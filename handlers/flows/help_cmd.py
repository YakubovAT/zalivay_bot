"""
help_cmd.py

Обработчик кнопки «Помощь».
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from handlers.keyboards import BTN_HELP

logger = logging.getLogger(__name__)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("MENU_HELP | user_id=%s | username=%s", user.id, user.username)

    text = "Если у вас возникли вопросы или нужна помощь — напишите нам: @work_wb01"

    if update.message and update.message.text == BTN_HELP:
        from handlers.flows import clean_user_message
        await clean_user_message(update, context)

    await update.message.reply_text(text)
