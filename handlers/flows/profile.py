"""
profile.py

Обработчик кнопки «Профиль».
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from database import ensure_user, get_user, get_user_references
from handlers.keyboards import BTN_PROFILE

logger = logging.getLogger(__name__)


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("MENU_PROFILE | user_id=%s | username=%s", user.id, user.username)
    await ensure_user(user.id, user.username)

    db_user = await get_user(user.id)
    refs = await get_user_references(user.id)

    ref_count = len(refs)
    balance = db_user["balance"] if db_user else 0

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"У Вас <b>{ref_count}</b> эталон(ов)\n"
        f"Баланс: <b>{balance}</b> руб."
    )

    # Если это сообщение с кнопкой меню — удаляем его
    if update.message and update.message.text == BTN_PROFILE:
        from handlers.flows import clean_user_message
        await clean_user_message(update, context)

    await update.message.reply_text(text, parse_mode="HTML")
