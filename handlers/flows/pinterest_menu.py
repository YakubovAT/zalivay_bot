"""
handlers/flows/pinterest_menu.py

Flow кнопки «📌 Пинтерест» в главном меню (Шаг 2).

Шаги:
  П1. Обзор — статистика, файлы с нанесённым артикулом
  П2. Выбор количества строк CSV (inline-кнопками)
  П3. Подтверждение и генерация
"""

from __future__ import annotations

import io
import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
)

from config import PINTEREST_CSV_COST
from database import get_user_stats, get_all_unexported_media_files, get_watermarked_articles_stats, deduct_balance
from handlers.flows.flow_helpers import send_screen
from handlers.flows.messages.pinterest_menu import (
    msg_pinterest_menu_overview,
    msg_pinterest_menu_count,
    msg_pinterest_menu_confirm,
    msg_pinterest_menu_insufficient,
    msg_pinterest_menu_no_files,
    msg_pinterest_menu_generating,
    msg_pinterest_menu_done,
    msg_pinterest_menu_distribution,
    msg_pinterest_menu_article_select,
)
from handlers.keyboards import (
    kb_pinterest_menu_overview,
    kb_pinterest_menu_count,
    kb_pinterest_menu_confirm,
    kb_pinterest_menu_distribution,
    kb_pinterest_menu_articles,
)
from services.pinterest_csv_generator import generate_pinterest_csv

logger = logging.getLogger(__name__)

_P1_OVERVIEW, _P2_COUNT, _P2_DISTRIBUTION, _P2_ARTICLE, _P3_CONFIRM = range(5)

_CTX_COUNT        = "pmenu_count"
_CTX_COST         = "pmenu_cost"
_CTX_AVAILABLE    = "pmenu_available"
_CTX_DISTRIBUTION = "pmenu_distribution"
_CTX_ARTICLE      = "pmenu_priority_article"


# ---------------------------------------------------------------------------
# Вспомогательные
# ---------------------------------------------------------------------------

async def _watermarked_counts(user_id: int) -> tuple[int, int]:
    """Возвращает (фото, видео) с нанесённым артикулом."""
    files = await get_all_unexported_media_files(user_id)
    photos = sum(1 for f in files if f["file_type"] == "photo")
    videos = sum(1 for f in files if f["file_type"] == "video")
    return photos, videos


# ---------------------------------------------------------------------------
# Шаг П1: Обзор
# ---------------------------------------------------------------------------

async def _show_overview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    stats = await get_user_stats(user_id)
    wm_photos, wm_videos = await _watermarked_counts(user_id)

    text = await msg_pinterest_menu_overview(
        photos_count=stats["photos"],
        videos_count=stats["videos"],
        watermarked_photos=wm_photos,
        watermarked_videos=wm_videos,
    )
    await send_screen(
        context.bot,
        chat_id=user_id,
        message_id=query.message.message_id,
        text=text,
        keyboard=kb_pinterest_menu_overview(),
    )
    return _P1_OVERVIEW


# ---------------------------------------------------------------------------
# Шаг П2: Выбор количества строк
# ---------------------------------------------------------------------------

async def _show_count_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    stats = await get_user_stats(user_id)
    wm_photos, wm_videos = await _watermarked_counts(user_id)
    available = wm_photos + wm_videos

    if available == 0:
        text = await msg_pinterest_menu_no_files()
        await send_screen(
            context.bot,
            chat_id=user_id,
            message_id=query.message.message_id,
            text=text,
            keyboard=kb_pinterest_menu_overview(),
        )
        return _P1_OVERVIEW

    context.user_data[_CTX_AVAILABLE] = available

    text = await msg_pinterest_menu_count(
        watermarked_photos=wm_photos,
        watermarked_videos=wm_videos,
        balance=stats["balance"],
        cost_per_row=PINTEREST_CSV_COST,
    )
    await send_screen(
        context.bot,
        chat_id=user_id,
        message_id=query.message.message_id,
        text=text,
        keyboard=kb_pinterest_menu_count(available),
    )
    return _P2_COUNT


# ---------------------------------------------------------------------------
# Шаг П3: Подтверждение
# ---------------------------------------------------------------------------

async def _on_count_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    requested = int(query.data.split("_")[-1])
    available = context.user_data.get(_CTX_AVAILABLE, 0)
    count = min(requested, available, 100)
    cost  = count * PINTEREST_CSV_COST

    user_id = update.effective_user.id
    stats   = await get_user_stats(user_id)
    balance = stats["balance"]

    # Не хватает баланса — предлагаем посильное количество
    if balance < cost:
        affordable = balance // PINTEREST_CSV_COST
        if affordable < 10:
            text = await msg_pinterest_menu_insufficient(cost=cost, balance=balance)
            await send_screen(
                context.bot,
                chat_id=user_id,
                message_id=query.message.message_id,
                text=text,
                keyboard=kb_pinterest_menu_overview(),
            )
            _clear(context)
            return _P1_OVERVIEW
        count = affordable
        cost  = affordable * PINTEREST_CSV_COST

    context.user_data[_CTX_COUNT] = count
    context.user_data[_CTX_COST]  = cost

    articles = await get_watermarked_articles_stats(user_id)
    text = await msg_pinterest_menu_distribution(
        count=count,
        articles_count=len(articles),
    )
    await send_screen(
        context.bot,
        chat_id=user_id,
        message_id=query.message.message_id,
        text=text,
        keyboard=kb_pinterest_menu_distribution(),
    )
    return _P2_DISTRIBUTION


# ---------------------------------------------------------------------------
# Шаг П2.5: Выбор распределения
# ---------------------------------------------------------------------------

async def _on_distribution_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    mode = query.data.split("_")[-1]  # "random" | "equal" | "priority"
    user_id = update.effective_user.id

    if mode == "priority":
        articles = await get_watermarked_articles_stats(user_id)
        articles_list = "\n".join(
            f"• {a['name']} — {a['photo_count'] + a['video_count']} фото"
            for a in articles
        )
        text = await msg_pinterest_menu_article_select(articles_list=articles_list)
        await send_screen(
            context.bot,
            chat_id=user_id,
            message_id=query.message.message_id,
            text=text,
            keyboard=kb_pinterest_menu_articles(articles),
        )
        return _P2_ARTICLE

    context.user_data[_CTX_DISTRIBUTION] = mode
    context.user_data[_CTX_ARTICLE] = None
    return await _show_confirm(update, context)


# ---------------------------------------------------------------------------
# Шаг П2.6: Выбор приоритетного артикула
# ---------------------------------------------------------------------------

async def _on_article_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    article_code = query.data[len("pmenu_article_"):]
    context.user_data[_CTX_DISTRIBUTION] = "priority"
    context.user_data[_CTX_ARTICLE] = article_code
    return await _show_confirm(update, context)


async def _show_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    count   = context.user_data.get(_CTX_COUNT, 0)
    cost    = context.user_data.get(_CTX_COST, 0)
    stats   = await get_user_stats(user_id)
    balance = stats["balance"]

    text = await msg_pinterest_menu_confirm(
        count=count,
        cost=cost,
        balance=balance,
        after=balance - cost,
    )
    await send_screen(
        context.bot,
        chat_id=user_id,
        message_id=query.message.message_id,
        text=text,
        keyboard=kb_pinterest_menu_confirm(),
    )
    return _P3_CONFIRM


# ---------------------------------------------------------------------------
# Генерация CSV
# ---------------------------------------------------------------------------

async def _do_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    count   = context.user_data.get(_CTX_COUNT, 0)

    status_text = await msg_pinterest_menu_generating(count)
    await send_screen(
        context.bot,
        chat_id=user_id,
        message_id=query.message.message_id,
        text=status_text,
        keyboard=None,
    )

    distribution_mode = context.user_data.get(_CTX_DISTRIBUTION, "random")
    priority_article  = context.user_data.get(_CTX_ARTICLE)
    result = await generate_pinterest_csv(
        user_id,
        count,
        distribution_mode=distribution_mode,
        priority_article_code=priority_article,
    )
    generated = result["stats"]["count"]

    if generated == 0:
        _clear(context)
        return await _show_overview(update, context)

    actual_cost = generated * PINTEREST_CSV_COST
    new_balance = await deduct_balance(user_id, actual_cost)
    logger.info(
        "PINTEREST_MENU | user=%d | rows=%d | cost=%d | balance=%d",
        user_id, generated, actual_cost, new_balance,
    )

    caption   = await msg_pinterest_menu_done(generated, actual_cost, new_balance)
    csv_bytes = result["content"].encode("utf-8")
    filename  = f"pinterest_{result['batch_id']}.csv"

    await context.bot.send_document(
        chat_id=user_id,
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption=caption,
    )

    _clear(context)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Навигация
# ---------------------------------------------------------------------------

async def _back_to_overview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _show_overview(update, context)


async def _back_to_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _show_count_select(update, context)


async def _back_to_distribution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    count   = context.user_data.get(_CTX_COUNT, 0)
    articles = await get_watermarked_articles_stats(user_id)
    text = await msg_pinterest_menu_distribution(count=count, articles_count=len(articles))
    await send_screen(
        context.bot,
        chat_id=user_id,
        message_id=query.message.message_id,
        text=text,
        keyboard=kb_pinterest_menu_distribution(),
    )
    return _P2_DISTRIBUTION


async def cb_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear(context)
    from handlers.flows.onboarding import cb_back_to_menu as _menu
    return await _menu(update, context)


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (_CTX_COUNT, _CTX_COST, _CTX_AVAILABLE, _CTX_DISTRIBUTION, _CTX_ARTICLE):
        context.user_data.pop(key, None)


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_pinterest_menu_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(_show_overview, pattern="^menu_pinterest$"),
        ],
        states={
            _P1_OVERVIEW: [
                CallbackQueryHandler(_show_count_select, pattern="^pmenu_csv$"),
                CallbackQueryHandler(cb_back_to_menu,    pattern="^back_to_menu$"),
            ],
            _P2_COUNT: [
                CallbackQueryHandler(_on_count_selected, pattern=r"^pmenu_count_\d+$"),
                CallbackQueryHandler(_back_to_overview,  pattern="^pmenu_back_overview$"),
                CallbackQueryHandler(cb_back_to_menu,    pattern="^back_to_menu$"),
            ],
            _P2_DISTRIBUTION: [
                CallbackQueryHandler(_on_distribution_selected, pattern=r"^pmenu_dist_(random|equal|priority)$"),
                CallbackQueryHandler(_back_to_count,             pattern="^pmenu_back_count$"),
                CallbackQueryHandler(cb_back_to_menu,            pattern="^back_to_menu$"),
            ],
            _P2_ARTICLE: [
                CallbackQueryHandler(_on_article_selected,  pattern=r"^pmenu_article_.+$"),
                CallbackQueryHandler(_back_to_distribution, pattern="^pmenu_back_dist$"),
                CallbackQueryHandler(cb_back_to_menu,       pattern="^back_to_menu$"),
            ],
            _P3_CONFIRM: [
                CallbackQueryHandler(_do_generate,          pattern="^pmenu_confirm$"),
                CallbackQueryHandler(_back_to_distribution, pattern="^pmenu_back_dist$"),
                CallbackQueryHandler(cb_back_to_menu,       pattern="^back_to_menu$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
        ],
        name="pinterest_menu_flow",
        persistent=False,
    )
