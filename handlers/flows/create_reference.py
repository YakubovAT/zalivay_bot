"""
handlers/flows/create_reference.py

Шаг 8-11: Создание эталона товара.
  8. Проверка баланса
  9. T2T API → промпт + категория
  10. I2I API → создание эталона
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
from handlers.flows.messages.common import msg_insufficient_funds, kb_alert_close
from services.reference_t2t import generate_reference_prompt
from services.reference_i2i import generate_reference_image

logger = logging.getLogger(__name__)

# Состояние (13, чтобы не пересекаться с new_article 0-2 и photo_selection 10-12)
_REFERENCE_GENERATING = 13

_REFERENCE_CREATING_TEXT_FALLBACK = (
    "⏳ Создаю эталон для артикула <code>{article}</code>...\n\n"
    "<a href=\"https://zaliv.ai/\">Zaliv.AI</a> — сервис массовой автоматизированной создания "
    "профессионального фото и видео контента для товаров "
    "с последующим размещением в социальных сетях.\n\n"
    "Это займёт 1-3 минуты..."
)

_REFERENCE_GENERATING_PHOTO_TEXT_FALLBACK = (
    "⏳ Создаю фото эталона...\n"
    "Тип товара: {category}\n\n"
    "Созданный эталон позволит вам массово создавать "
    "фото и видео для любых площадок: Telegram, VK, "
    "Instagram, YouTube и других социальных сетей.\n\n"
    "Осталось немного..."
)

_REFERENCE_READY_TEXT_FALLBACK = (
    "Шаг 11 из N: Эталон готов!\n\n"
    "📦 Артикул: <code>{article}</code>\n"
    "📸 Это ваш {reference_number}-й эталон для этого товара\n"
    "🏷 Тип товара: {category}\n\n"
    "💰 Списано: {reference_cost}₽\n"
    "💳 Ваш баланс: {new_balance}₽\n\n"
    "Эталон может немного отличаться от оригинала.\n"
    "Если отличия значительные — пересоздайте эталон,\n"
    "заменив фотографии на шаге выбора фото.\n\n"
    "Теперь вы можете создавать фото и видео!"
)


def _kb_reference_result() -> InlineKeyboardMarkup:
    """Клавиатура после создания эталона."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📸 Создать фото", callback_data="menu_gen_photo"),
            InlineKeyboardButton("🎥 Создать видео", callback_data="menu_gen_video"),
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
    from services.prompt_store import get_template

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
        alert_msg = await context.bot.send_photo(
            chat_id=user_id,
            photo=open("assets/banner_default.png", "rb"),
            caption=await msg_insufficient_funds(
                needed=REFERENCE_COST,
                balance=balance,
                purpose="Стоимость создания эталона",
            ),
            parse_mode="HTML",
            reply_markup=kb_alert_close(),
        )
        # НЕ завершаем диалог — кнопка «Создать эталон» останется активной
        return _REFERENCE_GENERATING

    # 2. Показываем экран создания
    creating_text = await get_template("msg_reference_creating", fallback=_REFERENCE_CREATING_TEXT_FALLBACK)
    await context.bot.edit_message_caption(
        chat_id=user_id,
        message_id=message_id,
        caption=creating_text.format(article=article),
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
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Не удалось создать промпт. Попробуйте снова или обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Закрыть", callback_data="close_error")]]),
        )
        return ConversationHandler.END

    category = prompt_result["category"]
    prompt_i2i = prompt_result["prompt_i2i"]
    description = prompt_result.get("description", "")
    logger.info("T2T DONE | category=%s prompt_len=%d desc_len=%d", category, len(prompt_i2i), len(description))

    # 4. Обновляем caption
    generating_photo_text = await get_template(
        "msg_reference_generating_photo",
        fallback=_REFERENCE_GENERATING_PHOTO_TEXT_FALLBACK,
    )
    await context.bot.edit_message_caption(
        chat_id=user_id,
        message_id=message_id,
        caption=generating_photo_text.format(category=category),
    )

    # 6. Создаём коллаж для I2I (не показываем пользователю)
    if not chosen_paths:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Не найдены выбранные фото. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Закрыть", callback_data="close_error")]]),
        )
        return ConversationHandler.END

    # Загружаем каждое оригинальное фото в Telegram чтобы получить публичный CDN URL
    image_urls = []
    temp_msg_ids = []
    for path in chosen_paths:
        sent = await context.bot.send_photo(chat_id=user_id, photo=open(path, "rb"))
        temp_msg_ids.append(sent.message_id)
        file_obj = await context.bot.get_file(sent.photo[-1].file_id)
        image_urls.append(file_obj.file_path)
    for msg_id in temp_msg_ids:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
        except Exception:
            pass

    # 7. I2I → создание эталона (передаём все оригинальные фото)
    async with aiohttp.ClientSession() as session:
        result_url = await generate_reference_image(
            session=session,
            api_base=I2I_API_BASE,
            api_key=I2I_API_KEY,
            image_urls=image_urls,
            prompt=prompt_i2i,
        )

    if not result_url:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Не удалось создать эталон. Средства не списаны. Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Закрыть", callback_data="close_error")]]),
        )
        return ConversationHandler.END

    logger.info("I2I DONE | result_url=%s", result_url)

    # 8. Определяем reference_number до скачивания файла (для имени файла)
    ref_count = await get_reference_count(user_id, article)
    reference_number = ref_count + 1

    # 9. Скачиваем результат
    result_local = f"media/{user_id}/references/{article}_ref_{reference_number}.png"
    os.makedirs(os.path.dirname(result_local), exist_ok=True)

    async with aiohttp.ClientSession() as session:
        async with session.get(result_url) as resp:
            if resp.status == 200:
                with open(result_local, "wb") as f:
                    f.write(await resp.read())

    # 10. Списываем баланс
    new_balance = await deduct_balance(user_id, REFERENCE_COST)

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
    import json as _json
    await save_reference(
        user_id=user_id,
        articul=article,
        reference_number=reference_number,
        file_id=file_id,
        file_path=result_local,
        reference_image_url=result_url,
        category=category,
        reference_prompt=prompt_i2i,
        product_description=description,
        product_name=name,
        product_color=color,
        product_material=composition,
        source_photo_paths=_json.dumps(chosen_paths),
    )

    logger.info("REFERENCE SAVED | user=%s article=%s ref=%d file_id=%s",
                user_id, article, reference_number, file_id)

    # Редактируем исходное сообщение с финальным результатом
    ready_text = await get_template("msg_reference_ready", fallback=_REFERENCE_READY_TEXT_FALLBACK)
    final_caption = ready_text.format(
        article=article,
        reference_number=reference_number,
        category=category,
        reference_cost=REFERENCE_COST,
        new_balance=new_balance,
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


async def cb_close_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Закрыть алерт-сообщение (недостаточно средств и т.п.)."""
    query = update.callback_query
    await query.answer()
    from handlers.flows.photo_selection import _REFERENCE_CONFIRM
    logger.info("CB_CLOSE_ALERT | deleting msg_id=%s returning state=%d", query.message.message_id, _REFERENCE_CONFIRM)
    await query.message.delete()
    # Возвращаемся к экрану подтверждения создания эталона
    return _REFERENCE_CONFIRM


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_reference_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[],  # Вызывается программно через start_reference_generation
        states={
            _REFERENCE_GENERATING: [
                CallbackQueryHandler(cb_back_to_menu_from_reference, pattern="^back_to_menu$"),
                # Повторное нажатие «Создать эталон» — перезапуск проверки баланса
                CallbackQueryHandler(cb_retry_reference, pattern="^ref_create_yes$"),
            ],
        },
        fallbacks=[],
        name="create_reference",
        persistent=False,
    )


async def cb_retry_reference(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Повторная попытка создания эталона (после алерта о недостатке средств)."""
    query = update.callback_query
    await query.answer()
    return await start_reference_generation(context, update.effective_user.id, query.message.message_id)
