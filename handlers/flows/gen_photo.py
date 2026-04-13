"""
handlers/flows/gen_photo.py

Flow генерации фото.
"""

from __future__ import annotations

import logging

from telegram.ext import CallbackQueryHandler, ContextTypes

logger = logging.getLogger(__name__)


def build_gen_photo_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(_stub, pattern="^menu_gen_photo$")


async def _stub(update, context):
    await update.callback_query.answer("⏳ Скоро будет доступно", show_alert=True)
