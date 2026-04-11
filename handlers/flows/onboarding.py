"""
handlers/flows/onboarding.py

Шаг 1: Приветствие (/start)
Шаг 2: Профиль пользователя (статистика + главное меню)
"""

from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
)

from database import ensure_user, get_user_stats
from handlers.flows.flow_helpers import send_screen, clear_previous_screen
from handlers.keyboards import kb_start, kb_main_menu

# Баннер для первого экрана приветствия
WELCOME_BANNER = "assets/welcom_banner_1.png"

logger = logging.getLogger(__name__)

# Состояния
_WELCOME, _MAIN_MENU = range(2)


# ---------------------------------------------------------------------------
# Шаг 1. Приветствие
# ---------------------------------------------------------------------------

_WELCOME_TEXT = (
    "Система массовой автоматизированной генерации профессионального\n"
    "фото и видео контента для товаров с последующим размещением в социальных сетях.\n\n"
    "Возможно создавать фото и видео в различных форматах\n"
    "по заранее спроектированным промптам для ваших товаров."
)


async def _show_profile(update, context, message_id=None):
    """Показывает профиль пользователя в формате «окошек»."""
    user = update.effective_user if hasattr(update, 'effective_user') else update.from_user
    stats = await get_user_stats(user.id)

    text = (
        f"👤 *Профиль:*\n"
        f"> • ID: `{user.id}`\n"
        f"> • Имя: {user.full_name}\n\n"
        f"📊 *Статистика:*\n"
        f"> • Товаров: {stats['articles']}\n"
        f"> • Эталонов: {stats['references']}\n"
        f"> • Фото: {stats['photos']}\n"
        f"> • Видео: {stats['videos']}\n"
        f"> • Баланс: {stats['balance']}₽"
    )

    await send_screen(
        context.bot,
        chat_id=user.id,
        message_id=message_id,
        text=text,
        keyboard=kb_main_menu(),
        parse_mode="MarkdownV2",
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /start — удаляем предыдущие экраны, показываем приветствие."""
    user = update.effective_user
    logger.info("START | user=%s name=%s", user.id, user.full_name)

    await ensure_user(user.id, user.username)

    # Удаляем предыдущий экран (если есть)
    await clear_previous_screen(context.bot, user.id)

    await send_screen(
        context.bot,
        chat_id=user.id,
        text=_WELCOME_TEXT,
        keyboard=kb_start(),
        banner_path=WELCOME_BANNER,
    )
    return _WELCOME


async def cb_start_begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь нажал «Начать ➜» — показываем профиль."""
    query = update.callback_query
    await query.answer()
    await _show_profile(update, context, message_id=query.message.message_id)
    return _MAIN_MENU


# ---------------------------------------------------------------------------
# Навигация: возврат в меню
# ---------------------------------------------------------------------------

async def cb_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка «🏠 Меню» из любого экрана."""
    query = update.callback_query
    await query.answer()
    await _show_profile(update, context, message_id=query.message.message_id)
    return _MAIN_MENU


# ---------------------------------------------------------------------------
# Заглушки для пунктов меню (будут реализованы в следующих шагах)
# ---------------------------------------------------------------------------

async def cb_menu_not_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Заглушка для кнопок меню которые ещё не реализованы."""
    query = update.callback_query
    await query.answer("⏳ Скоро будет доступно", show_alert=True)
    return _MAIN_MENU


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            _WELCOME: [
                CallbackQueryHandler(cb_start_begin, pattern="^start_begin$"),
            ],
            _MAIN_MENU: [
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cb_menu_not_impl, pattern="^menu_"),
            ],
        },
        fallbacks=[],
        allow_reentry=True,
        name="onboarding",
        persistent=False,
    )
