"""
handlers/flows/regen_reference.py

Шаг 16а: Перегенерация эталона с теми же исходными фотографиями.
Запускается из карточки эталона (Шаг 16) по кнопке «🔄 Перегенерировать».
"""

from __future__ import annotations

import json
import logging
import os

import aiohttp
from telegram import Update, InputMediaPhoto
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import REFERENCE_COST, AI_API_KEY, AI_API_BASE, AI_MODEL, I2I_API_KEY, I2I_API_BASE
from database import (
    get_user_stats, deduct_balance, save_reference,
    get_reference_count, get_reference, get_active_references,
)
from handlers.flows.messages.common import msg_insufficient_funds
from handlers.flows.messages.regen_reference import (
    msg_ref_card,
    msg_regen_wish,
    msg_regen_generating,
    msg_regen_result,
    msg_regen_no_source_photos,
)
from handlers.keyboards import kb_ref_card, kb_regen_wish, kb_regen_result
from services.reference_t2t import generate_reference_prompt
from services.reference_i2i import generate_reference_image
from services.image_merger import merge_photos_horizontal

logger = logging.getLogger(__name__)

_REGEN_WISH = 20


async def cb_regen_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь нажал «🔄 Перегенерировать» на карточке эталона."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    article = context.user_data.get("article_code", "")
    ref_number = context.user_data.get("ref_number_for_gen")

    if not article or ref_number is None:
        await query.answer("Ошибка: артикул или эталон не найден.", show_alert=True)
        return ConversationHandler.END

    ref = await get_reference(user_id, article, ref_number)
    if not ref:
        await query.answer("Эталон не найден.", show_alert=True)
        return ConversationHandler.END

    # Читаем пути исходных фото и проверяем наличие на диске
    raw = ref["source_photo_paths"]
    source_paths = json.loads(raw) if raw else []
    existing_paths = [p for p in source_paths if os.path.exists(p)]

    if not existing_paths:
        await context.bot.edit_message_caption(
            chat_id=user_id,
            message_id=query.message.message_id,
            caption=msg_regen_no_source_photos(article),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    context.user_data["regen_article"] = article
    context.user_data["regen_ref_number"] = ref_number
    context.user_data["regen_photo_paths"] = existing_paths
    context.user_data["regen_message_id"] = query.message.message_id

    await context.bot.edit_message_caption(
        chat_id=user_id,
        message_id=query.message.message_id,
        caption=msg_regen_wish(article, ref_number),
        parse_mode="HTML",
        reply_markup=kb_regen_wish(),
    )
    return _REGEN_WISH


async def _run_regen(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    message_id: int,
    wish: str | None = None,
) -> int:
    """Основная логика перегенерации: T2T → I2I → сохранение в БД."""
    from database import get_article_info

    article = context.user_data.get("regen_article", "")
    chosen_paths = context.user_data.get("regen_photo_paths", [])

    article_info = await get_article_info(user_id, article)
    name = article_info["name"] if article_info and article_info["name"] else "товар"
    color = article_info["color"] if article_info and article_info["color"] else "—"
    material = article_info["material"] if article_info and article_info["material"] else ""

    # Проверка баланса
    stats = await get_user_stats(user_id)
    if stats["balance"] < REFERENCE_COST:
        await context.bot.edit_message_caption(
            chat_id=user_id,
            message_id=message_id,
            caption=msg_insufficient_funds(REFERENCE_COST, stats["balance"], "Стоимость перегенерации"),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await context.bot.edit_message_caption(
        chat_id=user_id,
        message_id=message_id,
        caption=msg_regen_generating(article),
        parse_mode="HTML",
    )

    # T2T → промпт + категория
    async with aiohttp.ClientSession() as session:
        prompt_result = await generate_reference_prompt(
            session=session,
            name=name,
            color=color,
            material=material,
            api_key=AI_API_KEY,
            api_base_url=AI_API_BASE,
            model=AI_MODEL,
        )

    if not prompt_result:
        await context.bot.edit_message_caption(
            chat_id=user_id,
            message_id=message_id,
            caption="❌ Не удалось сгенерировать промпт. Попробуйте снова.",
        )
        return ConversationHandler.END

    category = prompt_result["category"]
    prompt_i2i = prompt_result["prompt_i2i"]
    description = prompt_result.get("description", "")

    # Пожелания пользователя дописываются в конец промпта
    if wish:
        prompt_i2i = f"{prompt_i2i}. Additional notes: {wish}"

    # Коллаж из исходных фото
    merged_path = f"media/{user_id}/temp/{article}_regen_input.png"
    merge_ok = merge_photos_horizontal(chosen_paths, merged_path, target_height=350, spacing=8)
    if not merge_ok or not os.path.exists(merged_path):
        merged_path = chosen_paths[0]

    # Отправляем коллаж для получения публичного URL (Telegram CDN)
    sent = await context.bot.send_photo(chat_id=user_id, photo=open(merged_path, "rb"))
    file_obj = await context.bot.get_file(sent.photo[-1].file_id)
    file_url = file_obj.file_path
    try:
        await context.bot.delete_message(chat_id=user_id, message_id=sent.message_id)
    except Exception:
        pass

    # I2I → генерация нового эталона
    async with aiohttp.ClientSession() as session:
        result_url = await generate_reference_image(
            session=session,
            api_base=I2I_API_BASE,
            api_key=I2I_API_KEY,
            image_urls=[file_url],
            prompt=prompt_i2i,
        )

    if not result_url:
        await context.bot.edit_message_caption(
            chat_id=user_id,
            message_id=message_id,
            caption="❌ Не удалось сгенерировать эталон. Средства не списаны.",
        )
        return ConversationHandler.END

    # Новый номер — следующий после всех активных
    ref_count = await get_reference_count(user_id, article)
    reference_number = ref_count + 1

    result_local = f"media/{user_id}/references/{article}_ref_{reference_number}.png"
    os.makedirs(os.path.dirname(result_local), exist_ok=True)

    async with aiohttp.ClientSession() as session:
        async with session.get(result_url) as resp:
            if resp.status == 200:
                with open(result_local, "wb") as f:
                    f.write(await resp.read())

    new_balance = await deduct_balance(user_id, REFERENCE_COST)

    # Получаем Telegram file_id
    temp_msg = await context.bot.send_photo(chat_id=user_id, photo=open(result_local, "rb"))
    file_id = temp_msg.photo[-1].file_id
    try:
        await context.bot.delete_message(chat_id=user_id, message_id=temp_msg.message_id)
    except Exception:
        pass

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
        product_material=material,
        source_photo_paths=json.dumps(chosen_paths),
    )

    logger.info("REGEN SAVED | user=%s article=%s ref=%d", user_id, article, reference_number)

    # Обновляем ref_number для последующей генерации фото/видео
    context.user_data["ref_number_for_gen"] = reference_number

    final_caption = msg_regen_result(article, reference_number, category, REFERENCE_COST, new_balance)
    try:
        await context.bot.edit_message_media(
            chat_id=user_id,
            message_id=message_id,
            media=InputMediaPhoto(media=file_id, caption=final_caption, parse_mode="HTML"),
            reply_markup=kb_regen_result(),
        )
    except Exception:
        await context.bot.send_photo(
            chat_id=user_id,
            photo=open(result_local, "rb"),
            caption=final_caption,
            parse_mode="HTML",
            reply_markup=kb_regen_result(),
        )

    return ConversationHandler.END


async def cb_regen_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь пропустил ввод пожеланий — запускаем перегенерацию без корректировок."""
    query = update.callback_query
    await query.answer()
    return await _run_regen(context, update.effective_user.id, query.message.message_id)


async def msg_regen_wish_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл пожелания текстом."""
    wish = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass

    message_id = context.user_data.get("regen_message_id")
    if not message_id:
        return ConversationHandler.END

    return await _run_regen(context, update.effective_user.id, message_id, wish=wish)


async def cb_regen_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возврат к карточке эталона (Шаг 16)."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    article = context.user_data.get("regen_article", "")
    ref_number = context.user_data.get("regen_ref_number")

    refs = await get_active_references(user_id, article) if article else []
    if not refs:
        return ConversationHandler.END

    idx = next((i for i, r in enumerate(refs) if r["reference_number"] == ref_number), 0)
    ref = refs[idx]
    total = len(refs)

    caption = msg_ref_card(ref["reference_number"], total, article, ref["category"] or "—")
    keyboard = kb_ref_card(article, idx, total)

    try:
        await context.bot.edit_message_media(
            chat_id=user_id,
            message_id=query.message.message_id,
            media=InputMediaPhoto(media=ref["file_id"], caption=caption, parse_mode="HTML"),
            reply_markup=keyboard,
        )
    except Exception:
        pass

    return ConversationHandler.END


async def cb_back_to_menu_from_regen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возврат в главное меню из flow перегенерации."""
    from handlers.flows.onboarding import cb_back_to_menu
    return await cb_back_to_menu(update, context)


def build_regen_reference_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_regen_start, pattern=r"^ref_regen_"),
        ],
        states={
            _REGEN_WISH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_regen_wish_input),
                CallbackQueryHandler(cb_regen_skip, pattern="^regen_skip$"),
                CallbackQueryHandler(cb_regen_back, pattern="^regen_back$"),
                CallbackQueryHandler(cb_back_to_menu_from_regen, pattern="^back_to_menu$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cb_back_to_menu_from_regen, pattern="^back_to_menu$"),
        ],
        name="regen_reference",
        persistent=False,
    )
