"""
handlers/flows/create_reference.py

Шаг 8-11: Создание эталона товара.
  8. Проверка баланса
  9. T2T API → промпт + категория
  10. I2I API → генерация эталона
  11. Показ результата пользователю
"""

from __future__ import annotations

import asyncio
import logging
import os

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, ConversationHandler, ContextTypes

from config import REFERENCE_COST, AI_API_KEY, AI_API_BASE, AI_MODEL, I2I_API_KEY, I2I_API_BASE
from database import get_user_stats, deduct_balance, save_reference, get_reference_count
from handlers.flows.messages.common import msg_insufficient_funds
from services.reference_t2t import generate_reference_prompt
from services.reference_i2i import generate_reference_image
from services.image_merger import merge_photos_horizontal

logger = logging.getLogger(__name__)

# Состояние (13, чтобы не пересекаться с new_article 0-2 и photo_selection 10-12)
_REFERENCE_GENERATING = 13


def _kb_reference_result() -> InlineKeyboardMarkup:
    """Клавиатура после создания эталона."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📸 Генерировать фото", callback_data="menu_gen_photo"),
            InlineKeyboardButton("🎥 Генерировать видео", callback_data="menu_gen_video"),
        ],
        [
            InlineKeyboardButton("📂 Мои эталоны", callback_data="menu_my_refs"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


async def start_reference_generation(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    message_id: int,
) -> int:
    """Запускает процесс создания эталона. Вызывается из photo_selection после подтверждения."""
    from database import get_article_info

    article = context.user_data.get("article_code", "")
    chosen_paths = context.user_data.get("chosen_photo_paths", [])

    # Берём данные товара из БД (table articles), а не из user_data
    article_info = await get_article_info(user_id, article)
    name = article_info["name"] if article_info and article_info["name"] else "товар"
    color = article_info["color"] if article_info and article_info["color"] else "—"
    composition = article_info["material"] if article_info and article_info["material"] else ""

    logger.info("START_REFERENCE | user=%s article=%s name=%s color=%s material=%s",
                user_id, article, name, color, composition)

    # 1. Проверяем баланс
    stats = await get_user_stats(user_id)
    balance = stats["balance"]

    if balance < REFERENCE_COST:
        alert_msg = await context.bot.send_message(
            chat_id=user_id,
            text=msg_insufficient_funds(
                needed=REFERENCE_COST,
                balance=balance,
                purpose="Стоимость создания эталона",
            ),
        )
        asyncio.get_event_loop().call_later(
            5, lambda: asyncio.create_task(
                context.bot.delete_message(chat_id=user_id, message_id=alert_msg.message_id)
            )
        )
        # НЕ завершаем диалог — кнопка «Создать эталон» останется активной
        return _REFERENCE_GENERATING

    # 2. Показываем экран генерации
    await context.bot.edit_message_caption(
        chat_id=user_id,
        message_id=message_id,
        caption=f"⏳ Создаю эталон для артикула <code>{article}</code>...\n\n"
                f"<a href=\"https://zaliv.ai/\">Zaliv.AI</a> — сервис массовой автоматизированной генерации "
                f"профессионального фото и видео контента для товаров "
                f"с последующим размещением в социальных сетях.\n\n"
                f"Это займёт 1-3 минуты...",
        parse_mode="HTML",
    )

    # 3. T2T → промпт + категория
    async with aiohttp.ClientSession() as session:
        prompt_result = await generate_reference_prompt(
            session=session,
            name=name,
            color=color,
            material=composition,
            api_key=AI_API_KEY,
            api_base_url=AI_API_BASE,
            model=AI_MODEL,
        )

    if not prompt_result:
        await context.bot.edit_message_caption(
            chat_id=user_id,
            message_id=message_id,
            caption="❌ Не удалось сгенерировать промпт. Попробуйте снова или обратитесь в поддержку.",
        )
        return ConversationHandler.END

    category = prompt_result["category"]
    prompt = prompt_result["prompt"]
    logger.info("T2T DONE | category=%s prompt_len=%d", category, len(prompt))

    # 4. Обновляем caption
    await context.bot.edit_message_caption(
        chat_id=user_id,
        message_id=message_id,
        caption=f"⏳ Генерирую фото эталона...\n"
                f"Тип товара: {category}\n\n"
                f"Созданный эталон позволит вам массово генерировать "
                f"фото и видео для любых площадок: Telegram, VK, "
                f"Instagram, YouTube и других социальных сетей.\n\n"
                f"Осталось немного...",
    )

    # 6. Создаём коллаж для I2I (не показываем пользователю)
    if not chosen_paths:
        await context.bot.edit_message_caption(
            chat_id=user_id,
            message_id=message_id,
            caption="❌ Не найдены выбранные фото. Начните заново.",
        )
        return ConversationHandler.END

    merged_path = f"media/{user_id}/temp/{article}_reference_input.png"
    merge_ok = merge_photos_horizontal(chosen_paths, merged_path, target_height=350, spacing=8)

    if not merge_ok or not os.path.exists(merged_path):
        await context.bot.edit_message_caption(
            chat_id=user_id,
            message_id=message_id,
            caption="❌ Ошибка создания коллажа. Попробуйте выбрать фото заново.",
        )
        return ConversationHandler.END

    # Отправляем коллаж ТОЛЬКО чтобы получить Telegram file_id и URL
    # Сразу удаляем после получения URL — пользователь не должен это видеть
    sent_collage_msg = await context.bot.send_photo(
        chat_id=user_id,
        photo=open(merged_path, "rb"),
    )
    file_obj = await context.bot.get_file(sent_collage_msg.photo[-1].file_id)
    file_url = file_obj.file_path

    # Удаляем сообщение с коллажем
    try:
        await context.bot.delete_message(chat_id=user_id, message_id=sent_collage_msg.message_id)
    except Exception:
        pass  # Игнорируем ошибки удаления

    # 7. I2I → генерация эталона
    async with aiohttp.ClientSession() as session:
        result_url = await generate_reference_image(
            session=session,
            api_base=I2I_API_BASE,
            api_key=I2I_API_KEY,
            image_urls=[file_url],
            prompt=prompt,
        )

    if not result_url:
        await context.bot.edit_message_caption(
            chat_id=user_id,
            message_id=message_id,
            caption="❌ Не удалось сгенерировать эталон. Средства не списаны. Попробуйте снова.",
        )
        return ConversationHandler.END

    logger.info("I2I DONE | result_url=%s", result_url)

    # 8. Скачиваем результат
    result_local = f"media/{user_id}/references/{article}_ref_final.png"
    os.makedirs(os.path.dirname(result_local), exist_ok=True)

    async with aiohttp.ClientSession() as session:
        async with session.get(result_url) as resp:
            if resp.status == 200:
                with open(result_local, "wb") as f:
                    f.write(await resp.read())

    # 9. Списываем баланс
    new_balance = await deduct_balance(user_id, REFERENCE_COST)

    # 10. Определяем reference_number
    ref_count = await get_reference_count(user_id, article)
    reference_number = ref_count + 1

    # 11. Редактируем исходное сообщение с результатом
    from telegram import InputMediaPhoto
    
    # Сначала сохраняем в БД (file_id получим после отправки/редактирования)
    # Отправляем фото для получения file_id (но не показываем пользователю)
    temp_msg = await context.bot.send_photo(
        chat_id=user_id,
        photo=open(result_local, "rb"),
    )
    file_id = temp_msg.photo[-1].file_id
    
    # Удаляем временное сообщение
    try:
        await context.bot.delete_message(chat_id=user_id, message_id=temp_msg.message_id)
    except Exception:
        pass

    # Сохраняем в БД
    await save_reference(
        user_id=user_id,
        articul=article,
        reference_number=reference_number,
        file_id=file_id,
        file_path=result_local,
        reference_image_url=result_url,
        category=category,
        reference_prompt=prompt,
        product_name=name,
        product_color=color,
        product_material=composition,
    )

    logger.info("REFERENCE SAVED | user=%s article=%s ref=%d file_id=%s",
                user_id, article, reference_number, file_id)

    # Редактируем исходное сообщение с финальным результатом
    final_caption = (
        f"Шаг 11 из N: Эталон готов!\n\n"
        f"📦 Артикул: <code>{article}</code>\n"
        f"📸 Это ваш {reference_number}-й эталон для этого товара\n"
        f"🏷 Тип товара: {category}\n\n"
        f"💰 Списано: {REFERENCE_COST}₽\n"
        f"💳 Ваш баланс: {new_balance}₽\n\n"
        f"Эталон может немного отличаться от оригинала.\n"
        f"Если отличия значительные — перегенерируйте эталон,\n"
        f"заменив фотографии на шаге выбора фото.\n\n"
        f"Теперь вы можете генерировать фото и видео!"
    )
    try:
        await context.bot.edit_message_media(
            chat_id=user_id,
            message_id=message_id,
            media=InputMediaPhoto(media=file_id, caption=final_caption, parse_mode="HTML"),
            reply_markup=_kb_reference_result(),
        )
    except Exception:
        # Если редактирование media не сработало — отправляем новое
        await context.bot.send_photo(
            chat_id=user_id,
            photo=open(result_local, "rb"),
            caption=final_caption,
            parse_mode="HTML",
            reply_markup=_kb_reference_result(),
        )

    return ConversationHandler.END


async def cb_back_to_menu_from_reference(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возврат в главное меню из flow создания эталона."""
    from handlers.flows.onboarding import cb_back_to_menu
    return await cb_back_to_menu(update, context)


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_reference_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[],  # Вызывается программно через start_reference_generation
        states={
            _REFERENCE_GENERATING: [
                CallbackQueryHandler(cb_back_to_menu_from_reference, pattern="^back_to_menu$"),
            ],
        },
        fallbacks=[],
        name="create_reference",
        persistent=False,
    )
