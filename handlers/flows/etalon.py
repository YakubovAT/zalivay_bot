"""
handlers/flows/etalon.py

Шаг 15: Список товаров пользователя (Мои эталоны).
Показывает артикулы пользователя в виде inline-кнопок с количеством эталонов.
"""

from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, ConversationHandler, ContextTypes

from database import get_user_articles_with_refs
from handlers.flows.flow_helpers import send_screen

logger = logging.getLogger(__name__)

# Состояние
_MY_REFS_LIST = 20


async def cb_menu_my_refs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает список товаров пользователя с количеством эталонов."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    message_id = query.message.message_id

    articles = await get_user_articles_with_refs(user_id)

    if not articles:
        text = (
            "📂 Мои эталоны\n\n"
            "У вас пока нет товаров с эталонами.\n\n"
            "Создайте первый эталон, чтобы генерировать "
            "фото и видео для ваших товаров."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Добавить товар", callback_data="menu_new_article")],
            [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")],
        ])
    else:
        text = (
            "📂 Мои эталоны\n\n"
            "Ниже ваши артикулы с эталонами.\n"
            "Нажмите на артикул — откроется меню работы с эталонами."
        )

        buttons = []
        row = []
        for article in articles:
            code = article["article_code"]
            ref_count = article["ref_count"] or 0

            btn_text = f"📦 {code} ({ref_count})"
            row.append(InlineKeyboardButton(btn_text, callback_data=f"ref_article_{code}"))

            if len(row) == 2:
                buttons.append(row)
                row = []

        if row:
            buttons.append(row)

        buttons.append([InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")])
        keyboard = InlineKeyboardMarkup(buttons)

    await send_screen(
        context.bot,
        chat_id=user_id,
        message_id=message_id,
        text=text,
        keyboard=keyboard,
    )
    return _MY_REFS_LIST


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_etalon_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_menu_my_refs, pattern="^menu_my_refs$"),
        ],
        states={
            _MY_REFS_LIST: [
                CallbackQueryHandler(cb_menu_my_refs, pattern="^menu_my_refs$"),
            ],
        },
        fallbacks=[],
        name="etalon_list",
        persistent=False,
    )
