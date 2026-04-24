"""
handlers/flows/watermark.py

Flow команды /watermark — нанесение артикула и названия товара на изображения.

Шаги:
  1. /watermark — считает фото без watermark, предлагает обработать
  2. Пользователь подтверждает → обрабатываем все, отправляем итог
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
)

from database.db import get_unwatermarked_photos
from services.image_watermark import apply_watermark_to_media_file

logger = logging.getLogger(__name__)

_CONFIRM = 0


async def cmd_watermark(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Точка входа: /watermark."""
    user_id = update.effective_user.id

    photos = await get_unwatermarked_photos(user_id)
    if not photos:
        await update.message.reply_text(
            "Все ваши фото уже обработаны — артикул и название нанесены."
        )
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"Обработать {len(photos)} фото", callback_data="watermark_confirm"),
        InlineKeyboardButton("Отмена", callback_data="watermark_cancel"),
    ]])
    await update.message.reply_text(
        f"Фото без текста: {len(photos)}\n\n"
        f"На каждое фото будет нанесено:\n"
        f"• артикул товара (по диагонали)\n"
        f"• название товара (по диагонали)\n\n"
        f"Оригиналы остаются без изменений.",
        reply_markup=keyboard,
    )
    return _CONFIRM


async def cb_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь подтвердил — обрабатываем все фото."""
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Наношу текст на фото…")

    user_id = update.effective_user.id
    photos = await get_unwatermarked_photos(user_id)

    done = 0
    failed = 0
    for mf in photos:
        result = await apply_watermark_to_media_file(
            media_file_id=mf["id"],
            user_id=user_id,
        )
        if result:
            done += 1
        else:
            failed += 1

    lines = [f"Готово! Обработано фото: {done}"]
    if failed:
        lines.append(f"Не удалось обработать: {failed}")

    await query.message.edit_text("\n".join(lines))
    return ConversationHandler.END


async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь отменил."""
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Отменено.")
    return ConversationHandler.END


def build_watermark_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("watermark", cmd_watermark)],
        states={
            _CONFIRM: [
                CallbackQueryHandler(cb_confirm, pattern="^watermark_confirm$"),
                CallbackQueryHandler(cb_cancel,  pattern="^watermark_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("watermark", cmd_watermark)],
        name="watermark_flow",
        persistent=False,
    )
