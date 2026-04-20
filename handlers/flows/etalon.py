"""
handlers/flows/etalon.py

Шаг 15: Список товаров пользователя (Мои эталоны).
Шаг 16: Просмотр эталона (фото артикула с навигацией).
Без ConversationHandler — чтобы другие кнопки меню работали из любого экрана.
"""

from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import CallbackQueryHandler, ContextTypes

from database import get_user_articles_with_refs, get_active_references, get_user_stats
from handlers.flows.flow_helpers import send_screen, safe_delete
from handlers.flows.messages.regen_reference import msg_ref_card
from handlers.keyboards import kb_my_refs_empty, kb_ref_card
from services.prompt_store import get_template

logger = logging.getLogger(__name__)

# Храним текущий индекс эталона для каждого пользователя
_ref_index: dict[int, int] = {}

_MY_REFS_EMPTY_TEXT_FALLBACK = (
    "📂 Мои эталоны (Шаг 15)\n\n"
    "У вас пока нет товаров с эталонами.\n\n"
    "Создайте первый эталон, чтобы создавать "
    "фото и видео для ваших товаров."
)

_MY_REFS_LIST_TEXT_FALLBACK = (
    "📂 Мои эталоны (Шаг 15)\n\n"
    "Ниже ваши артикулы с эталонами.\n"
    "Нажмите на артикул — откроется меню работы с эталонами."
)


async def cb_menu_my_refs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает список товаров пользователя с количеством эталонов."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    full_name = update.effective_user.full_name or "—"
    message_id = query.message.message_id

    articles = await get_user_articles_with_refs(user_id)

    if not articles:
        text = await get_template("msg_my_refs_empty", fallback=_MY_REFS_EMPTY_TEXT_FALLBACK)
        keyboard = kb_my_refs_empty()
    else:
        stats = await get_user_stats(user_id)
        list_template = await get_template("msg_my_refs_list", fallback=_MY_REFS_LIST_TEXT_FALLBACK)
        text = list_template.format(
            user_id=user_id,
            full_name=full_name,
            articles=stats.get("articles", 0),
            references=stats.get("references", 0),
            photos=stats.get("photos", 0),
            videos=stats.get("videos", 0),
            balance=stats.get("balance", 0),
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

        buttons.append([InlineKeyboardButton("🌐 Перейти на сайт", url="https://media.zaliv.ai/")])
        buttons.append([InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")])
        keyboard = InlineKeyboardMarkup(buttons)

    await send_screen(
        context.bot,
        chat_id=user_id,
        message_id=message_id,
        text=text,
        keyboard=keyboard,
    )


async def show_ref_card(user, article: str, ref_index: int, bot, query) -> None:
    """Показывает фото эталона по индексу (переиспользуемая функция)."""
    user_id = user.id
    refs = await get_active_references(user_id, article)

    if not refs:
        await query.edit_message_text("❌ Эталоны для этого артикула не найдены.")
        return

    idx = ref_index
    if idx >= len(refs):
        idx = 0

    ref = refs[idx]
    total = len(refs)
    caption = await msg_ref_card(ref["reference_number"], total, article, ref["category"] or "—")
    keyboard = kb_ref_card(article, idx, total)

    try:
        await bot.edit_message_media(
            chat_id=user_id,
            message_id=query.message.message_id,
            media=InputMediaPhoto(media=ref["file_id"], caption=caption, parse_mode="HTML"),
            reply_markup=keyboard,
        )
    except Exception:
        try:
            await bot.send_photo(
                chat_id=user_id,
                photo=ref["file_id"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception:
            pass


async def cb_ref_article(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает фото эталона для выбранного артикула (Шаг 16)."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    message_id = query.message.message_id
    data = query.data  # ref_article_{code}
    article = data.replace("ref_article_", "")

    # Сбрасываем индекс при первом открытии артикула
    last_ref = context.user_data.get("_last_ref_data")
    if data != last_ref:
        _ref_index[user_id] = 0
    context.user_data["_last_ref_data"] = data

    refs = await get_active_references(user_id, article)

    if not refs:
        await query.edit_message_text("❌ Эталоны для этого артикула не найдены.")
        return

    idx = _ref_index.get(user_id, 0)
    if idx >= len(refs):
        idx = 0
    _ref_index[user_id] = idx

    ref = refs[idx]
    total = len(refs)

    # Запоминаем для flow создания фото/видео и пересоздания
    context.user_data["article_code"] = article
    context.user_data["ref_number_for_gen"] = ref["reference_number"]

    caption = await msg_ref_card(ref["reference_number"], total, article, ref["category"] or "—")
    keyboard = kb_ref_card(article, idx, total)

    try:
        await context.bot.edit_message_media(
            chat_id=user_id,
            message_id=message_id,
            media=InputMediaPhoto(media=ref["file_id"], caption=caption, parse_mode="HTML"),
            reply_markup=keyboard,
        )
    except Exception:
        await context.bot.send_photo(
            chat_id=user_id,
            photo=ref["file_id"],
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )


async def cb_ref_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Навигация между эталонами (← Пред. / След. →)."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    message_id = query.message.message_id
    data = query.data  # ref_prev_{code} / ref_next_{code}

    parts = data.split("_", 2)  # ref, prev/next, code
    if len(parts) < 3:
        return
    direction = parts[1]
    article = parts[2]

    refs = await get_active_references(user_id, article)
    if not refs:
        return

    idx = _ref_index.get(user_id, 0)
    if direction == "prev":
        idx = max(0, idx - 1)
    elif direction == "next":
        idx = min(len(refs) - 1, idx + 1)

    _ref_index[user_id] = idx

    # Перерисовываем экран напрямую, без вызова cb_ref_article
    ref = refs[idx]
    total = len(refs)

    # Запоминаем для flow создания фото/видео и пересоздания
    context.user_data["article_code"] = article
    context.user_data["ref_number_for_gen"] = ref["reference_number"]

    caption = await msg_ref_card(ref["reference_number"], total, article, ref["category"] or "—")
    keyboard = kb_ref_card(article, idx, total)

    try:
        await context.bot.edit_message_media(
            chat_id=user_id,
            message_id=message_id,
            media=InputMediaPhoto(media=ref["file_id"], caption=caption, parse_mode="HTML"),
            reply_markup=keyboard,
        )
    except Exception:
        try:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=ref["file_id"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception:
            pass


def build_etalon_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(cb_menu_my_refs, pattern="^menu_my_refs$")


async def cb_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик noop-кнопок — только подтверждение клика."""
    await update.callback_query.answer()


def build_noop_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(cb_noop, pattern="^noop$")


def build_ref_article_handler() -> CallbackQueryHandler:
    """Обработчик просмотра эталона (Шаг 16)."""
    return CallbackQueryHandler(cb_ref_article, pattern="^ref_article_")


def build_ref_nav_handler() -> CallbackQueryHandler:
    """Обработчик навигации ← Пред. / След. →"""
    return CallbackQueryHandler(cb_ref_nav, pattern="^(ref_prev_|ref_next_)")
