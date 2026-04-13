"""
handlers/flows/gen_photo.py

Flow генерации фото на основе эталона.

Шаги по SCENARIO.md:
  P1. Сколько фото? (текстовый ввод)
  P2. Пожелания (текст или «Пропустить»)
  P3. Проверка баланса и подтверждение
  P4. Генерация (I2I)
  P5. Результат (альбом)
"""

from __future__ import annotations

import asyncio
import logging
import os

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import PHOTO_COST, I2I_API_BASE, I2I_API_KEY
from database import get_user_stats, deduct_balance, get_reference, get_active_references
from handlers.flows.flow_helpers import safe_delete
from handlers.keyboards import (
    kb_gen_photo_count,
    kb_gen_photo_wish,
    kb_gen_photo_confirm,
    kb_gen_photo_result,
)
from services.prompt_generator_cloth import generate_photo_prompts
from services.lifestyle_photo_generator import generate_lifestyle_photo

logger = logging.getLogger(__name__)

# Состояния
_P_COUNT, _P_WISH, _P_CONFIRM, _P_GENERATING = range(4)


# ---------------------------------------------------------------------------
# Entry point — нажали «📸 Генерировать фото»
# ---------------------------------------------------------------------------

async def cb_menu_gen_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вход в flow генерации фото."""
    query = update.callback_query
    await query.answer()

    # Проверяем, пришли ли из карточки эталона (эталон уже выбран)
    article = context.user_data.get("article_code")
    ref_number = context.user_data.get("ref_number_for_gen")

    if not article or ref_number is None:
        # Пришли из главного меню — перенаправляем на «Мои эталоны»
        context.user_data["redirect_to_gen_photo"] = True
        await update.effective_user.send_message(
            text="Сначала выберите артикул и эталон из списка «Мои эталоны»."
        )
        from handlers.flows.etalon import cb_menu_my_refs
        await cb_menu_my_refs(update, context)
        return ConversationHandler.END

    # Эталон известен — показываем экран P1
    ref = await get_reference(update.effective_user.id, article, ref_number)
    if not ref:
        await query.edit_message_text("❌ Эталон не найден.")
        return ConversationHandler.END

    # Считаем индекс эталона для навигации
    refs = await get_active_references(update.effective_user.id, article)
    ref_index = 0
    if refs:
        for i, r in enumerate(refs):
            if r["reference_number"] == ref_number:
                ref_index = i
                break

    context.user_data["gen_article"] = article
    context.user_data["gen_ref_number"] = ref_number
    context.user_data["gen_ref_index"] = ref_index
    context.user_data["gen_ref"] = dict(ref)
    context.user_data["_screen_msg"] = query.message.message_id

    text = (
        "Сколько фото сгенерировать на основе этого эталона?\n\n"
        "Вы можете сгенерировать одно или множество изображений.\n"
        "Каждое фото будет уникальным — разная локация, освещение, ракурс.\n\n"
        f"📦 Артикул: <code>{article}</code>\n"
        f"📸 Эталон: #{ref_number}\n"
        f"🏷 Тип товара: {ref.get('category', '—')}\n\n"
        f"💰 Стоимость: {PHOTO_COST}₽ за фото\n\n"
        "Введите число:"
    )

    await context.bot.edit_message_caption(
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        caption=text,
        parse_mode="HTML",
        reply_markup=kb_gen_photo_count(),
    )
    return _P_COUNT


# ---------------------------------------------------------------------------
# P1. Сколько фото?
# ---------------------------------------------------------------------------

async def msg_photo_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл количество фото."""
    user = update.effective_user
    text = update.message.text.strip()

    # Удаляем сообщение пользователя
    asyncio.get_event_loop().call_later(
        0, lambda: asyncio.create_task(safe_delete(context.bot, user.id, update.message.message_id))
    )

    try:
        count = int(text)
        if count < 1 or count > 20:
            await context.bot.send_message(
                chat_id=user.id,
                text="Введите число от 1 до 20:",
            )
            return _P_COUNT
    except ValueError:
        await context.bot.send_message(
            chat_id=user.id,
            text="Пожалуйста, введите число (от 1 до 20):",
        )
        return _P_COUNT

    context.user_data["gen_count"] = count

    # Показываем экран P2 — Пожелания
    msg = await context.bot.send_message(
        chat_id=user.id,
        text=(
            "У вас будут пожелания к генерации?\n\n"
            'Например: «хочу фото на фоне моря», «сделай в студии».\n\n'
            'Или напишите «Пропустить» — я сам подберу лучшие локации\n'
            "и условия для вашего типа товара."
        ),
        reply_markup=kb_gen_photo_wish(),
    )
    context.user_data["gen_intermediate_msg"] = msg.message_id
    return _P_WISH


# ---------------------------------------------------------------------------
# P2. Пожелания
# ---------------------------------------------------------------------------

async def msg_photo_wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл пожелания или написал «Пропустить»."""
    user = update.effective_user
    text = update.message.text.strip()

    # Удаляем сообщение пользователя
    asyncio.get_event_loop().call_later(
        0, lambda: asyncio.create_task(safe_delete(context.bot, user.id, update.message.message_id))
    )

    wish = None if text.lower() in ("пропустить", "пропуск", "skip", "нет") else text
    context.user_data["gen_wish"] = wish

    # Удаляем промежуточное сообщение
    inter_msg = context.user_data.get("gen_intermediate_msg")
    if inter_msg:
        await safe_delete(context.bot, user.id, inter_msg)

    # Показываем экран P3 — Подтверждение
    article = context.user_data["gen_article"]
    ref_number = context.user_data["gen_ref_number"]
    ref = context.user_data["gen_ref"]
    count = context.user_data["gen_count"]
    total_cost = count * PHOTO_COST

    wish_line = f'📝 Пожелания: "{wish}"' if wish else ""

    # Проверяем баланс
    stats = await get_user_stats(user.id)
    balance = stats["balance"]

    if balance < total_cost:
        # Недостаточно средств — алерт
        alert_msg = await context.bot.send_message(
            chat_id=user.id,
            text=(
                f"❌ Недостаточно средств.\n\n"
                f"💰 Нужно: {total_cost}₽\n"
                f"💳 Ваш баланс: {balance}₽\n\n"
                f"Пополните баланс и попробуйте снова."
            ),
        )
        asyncio.get_event_loop().call_later(
            5, lambda: asyncio.create_task(safe_delete(context.bot, user.id, alert_msg.message_id))
        )
        return _P_COUNT

    final_caption = (
        f"Готов генерировать {count} фото на основе Эталона #{ref_number}\n\n"
        f"📦 Артикул: <code>{article}</code>\n"
        f"🏷 Тип товара: {ref.get('category', '—')}\n"
        f"{wish_line}\n\n"
        f"💰 Стоимость: {total_cost}₽\n"
        f"💳 Ваш баланс: {balance}₽"
    )

    screen_msg = context.user_data.get("_screen_msg")
    if screen_msg:
        await context.bot.edit_message_caption(
            chat_id=user.id,
            message_id=screen_msg,
            caption=final_caption,
            parse_mode="HTML",
            reply_markup=kb_gen_photo_confirm(),
        )
    return _P_CONFIRM


# ---------------------------------------------------------------------------
# P3. Подтверждение
# ---------------------------------------------------------------------------

async def cb_gen_photo_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь подтвердил генерацию."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    article = context.user_data["gen_article"]
    ref_number = context.user_data["gen_ref_number"]
    ref = context.user_data["gen_ref"]
    count = context.user_data["gen_count"]
    wish = context.user_data.get("gen_wish")

    logger.info("GEN_PHOTO_START | user=%s article=%s ref=%d count=%d", user_id, article, ref_number, count)

    return await _start_generation(update, context, user_id, article, ref_number, ref, count, wish)


async def _start_generation(
    update, context, user_id: int, article: str, ref_number: int,
    ref: dict, count: int, wish: str | None,
) -> int:
    """Запускает генерацию N фото."""
    total_cost = count * PHOTO_COST
    screen_msg = context.user_data.get("_screen_msg")

    await context.bot.edit_message_caption(
        chat_id=user_id,
        message_id=screen_msg,
        caption=(
            f"⏳ Генерирую {count} фото для артикула <code>{article}</code>...\n\n"
            "Это может занять несколько минут.\n"
            "Я пришлю результат когда будет готово."
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")],
        ]),
    )

    # Запускаем генерацию в фоне
    asyncio.create_task(
        _generate_photos(context.bot, user_id, article, ref, count, wish, total_cost)
    )

    return _P_GENERATING


# ---------------------------------------------------------------------------
# Генерация (фоновая задача)
# ---------------------------------------------------------------------------

async def _generate_photos(
    bot, user_id: int, article: str, ref: dict,
    count: int, wish: str | None, total_cost: int,
) -> None:
    """Генерирует N фото и отправляет пользователю."""
    ref_prompt = ref.get("reference_prompt", "")
    ref_image_url = ref.get("reference_image_url", "")

    if not ref_image_url:
        logger.error("GEN_PHOTO | no_ref_image_url | user=%s", user_id)
        await bot.send_message(
            chat_id=user_id,
            text="❌ Эталон не содержит изображения. Создайте эталон заново.",
        )
        return

    # Генерируем N уникальных промптов
    product_name = ref.get("product_name", "товар")
    product_color = ref.get("product_color", "neutral")
    product_material = ref.get("product_material", "")
    category = ref.get("category", "верх")
    ref_prompt = ref.get("reference_prompt", "")  # Базовый промпт из эталона

    base_prompts = generate_photo_prompts(
        name=product_name,
        color=product_color,
        material=product_material,
        category=category,
        count=count,
    )

    # Добавляем reference_prompt к каждому промпту
    # Если есть пожелания — тоже встраиваем
    prompts = []
    for base in base_prompts:
        parts = []
        if ref_prompt:
            parts.append(ref_prompt)
        if wish:
            parts.append(wish)
        parts.append(base)
        prompts.append(", ".join(parts))

    # Папка для сохранения
    save_dir = f"media/{user_id}/generated/{article}"
    os.makedirs(save_dir, exist_ok=True)

    results = []
    errors = 0

    async with aiohttp.ClientSession() as session:
        for i, prompt in enumerate(prompts):
            logger.info("GEN_PHOTO | i2i_call | user=%s i=%d/%d", user_id, i + 1, count)

            # Используем reference_image_url эталона как входное изображение
            ref_image_url = ref.get("reference_image_url", "")

            result_url = await generate_lifestyle_photo(
                session=session,
                api_base=I2I_API_BASE,
                api_key=I2I_API_KEY,
                ref_image_url=ref_image_url,
                prompt=prompt,
            )

            if not result_url:
                errors += 1
                continue

            # Скачиваем результат
            save_path = f"{save_dir}/photo_{article}_{i + 1}.png"
            try:
                async with session.get(result_url) as resp:
                    if resp.status == 200:
                        with open(save_path, "wb") as f:
                            f.write(await resp.read())
                        results.append(save_path)
            except Exception as e:
                logger.error("GEN_PHOTO | download_failed | i=%d error=%s", i, e)
                errors += 1

    # Списываем баланс
    new_balance = await deduct_balance(user_id, total_cost)

    # Отправляем результат
    if results:
        batch_size = 10
        for batch_start in range(0, len(results), batch_size):
            batch = results[batch_start:batch_start + batch_size]

            caption = (
                f"📸 Готово! {len(results)} фото для артикула <code>{article}</code>\n\n"
                f"📦 Эталон: #{ref.get('reference_number', '—')}\n"
                f"💰 Списано: {total_cost}₽\n"
                f"💳 Остаток: {new_balance}₽"
                + (f"\n⚠️ Ошибок: {errors}" if errors else "")
            )

            if len(batch) == 1:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=open(batch[0], "rb"),
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=kb_gen_photo_result(),
                )
            else:
                media_group = [InputMediaPhoto(media=open(p, "rb")) for p in batch]
                await bot.send_media_group(chat_id=user_id, media=media_group)
                await bot.send_message(
                    chat_id=user_id,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=kb_gen_photo_result(),
                )
    else:
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"❌ Не удалось сгенерировать фото.\n\n"
                f"💰 Списано: {total_cost}₽\n"
                f"💳 Остаток: {new_balance}₽\n\n"
                f"Попробуйте снова или обратитесь в поддержку."
            ),
            reply_markup=kb_gen_photo_result(),
        )

    logger.info(
        "GEN_PHOTO_DONE | user=%s article=%s count=%d success=%d errors=%d",
        user_id, article, count, len(results), errors,
    )


# ---------------------------------------------------------------------------
# Навигация — назад
# ---------------------------------------------------------------------------

async def cb_back_to_ref_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к карточке эталона."""
    from handlers.flows.etalon import show_ref_card
    user_id = update.effective_user.id
    article = context.user_data.get("gen_article")
    ref_number = context.user_data.get("gen_ref_number")
    ref_index = context.user_data.get("gen_ref_index", 0)
    if article and ref_number:
        # Сохраняем article_code и ref_number_for_gen как в etalon.py
        context.user_data["article_code"] = article
        context.user_data["ref_number_for_gen"] = ref_number
        # Возвращаемся к карточке эталона напрямую
        return await show_ref_card(update.effective_user, article, ref_index, context.bot, update.callback_query)
    from handlers.flows.onboarding import cb_back_to_menu
    return await cb_back_to_menu(update, context)


async def cb_back_to_p_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к вводу числа."""
    query = update.callback_query
    await query.answer()

    inter_msg = context.user_data.get("gen_intermediate_msg")
    if inter_msg:
        await safe_delete(context.bot, update.effective_user.id, inter_msg)

    article = context.user_data.get("gen_article", "")
    ref_number = context.user_data.get("gen_ref_number", "")
    ref = context.user_data.get("gen_ref", {})

    text = (
        "Сколько фото сгенерировать на основе этого эталона?\n\n"
        "Вы можете сгенерировать одно или множество изображений.\n"
        "Каждое фото будет уникальным — разная локация, освещение, ракурс.\n\n"
        f"📦 Артикул: <code>{article}</code>\n"
        f"📸 Эталон: #{ref_number}\n"
        f"🏷 Тип товара: {ref.get('category', '—')}\n\n"
        f"💰 Стоимость: {PHOTO_COST}₽ за фото\n\n"
        "Введите число:"
    )

    await context.bot.edit_message_caption(
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        caption=text,
        parse_mode="HTML",
        reply_markup=kb_gen_photo_count(),
    )
    return _P_COUNT


async def cb_back_to_p_wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к пожеланиям."""
    query = update.callback_query
    await query.answer()

    inter_msg = context.user_data.get("gen_intermediate_msg")
    if inter_msg:
        await safe_delete(context.bot, update.effective_user.id, inter_msg)

    msg = await context.bot.send_message(
        chat_id=update.effective_user.id,
        text=(
            "У вас будут пожелания к генерации?\n\n"
            'Например: «хочу фото на фоне моря», «сделай в студии».\n\n'
            'Или напишите «Пропустить» — я сам подберу лучшие локации\n'
            "и условия для вашего типа товара."
        ),
        reply_markup=kb_gen_photo_wish(),
    )
    context.user_data["gen_intermediate_msg"] = msg.message_id
    return _P_WISH


async def cb_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад в главное меню."""
    from handlers.flows.onboarding import cb_back_to_menu
    return await cb_back_to_menu(update, context)


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_gen_photo_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_menu_gen_photo, pattern="^menu_gen_photo$"),
        ],
        states={
            _P_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_photo_count),
                CallbackQueryHandler(cb_back_to_ref_card, pattern="^back_to_ref_card$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
            _P_WISH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_photo_wish),
                CallbackQueryHandler(cb_back_to_p_count, pattern="^back_to_p_count$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
            _P_CONFIRM: [
                CallbackQueryHandler(cb_gen_photo_yes, pattern="^gen_photo_yes$"),
                CallbackQueryHandler(cb_back_to_p_wish, pattern="^back_to_p_wish$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
            _P_GENERATING: [
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
        },
        fallbacks=[],
        name="gen_photo",
        persistent=False,
    )
