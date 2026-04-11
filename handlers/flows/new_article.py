"""
handlers/flows/new_article.py

Шаг 3: Выбор маркетплейса
Шаг 4: Ввод артикула
"""

from __future__ import annotations

import logging
import re

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import ensure_user, get_user_stats
from handlers.flows.flow_helpers import send_screen, store_msg_id
from handlers.keyboards import kb_marketplace, kb_enter_article, kb_main_menu

logger = logging.getLogger(__name__)

# Состояния
_MP_SELECT, _ARTICLE_INPUT = range(2)

# Валидация артикула WB: только цифры, 6-9 знаков
ARTICLE_RE = re.compile(r"^\d{6,9}$")


# ---------------------------------------------------------------------------
# Шаг 3. Выбор маркетплейса
# ---------------------------------------------------------------------------

_MARKETPLACE_TEXT = (
    "Выберите маркетплейс, где продается ваш товар. "
    "Далее вы введёте артикул, а мы создадим эталон — "
    "чистое изображение товара на прозрачном фоне. "
    "На его основе будут генерироваться фото и видео для соцсетей."
)

_LOCKED_TEXT = "⏳ Этот маркетплейс скоро будет доступен"


async def cb_menu_new_article(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь нажал «➕ Новый артикул» в главном меню."""
    query = update.callback_query
    await query.answer()

    await send_screen(
        context.bot,
        chat_id=query.from_user.id,
        message_id=query.message.message_id,
        text=_MARKETPLACE_TEXT,
        keyboard=kb_marketplace(),
    )
    store_msg_id(query.from_user.id, query.message.message_id)
    return _MP_SELECT


async def cb_mp_wb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь выбрал Wildberries."""
    query = update.callback_query
    await query.answer()

    await send_screen(
        context.bot,
        chat_id=query.from_user.id,
        message_id=query.message.message_id,
        text="Введите артикул товара Wildberries:",
        keyboard=kb_enter_article(),
    )
    return _ARTICLE_INPUT


async def cb_mp_locked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь выбрал ещё не доступный маркетплейс."""
    query = update.callback_query
    await query.answer(_LOCKED_TEXT, show_alert=True)
    return _MP_SELECT


async def cb_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка «← Назад» — возврат в главное меню."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
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
        message_id=query.message.message_id,
        text=text,
        keyboard=kb_main_menu(),
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Шаг 4. Ввод артикула
# ---------------------------------------------------------------------------

async def msg_article_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл артикул — валидируем и переходим к парсингу."""
    user = update.effective_user
    text = update.message.text.strip()

    logger.info("ARTICLE_INPUT | user=%s text=%r", user.id, text)

    # Валидация: только цифры, 6-9 знаков
    if not ARTICLE_RE.match(text):
        await update.message.reply_text(
            "❌ Артикул должен содержать от 6 до 9 цифр.\n"
            "Попробуйте снова:"
        )
        return _ARTICLE_INPUT

    # Сохраняем артикул в контекст для следующего шага (парсинг)
    context.user_data["article_code"] = text
    logger.info("ARTICLE_VALIDATED | user=%s article=%s", user.id, text)

    # TODO: Шаг 5 — парсинг WB (будет реализован следующим)
    await update.message.reply_text(
        f"✅ Артикул {text} принят.\n"
        "Следующий шаг: парсинг товара с Wildberries."
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_new_article_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_menu_new_article, pattern="^menu_new_article$"),
        ],
        states={
            _MP_SELECT: [
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cb_mp_wb, pattern="^mp_wb$"),
                CallbackQueryHandler(cb_mp_locked, pattern="^mp_"),
            ],
            _ARTICLE_INPUT: [
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_article_input),
            ],
        },
        fallbacks=[],
        allow_reentry=True,
        name="new_article",
        persistent=False,
    )
