"""
handlers/flows/onboarding.py

Шаг 1: Приветствие (/start)
Шаг 2: Профиль пользователя (статистика + Меню)
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

from database import ensure_user, get_user_stats, get_user, save_registration
from handlers.flows.flow_helpers import send_screen, clear_previous_screen, clear_article_context
from handlers.flows.messages.common import msg_profile
from handlers.keyboards import kb_start, kb_main_menu, kb_next, kb_back_next, kb_start_work
from services.prompt_store import get_template, get_banner

logger = logging.getLogger(__name__)

# Состояния: флоу приветствия 1а-1е + меню
_WELCOME_1A, _WELCOME_1B, _WELCOME_1C, _WELCOME_1D, _WELCOME_1E, _MAIN_MENU = range(6)


# ---------------------------------------------------------------------------
# Шаг 1. Приветствие
# ---------------------------------------------------------------------------


async def _show_profile(update, context, message_id=None):
    """Показывает профиль пользователя в формате «окошек»."""
    user = update.effective_user if hasattr(update, 'effective_user') else update.from_user
    stats = await get_user_stats(user.id)
    text = await msg_profile(user.id, user.full_name, stats)

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

    # Очищаем информацию о выбранном артикуле
    clear_article_context(context)

    # ФЛАГ: показывать ли флоу приветствия 1а-1е для повторных пользователей
    # Пока True (всегда показывать) — позже можно переключить на False
    SHOW_WELCOME_ALWAYS = True  # TODO: переключить на False когда готово

    user_obj = await get_user(user.id)
    is_first_time = not user_obj["is_registered"]

    # Если первый раз ИЛИ флаг всегда показывать — показать флоу 1а-1е
    if is_first_time or SHOW_WELCOME_ALWAYS:
        context.user_data["welcome_step"] = "1a"
        welcome_text = await get_template("msg_welcome_1a")
        banner_name = await get_banner("msg_welcome_1a")
        await send_screen(
            context.bot,
            chat_id=user.id,
            text=welcome_text,
            keyboard=kb_next(),
            banner_path=f"assets/{banner_name}",
        )
        return _WELCOME_1A
    else:
        # Повторный вход — прямо в профиль
        await _show_profile(update, context)
        return _MAIN_MENU


async def _show_welcome_step(update: Update, context: ContextTypes.DEFAULT_TYPE, step: str, message_id: int | None = None) -> int:
    """Показывает конкретный шаг приветствия (1а-1е)."""
    user = update.effective_user

    # Маппинг шагов
    step_map = {
        "1a": ("msg_welcome_1a", kb_next()),
        "1b": ("msg_welcome_1b", kb_back_next()),
        "1c": ("msg_welcome_1c", kb_back_next()),
        "1d": ("msg_welcome_1d", kb_back_next()),
        "1e": ("msg_welcome_1e", kb_start_work()),
    }

    template_key, keyboard = step_map.get(step, ("msg_welcome_1a", kb_next()))
    welcome_text = await get_template(template_key)
    banner_name = await get_banner(template_key)

    await send_screen(
        context.bot,
        chat_id=user.id,
        message_id=message_id,
        text=welcome_text,
        keyboard=keyboard,
        banner_path=f"assets/{banner_name}",
    )

    # Маппинг шагов → состояния
    state_map = {
        "1a": _WELCOME_1A,
        "1b": _WELCOME_1B,
        "1c": _WELCOME_1C,
        "1d": _WELCOME_1D,
        "1e": _WELCOME_1E,
    }

    context.user_data["welcome_step"] = step
    return state_map.get(step, _WELCOME_1A)


async def cb_welcome_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Навигация вперед по шагам приветствия."""
    query = update.callback_query
    await query.answer()

    current_step = context.user_data.get("welcome_step", "1a")
    next_map = {"1a": "1b", "1b": "1c", "1c": "1d", "1d": "1e"}
    next_step = next_map.get(current_step, "1a")

    return await _show_welcome_step(update, context, next_step, message_id=query.message.message_id)


async def cb_welcome_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Навигация назад по шагам приветствия."""
    query = update.callback_query
    await query.answer()

    current_step = context.user_data.get("welcome_step", "1a")
    prev_map = {"1b": "1a", "1c": "1b", "1d": "1c", "1e": "1d"}
    prev_step = prev_map.get(current_step, "1a")

    return await _show_welcome_step(update, context, prev_step, message_id=query.message.message_id)


async def cb_welcome_start_work(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка 'Начать работу' — переход в профиль и отметить пользователя как зарегистрированного."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    # Помечаем пользователя как зарегистрированного (завершил флоу приветствия)
    await save_registration(user.id)
    logger.info("REGISTERED | user=%s", user.id)

    await _show_profile(update, context, message_id=query.message.message_id)
    return _MAIN_MENU


async def cb_start_begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь нажал «Начать ➜» — показываем профиль (для старого флоу)."""
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

    # Очищаем информацию о выбранном артикуле
    clear_article_context(context)

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
            _WELCOME_1A: [
                CallbackQueryHandler(cb_welcome_next, pattern="^welcome_next$"),
            ],
            _WELCOME_1B: [
                CallbackQueryHandler(cb_welcome_back, pattern="^welcome_back$"),
                CallbackQueryHandler(cb_welcome_next, pattern="^welcome_next$"),
            ],
            _WELCOME_1C: [
                CallbackQueryHandler(cb_welcome_back, pattern="^welcome_back$"),
                CallbackQueryHandler(cb_welcome_next, pattern="^welcome_next$"),
            ],
            _WELCOME_1D: [
                CallbackQueryHandler(cb_welcome_back, pattern="^welcome_back$"),
                CallbackQueryHandler(cb_welcome_next, pattern="^welcome_next$"),
            ],
            _WELCOME_1E: [
                CallbackQueryHandler(cb_welcome_back, pattern="^welcome_back$"),
                CallbackQueryHandler(cb_welcome_start_work, pattern="^welcome_start_work$"),
            ],
            _MAIN_MENU: [
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
                # menu_my_refs, menu_gen_photo, menu_gen_video, menu_new_article обрабатываются в других flow
                CallbackQueryHandler(cb_menu_not_impl, pattern="^menu_(?!my_refs|gen_photo|gen_video|topup|new_article|pinterest)"),
            ],
        },
        fallbacks=[],
        allow_reentry=True,
        name="onboarding",
        persistent=False,
    )
