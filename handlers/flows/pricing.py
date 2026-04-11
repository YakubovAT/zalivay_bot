"""
pricing.py

Обработчик кнопки «Прайс».
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from handlers.keyboards import BTN_PRICING

logger = logging.getLogger(__name__)


async def pricing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("MENU_PRICING | user_id=%s | username=%s", user.id, user.username)

    text = (
        "💰 <b>Прайс</b>\n\n"
        "🖼 Создание фото-эталона — <b>XX руб.</b>\n"
        "🎬 Создание видео-эталона — <b>XX руб.</b>\n\n"
        "По вопросам тарифов: @work_wb01"
    )

    if update.message and update.message.text == BTN_PRICING:
        from handlers.flows import clean_user_message
        await clean_user_message(update, context)

    await update.message.reply_text(text, parse_mode="HTML")
