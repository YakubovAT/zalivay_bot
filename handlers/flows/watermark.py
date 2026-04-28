"""
handlers/flows/watermark.py

Flow команды /watermark — нанесение артикула и названия товара на изображения.

Шаги:
  1. /watermark — считает фото без watermark, предлагает обработать
  2. Пользователь подтверждает → обрабатываем все, отправляем итог
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
)

from database.db import get_unwatermarked_photos
from handlers.keyboards import kb_watermark_confirm
from handlers.flows.messages.watermark import (
    msg_watermark_all_done,
    msg_watermark_confirm,
    msg_watermark_processing,
    msg_watermark_done,
    msg_watermark_failed_line,
    msg_watermark_cancel,
)
from services.image_watermark import apply_watermark_to_media_file

logger = logging.getLogger(__name__)

_CONFIRM = 0


async def cmd_watermark(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Точка входа: /watermark или menu_watermark."""
    user_id = update.effective_user.id

    photos = await get_unwatermarked_photos(user_id)
    caption = await msg_watermark_confirm(len(photos))
    keyboard = kb_watermark_confirm(len(photos))

    if not photos:
        msg_text = await msg_watermark_all_done()
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.edit_text(msg_text)
        else:
            await update.message.reply_text(msg_text)
        return ConversationHandler.END

    if update.callback_query:
        await update.callback_query.answer()
        from telegram import InputMediaPhoto
        await update.callback_query.message.edit_media(
            media=InputMediaPhoto(media=open("assets/banner_default.png", "rb"), caption=caption),
            reply_markup=keyboard,
        )
    else:
        await context.bot.send_photo(
            chat_id=user_id,
            photo=open("assets/banner_default.png", "rb"),
            caption=caption,
            reply_markup=keyboard,
        )
    return _CONFIRM


async def cb_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь подтвердил — обрабатываем все фото."""
    query = update.callback_query
    await query.answer()
    await query.message.edit_caption(caption=await msg_watermark_processing())

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

    result_text = await msg_watermark_done(done)
    if failed:
        result_text += "\n" + await msg_watermark_failed_line(failed)

    await query.message.edit_caption(caption=result_text)
    return ConversationHandler.END


async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь отменил."""
    query = update.callback_query
    await query.answer()
    await query.message.edit_caption(caption=await msg_watermark_cancel())
    return ConversationHandler.END


def build_watermark_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("watermark", cmd_watermark),
            CallbackQueryHandler(cmd_watermark, pattern="^menu_watermark$"),
        ],
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
