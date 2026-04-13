"""
handlers/flows/gen_video.py

Flow генерации видео.
"""

from __future__ import annotations

import logging

from telegram.ext import CallbackQueryHandler, ContextTypes

logger = logging.getLogger(__name__)


def build_gen_video_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(_stub, pattern="^menu_gen_video$")


async def _stub(update, context):
    await update.callback_query.answer("⏳ Скоро будет доступно", show_alert=True)
