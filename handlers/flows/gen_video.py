"""
handlers/flows/gen_video.py

Flow создания видео на основе эталона.

Шаги (по образу gen_photo.py):
  V1. Сколько видео? (текстовый ввод или быстрые кнопки 1/2/3)
  V2. Пожелания (текст или «Нет пожеланий»)
  V3. Проверка баланса и подтверждение
  V4. Создание (I2V) — поставлено в очередь
"""

from __future__ import annotations

import asyncio
import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import VIDEO_COST
from database import (
    get_user_stats,
    get_reference,
    get_active_references,
    create_generation_job,
    create_video_job_task,
)
from handlers.flows.flow_helpers import safe_delete
from handlers.flows.messages.common import msg_insufficient_funds, kb_alert_close
from handlers.keyboards import (
    kb_gen_video_count,
    kb_gen_video_wish,
    kb_gen_video_confirm,
    kb_gen_video_result,
)
from services.prompt_store import get_template
from services.prompt_generator_video import generate_video_prompts

logger = logging.getLogger(__name__)

# Состояния
_V_COUNT, _V_WISH, _V_CONFIRM, _V_GENERATING = range(4)

# Максимальное количество видео за один запрос
_MAX_VIDEOS = 5


# ---------------------------------------------------------------------------
# Entry point — нажали «🎥 Создать видео»
# ---------------------------------------------------------------------------

async def cb_menu_gen_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вход в flow создания видео."""
    query = update.callback_query
    await query.answer()

    article = context.user_data.get("article_code")
    ref_number = context.user_data.get("ref_number_for_gen")

    if not article or ref_number is None:
        # Пришли из главного меню — перенаправляем на «Мои эталоны»
        from handlers.flows.etalon import cb_menu_my_refs
        await cb_menu_my_refs(update, context)
        return ConversationHandler.END

    ref = await get_reference(update.effective_user.id, article, ref_number)
    if not ref:
        await query.edit_message_text("❌ Эталон не найден.")
        return ConversationHandler.END

    # Проверяем наличие product_description
    if not ref.get("product_description"):
        await query.answer(
            "❌ Этот эталон создан до обновления системы и не поддерживает создание видео. "
            "Пересоздайте эталон.",
            show_alert=True,
        )
        return ConversationHandler.END

    refs = await get_active_references(update.effective_user.id, article)
    ref_index = 0
    if refs:
        for i, r in enumerate(refs):
            if r["reference_number"] == ref_number:
                ref_index = i
                break

    context.user_data["gen_video_article"] = article
    context.user_data["gen_video_ref_number"] = ref_number
    context.user_data["gen_video_ref_index"] = ref_index
    context.user_data["gen_video_ref"] = dict(ref)
    context.user_data["_screen_msg"] = query.message.message_id

    text = await _msg_gen_video_count(article, ref_number, ref.get("category", "—"))

    await context.bot.edit_message_caption(
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        caption=text,
        parse_mode="HTML",
        reply_markup=kb_gen_video_count(),
    )
    return _V_COUNT


# ---------------------------------------------------------------------------
# V1. Сколько видео? — текстовый ввод
# ---------------------------------------------------------------------------

async def msg_video_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл количество видео текстом."""
    user = update.effective_user
    text = update.message.text.strip()

    asyncio.get_event_loop().call_later(
        0, lambda: asyncio.create_task(safe_delete(context.bot, user.id, update.message.message_id))
    )

    screen_msg = context.user_data.get("_screen_msg")

    try:
        count = int(text)
        if count < 1 or count > _MAX_VIDEOS:
            if screen_msg:
                await context.bot.edit_message_caption(
                    chat_id=user.id,
                    message_id=screen_msg,
                    caption=f"Введите число от 1 до {_MAX_VIDEOS}:",
                )
            return _V_COUNT
    except ValueError:
        if screen_msg:
            await context.bot.edit_message_caption(
                chat_id=user.id,
                message_id=screen_msg,
                caption=f"Пожалуйста, введите число (от 1 до {_MAX_VIDEOS}):",
            )
        return _V_COUNT

    context.user_data["gen_video_count"] = count
    return await _show_wish_screen(update.effective_user, context)


async def cb_quick_video_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Быстрый выбор количества видео кнопками 1/2/3."""
    query = update.callback_query
    await query.answer()

    count = int(query.data.replace("gen_video_count_", ""))
    context.user_data["gen_video_count"] = count
    return await _show_wish_screen(update.effective_user, context)


async def _show_wish_screen(user, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает экран V2 — пожелания."""
    screen_msg = context.user_data.get("_screen_msg")
    article = context.user_data["gen_video_article"]
    ref_number = context.user_data["gen_video_ref_number"]
    count = context.user_data["gen_video_count"]
    total_cost = count * VIDEO_COST

    text = await _msg_gen_video_wish(article, ref_number, count, total_cost)

    if screen_msg:
        await context.bot.edit_message_caption(
            chat_id=user.id,
            message_id=screen_msg,
            caption=text,
            parse_mode="HTML",
            reply_markup=kb_gen_video_wish(),
        )
    return _V_WISH


# ---------------------------------------------------------------------------
# V2. Пожелания
# ---------------------------------------------------------------------------

async def msg_video_wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл пожелания."""
    user = update.effective_user
    text = update.message.text.strip()

    asyncio.get_event_loop().call_later(
        0, lambda: asyncio.create_task(safe_delete(context.bot, user.id, update.message.message_id))
    )

    wish = None if text.lower() in ("пропустить", "пропуск", "skip", "нет") else text
    context.user_data["gen_video_wish"] = wish
    try:
        await _show_confirm_screen(user, context)
    except Exception:
        logger.exception("msg_video_wish: _show_confirm_screen failed")
    return _V_CONFIRM


async def cb_no_video_wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь нажал «Нет пожеланий»."""
    query = update.callback_query
    await query.answer()
    context.user_data["gen_video_wish"] = None
    try:
        await _show_confirm_screen(update.effective_user, context)
    except Exception:
        logger.exception("cb_no_video_wish: _show_confirm_screen failed")
    return _V_CONFIRM


async def _show_confirm_screen(user, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает экран V3 — подтверждение. Проверяет баланс."""
    article = context.user_data["gen_video_article"]
    ref_number = context.user_data["gen_video_ref_number"]
    count = context.user_data["gen_video_count"]
    wish = context.user_data.get("gen_video_wish")
    total_cost = count * VIDEO_COST
    screen_msg = context.user_data.get("_screen_msg")

    stats = await get_user_stats(user.id)
    balance = stats["balance"]

    if balance < total_cost:
        await context.bot.send_photo(
            chat_id=user.id,
            photo=open("assets/banner_default.png", "rb"),
            caption=await msg_insufficient_funds(needed=total_cost, balance=balance),
            parse_mode="HTML",
            reply_markup=kb_alert_close(),
        )
        return _V_WISH

    caption = await _msg_gen_video_confirm(article, count, total_cost, balance, wish)

    if screen_msg:
        from telegram.error import BadRequest as TgBadRequest
        try:
            await context.bot.edit_message_caption(
                chat_id=user.id,
                message_id=screen_msg,
                caption=caption,
                parse_mode="HTML",
                reply_markup=kb_gen_video_confirm(),
            )
        except TgBadRequest:
            sent = await context.bot.send_photo(
                chat_id=user.id,
                photo=open("assets/banner_default.png", "rb"),
                caption=caption,
                parse_mode="HTML",
                reply_markup=kb_gen_video_confirm(),
            )
            context.user_data["_screen_msg"] = sent.message_id
    return _V_CONFIRM


# ---------------------------------------------------------------------------
# V3. Подтверждение — создаём job + tasks
# ---------------------------------------------------------------------------

async def cb_gen_video_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь подтвердил создание видео."""
    query = update.callback_query
    await query.answer()

    user_id    = update.effective_user.id
    article    = context.user_data["gen_video_article"]
    ref_number = context.user_data["gen_video_ref_number"]
    ref        = context.user_data["gen_video_ref"]
    count      = context.user_data["gen_video_count"]
    wish       = context.user_data.get("gen_video_wish")
    screen_msg = context.user_data.get("_screen_msg")
    total_cost = count * VIDEO_COST

    logger.info("GEN_VIDEO_START | user=%s article=%s ref=%d count=%d", user_id, article, ref_number, count)

    # Формируем URL эталона
    ref_image_url = ref.get("reference_image_url", "")
    if not ref_image_url:
        file_path = ref.get("file_path", "")
        if file_path:
            abs_path = os.path.realpath(file_path)
            media_idx = abs_path.find("/media/")
            if media_idx >= 0:
                rel = abs_path[media_idx + len("/media/"):]
                ref_image_url = f"https://zaliv.ai/media/{rel}"
            else:
                rel = file_path.lstrip("/").replace("media/", "", 1)
                ref_image_url = f"https://zaliv.ai/media/{user_id}/{rel}"

    if not ref_image_url:
        await query.edit_message_caption(
            caption="❌ Эталон не содержит изображения. Создайте эталон заново.",
        )
        return ConversationHandler.END

    # Создаем промпты
    description = ref["product_description"]
    base_prompts = await generate_video_prompts(
        description=description,
        category=ref.get("category"),
        count=count,
    )
    prompts = [
        ", ".join(filter(None, [base, wish]))
        for base in base_prompts
    ]

    # Создаём job в БД
    job_id = await create_generation_job(
        user_id=user_id,
        chat_id=user_id,
        article=article,
        ref_number=ref_number,
        ref_image_url=ref_image_url,
        wish=wish,
        count=count,
        cost=total_cost,
        screen_msg_id=screen_msg,
    )

    # Создаём N задач типа lifestyle_video
    for prompt in prompts:
        await create_video_job_task(
            job_id=job_id,
            user_id=user_id,
            chat_id=user_id,
            article=article,
            prompt=prompt,
        )

    logger.info("GEN_VIDEO | job_id=%d | created %d tasks", job_id, count)

    generating_caption = await _msg_gen_video_generating(article, count)
    await context.bot.edit_message_caption(
        chat_id=user_id,
        message_id=screen_msg,
        caption=generating_caption,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")],
        ]),
    )

    return _V_GENERATING


# ---------------------------------------------------------------------------
# Навигация
# ---------------------------------------------------------------------------

async def cb_back_to_ref_card_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к карточке эталона."""
    from handlers.flows.etalon import show_ref_card
    user_id = update.effective_user.id
    article = context.user_data.get("gen_video_article")
    ref_number = context.user_data.get("gen_video_ref_number")
    ref_index = context.user_data.get("gen_video_ref_index", 0)
    if article and ref_number:
        context.user_data["article_code"] = article
        context.user_data["ref_number_for_gen"] = ref_number
        return await show_ref_card(update.effective_user, article, ref_index, context.bot, update.callback_query)
    from handlers.flows.onboarding import cb_back_to_menu
    return await cb_back_to_menu(update, context)


async def cb_back_to_v_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к вводу количества видео."""
    query = update.callback_query
    await query.answer()

    article = context.user_data.get("gen_video_article", "")
    ref_number = context.user_data.get("gen_video_ref_number", "")
    ref = context.user_data.get("gen_video_ref", {})

    text = await _msg_gen_video_count(article, ref_number, ref.get("category", "—"))

    await context.bot.edit_message_caption(
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        caption=text,
        parse_mode="HTML",
        reply_markup=kb_gen_video_count(),
    )
    return _V_COUNT


async def cb_back_to_v_wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к пожеланиям."""
    query = update.callback_query
    await query.answer()
    return await _show_wish_screen(update.effective_user, context)


async def cb_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад в главное меню."""
    from handlers.flows.onboarding import cb_back_to_menu
    return await cb_back_to_menu(update, context)


async def cb_close_alert_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Закрыть алерт-сообщение."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    return _V_WISH


async def _msg_gen_video_count(article: str, ref_number: int | str, category: str) -> str:
    template = await get_template("msg_gen_video_count")
    return template.format(
        article=article,
        ref_number=ref_number,
        category=category or "—",
        video_cost=VIDEO_COST,
    )


async def _msg_gen_video_wish(article: str, ref_number: int | str, count: int, total_cost: int) -> str:
    template = await get_template("msg_gen_video_wish")
    return template.format(
        article=article,
        ref_number=ref_number,
        count=count,
        total_cost=total_cost,
    )


async def _msg_gen_video_confirm(article: str, count: int, total_cost: int, balance: int, wish: str | None) -> str:
    template = await get_template("msg_gen_video_confirm")
    wish_block = f'📝 Пожелания: "{wish}"\n\n' if wish else ""
    return template.format(
        article=article,
        count=count,
        wish_block=wish_block,
        total_cost=total_cost,
        balance=balance,
    )


async def _msg_gen_video_generating(article: str, count: int) -> str:
    template = await get_template("msg_gen_video_generating")
    return template.format(article=article, count=count)


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_gen_video_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_menu_gen_video, pattern="^menu_gen_video$"),
        ],
        states={
            _V_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_video_count),
                CallbackQueryHandler(cb_quick_video_count, pattern=r"^gen_video_count_\d+$"),
                CallbackQueryHandler(cb_back_to_ref_card_video, pattern="^back_to_ref_card$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cb_close_alert_video, pattern="^alert_close$"),
            ],
            _V_WISH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_video_wish),
                CallbackQueryHandler(cb_no_video_wish, pattern="^gen_video_no_wish$"),
                CallbackQueryHandler(cb_back_to_v_count, pattern="^back_to_v_count$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cb_close_alert_video, pattern="^alert_close$"),
            ],
            _V_CONFIRM: [
                CallbackQueryHandler(cb_gen_video_yes, pattern="^gen_video_yes$"),
                CallbackQueryHandler(cb_back_to_v_wish, pattern="^back_to_v_wish$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
            _V_GENERATING: [
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cb_menu_gen_video, pattern="^menu_gen_video$"),
        ],
        name="gen_video",
        persistent=False,
        allow_reentry=True,
    )
