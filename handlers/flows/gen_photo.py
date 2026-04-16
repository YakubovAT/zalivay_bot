"""
handlers/flows/gen_photo.py

Flow генерации фото на основе эталона.

Шаги по SCENARIO.md:
  P1. Сколько фото? (текстовый ввод)
  P2. Пожелания (текст или «Пропустить»)
  P3. Проверка баланса и подтверждение
  P4. Генерация (I2I)
  P5. Результат (альбом)
"""

from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import PHOTO_COST
from database import (
    get_user_stats,
    get_reference,
    get_active_references,
    create_generation_job,
    create_job_task,
)
from handlers.flows.flow_helpers import safe_delete
from handlers.flows.messages.common import msg_insufficient_funds, kb_alert_close
from handlers.keyboards import (
    kb_gen_photo_count,
    kb_gen_photo_wish,
    kb_gen_photo_confirm,
    kb_gen_photo_result,
)
from services.prompt_store import get_template
from services.prompt_generator_cloth import generate_photo_prompts

logger = logging.getLogger(__name__)

# Состояния
_P_COUNT, _P_WISH, _P_CONFIRM, _P_GENERATING = range(4)

_GEN_PHOTO_COUNT_TEXT_FALLBACK = (
    "📸 Шаг P1: Сколько фото?\n\n"
    "Сколько фото сгенерировать на основе этого эталона?\n\n"
    "Вы можете сгенерировать одно или множество изображений.\n"
    "Каждое фото будет уникальным — разная локация, освещение, ракурс.\n\n"
    "📦 Артикул: <code>{article}</code>\n"
    "📸 Эталон: #{ref_number}\n"
    "🏷 Тип товара: {category}\n\n"
    "💰 Стоимость: {photo_cost}₽ за фото\n\n"
    "Введите число:"
)

_GEN_PHOTO_WISH_TEXT_FALLBACK = (
    "📸 Шаг P2: Пожелания\n\n"
    "📦 Артикул: <code>{article}</code>\n"
    "📸 Эталон: #{ref_number}\n\n"
    "Будет сгенерировано: {count} фото\n"
    "💰 Стоимость: {total_cost}₽\n\n"
    "Есть пожелания к генерации?\n\n"
    "Например: «хочу фото на фоне моря», «сделай в студии»."
)

_GEN_PHOTO_CONFIRM_TEXT_FALLBACK = (
    "📸 Шаг P3: Подтверждение\n\n"
    "Готов генерировать {count} фото на основе изображения представленного выше.\n\n"
    "📦 Артикул: <code>{article}</code>\n"
    "{wish_block}"
    "💰 Стоимость: {total_cost}₽\n"
    "💳 Ваш баланс: {balance}₽\n\n"
    "Если всё устраивает, нажмите ✅ Сгенерировать и процесс запустится."
)

_GEN_PHOTO_GENERATING_TEXT_FALLBACK = (
    "📸 Шаг P4: Генерация\n\n"
    "⏳ Поставил в очередь {count} фото для артикула <code>{article}</code>.\n\n"
    "Фото генерируются параллельно.\n"
    "Я пришлю результат когда все будут готовы."
)


# ---------------------------------------------------------------------------
# Entry point — нажали «📸 Генерировать фото»
# ---------------------------------------------------------------------------

async def cb_menu_gen_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вход в flow генерации фото."""
    query = update.callback_query
    await query.answer()

    # Проверяем, пришли ли из карточки эталона (эталон уже выбран)
    article = context.user_data.get("article_code")
    ref_number = context.user_data.get("ref_number_for_gen")

    if not article or ref_number is None:
        # Пришли из главного меню — перенаправляем на «Мои эталоны»
        from handlers.flows.etalon import cb_menu_my_refs
        await cb_menu_my_refs(update, context)
        return ConversationHandler.END

    # Эталон известен — показываем экран P1
    ref = await get_reference(update.effective_user.id, article, ref_number)
    if not ref:
        await query.edit_message_text("❌ Эталон не найден.")
        return ConversationHandler.END

    # Считаем индекс эталона для навигации
    refs = await get_active_references(update.effective_user.id, article)
    ref_index = 0
    if refs:
        for i, r in enumerate(refs):
            if r["reference_number"] == ref_number:
                ref_index = i
                break

    context.user_data["gen_article"] = article
    context.user_data["gen_ref_number"] = ref_number
    context.user_data["gen_ref_index"] = ref_index
    context.user_data["gen_ref"] = dict(ref)
    context.user_data["_screen_msg"] = query.message.message_id

    text = await _msg_gen_photo_count(article, ref_number, ref.get("category", "—"))

    await context.bot.edit_message_caption(
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        caption=text,
        parse_mode="HTML",
        reply_markup=kb_gen_photo_count(),
    )
    return _P_COUNT


# ---------------------------------------------------------------------------
# P1. Сколько фото?
# ---------------------------------------------------------------------------

async def msg_photo_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл количество фото."""
    user = update.effective_user
    text = update.message.text.strip()

    # Удаляем сообщение пользователя
    asyncio.get_event_loop().call_later(
        0, lambda: asyncio.create_task(safe_delete(context.bot, user.id, update.message.message_id))
    )

    screen_msg = context.user_data.get("_screen_msg")

    try:
        count = int(text)
        if count < 1 or count > 20:
            if screen_msg:
                await context.bot.edit_message_caption(
                    chat_id=user.id,
                    message_id=screen_msg,
                    caption="Введите число от 1 до 20:",
                )
            return _P_COUNT
    except ValueError:
        if screen_msg:
            await context.bot.edit_message_caption(
                chat_id=user.id,
                message_id=screen_msg,
                caption="Пожалуйста, введите число (от 1 до 20):",
            )
        return _P_COUNT

    context.user_data["gen_count"] = count

    # Редактируем экран — показываем P2 (Пожелания)
    article = context.user_data["gen_article"]
    ref_number = context.user_data["gen_ref_number"]
    ref = context.user_data["gen_ref"]
    total_cost = count * PHOTO_COST

    text_p2 = await _msg_gen_photo_wish(article, ref_number, count, total_cost)

    if screen_msg:
        await context.bot.edit_message_caption(
            chat_id=user.id,
            message_id=screen_msg,
            caption=text_p2,
            parse_mode="HTML",
            reply_markup=kb_gen_photo_wish(),
        )
    return _P_WISH


async def cb_no_wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь нажал «Нет пожеланий» — сразу к P3."""
    query = update.callback_query
    await query.answer()

    context.user_data["gen_wish"] = None

    user = update.effective_user
    article = context.user_data["gen_article"]
    ref_number = context.user_data["gen_ref_number"]
    ref = context.user_data["gen_ref"]
    count = context.user_data["gen_count"]
    total_cost = count * PHOTO_COST

    stats = await get_user_stats(user.id)
    balance = stats["balance"]

    if balance < total_cost:
        alert_msg = await context.bot.send_photo(
            chat_id=user.id,
            photo=open("assets/banner_default.png", "rb"),
            caption=msg_insufficient_funds(needed=total_cost, balance=balance),
            parse_mode="HTML",
            reply_markup=kb_alert_close(),
        )
        return _P_WISH

    final_caption = await _msg_gen_photo_confirm(article, count, total_cost, balance, wish=None)

    screen_msg = context.user_data.get("_screen_msg")
    if screen_msg:
        await context.bot.edit_message_caption(
            chat_id=user.id,
            message_id=screen_msg,
            caption=final_caption,
            parse_mode="HTML",
            reply_markup=kb_gen_photo_confirm(),
        )
    return _P_CONFIRM


# ---------------------------------------------------------------------------
# P3. Подтверждение
# ---------------------------------------------------------------------------

async def msg_photo_wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл пожелания или написал «Пропустить»."""
    user = update.effective_user
    text = update.message.text.strip()

    # Удаляем сообщение пользователя
    asyncio.get_event_loop().call_later(
        0, lambda: asyncio.create_task(safe_delete(context.bot, user.id, update.message.message_id))
    )

    wish = None if text.lower() in ("пропустить", "пропуск", "skip", "нет") else text
    context.user_data["gen_wish"] = wish

    # Показываем экран P3 — Подтверждение
    article = context.user_data["gen_article"]
    ref_number = context.user_data["gen_ref_number"]
    ref = context.user_data["gen_ref"]
    count = context.user_data["gen_count"]
    total_cost = count * PHOTO_COST

    # Проверяем баланс
    stats = await get_user_stats(user.id)
    balance = stats["balance"]

    if balance < total_cost:
        alert_msg = await context.bot.send_photo(
            chat_id=user.id,
            photo=open("assets/banner_default.png", "rb"),
            caption=msg_insufficient_funds(needed=total_cost, balance=balance),
            parse_mode="HTML",
            reply_markup=kb_alert_close(),
        )
        return _P_WISH

    final_caption = await _msg_gen_photo_confirm(article, count, total_cost, balance, wish=wish)

    screen_msg = context.user_data.get("_screen_msg")
    if screen_msg:
        await context.bot.edit_message_caption(
            chat_id=user.id,
            message_id=screen_msg,
            caption=final_caption,
            parse_mode="HTML",
            reply_markup=kb_gen_photo_confirm(),
        )
    return _P_CONFIRM


# ---------------------------------------------------------------------------
# P3. Подтверждение
# ---------------------------------------------------------------------------

async def cb_gen_photo_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь подтвердил генерацию — создаём job + tasks в БД."""
    query = update.callback_query
    await query.answer()

    user_id    = update.effective_user.id
    article    = context.user_data["gen_article"]
    ref_number = context.user_data["gen_ref_number"]
    ref        = context.user_data["gen_ref"]
    count      = context.user_data["gen_count"]
    wish       = context.user_data.get("gen_wish")
    screen_msg = context.user_data.get("_screen_msg")
    total_cost = count * PHOTO_COST

    logger.info("GEN_PHOTO_START | user=%s article=%s ref=%d count=%d", user_id, article, ref_number, count)

    # Формируем URL эталона
    ref_image_url = ref.get("reference_image_url", "")
    if not ref_image_url:
        file_path = ref.get("file_path", "")
        if file_path:
            import os
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

    # Генерируем промпты
    description = ref["product_description"]
    base_prompts = await generate_photo_prompts(
        description=description,
        category=ref.get("category", "верх"),
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

    # Создаём N задач внутри job
    for prompt in prompts:
        await create_job_task(
            job_id=job_id,
            user_id=user_id,
            chat_id=user_id,
            article=article,
            prompt=prompt,
        )

    logger.info("GEN_PHOTO | job_id=%d | created %d tasks", job_id, count)

    # Показываем экран P4 — ожидание
    generating_caption = await _msg_gen_photo_generating(article, count)
    await context.bot.edit_message_caption(
        chat_id=user_id,
        message_id=screen_msg,
        caption=generating_caption,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")],
        ]),
    )

    return _P_GENERATING


# ---------------------------------------------------------------------------
# Навигация — назад
# ---------------------------------------------------------------------------

async def cb_back_to_ref_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к карточке эталона."""
    from handlers.flows.etalon import show_ref_card
    user_id = update.effective_user.id
    article = context.user_data.get("gen_article")
    ref_number = context.user_data.get("gen_ref_number")
    ref_index = context.user_data.get("gen_ref_index", 0)
    if article and ref_number:
        # Сохраняем article_code и ref_number_for_gen как в etalon.py
        context.user_data["article_code"] = article
        context.user_data["ref_number_for_gen"] = ref_number
        # Возвращаемся к карточке эталона напрямую
        return await show_ref_card(update.effective_user, article, ref_index, context.bot, update.callback_query)
    from handlers.flows.onboarding import cb_back_to_menu
    return await cb_back_to_menu(update, context)


async def cb_quick_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Быстрый выбор количества фото (кнопки 1 / 5 / 10)."""
    query = update.callback_query
    await query.answer()

    count = int(query.data.replace("gen_count_", ""))
    context.user_data["gen_count"] = count

    # Переходим к P2 — Пожелания
    user = update.effective_user
    screen_msg = context.user_data.get("_screen_msg")
    article = context.user_data["gen_article"]
    ref_number = context.user_data["gen_ref_number"]
    total_cost = count * PHOTO_COST

    text_p2 = await _msg_gen_photo_wish(article, ref_number, count, total_cost)

    if screen_msg:
        await context.bot.edit_message_caption(
            chat_id=user.id,
            message_id=screen_msg,
            caption=text_p2,
            parse_mode="HTML",
            reply_markup=kb_gen_photo_wish(),
        )
    return _P_WISH


async def cb_back_to_p_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к вводу числа."""
    query = update.callback_query
    await query.answer()

    inter_msg = context.user_data.get("gen_intermediate_msg")
    if inter_msg:
        await safe_delete(context.bot, update.effective_user.id, inter_msg)

    article = context.user_data.get("gen_article", "")
    ref_number = context.user_data.get("gen_ref_number", "")
    ref = context.user_data.get("gen_ref", {})

    text = await _msg_gen_photo_count(article, ref_number, ref.get("category", "—"))

    await context.bot.edit_message_caption(
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        caption=text,
        parse_mode="HTML",
        reply_markup=kb_gen_photo_count(),
    )
    return _P_COUNT


async def cb_back_to_p_wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к пожеланиям."""
    query = update.callback_query
    await query.answer()

    screen_msg = context.user_data.get("_screen_msg")
    article = context.user_data.get("gen_article", "")
    ref_number = context.user_data.get("gen_ref_number", "")

    count = context.user_data.get("gen_count", 1)
    total_cost = count * PHOTO_COST
    text = await _msg_gen_photo_wish(article, ref_number, count, total_cost)

    if screen_msg:
        await context.bot.edit_message_caption(
            chat_id=query.message.chat_id,
            message_id=screen_msg,
            caption=text,
            parse_mode="HTML",
            reply_markup=kb_gen_photo_wish(),
        )
    return _P_WISH


async def cb_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад в главное меню."""
    from handlers.flows.onboarding import cb_back_to_menu
    return await cb_back_to_menu(update, context)


async def cb_close_alert_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Закрыть алерт-сообщение (недостаточно средств)."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    # Возвращаемся к P_WISH — откуда пришли (Нет пожеланий / Пожелания)
    return _P_WISH


async def _msg_gen_photo_count(article: str, ref_number: int | str, category: str) -> str:
    template = await get_template("msg_gen_photo_count", fallback=_GEN_PHOTO_COUNT_TEXT_FALLBACK)
    return template.format(
        article=article,
        ref_number=ref_number,
        category=category or "—",
        photo_cost=PHOTO_COST,
    )


async def _msg_gen_photo_wish(article: str, ref_number: int | str, count: int, total_cost: int) -> str:
    template = await get_template("msg_gen_photo_wish", fallback=_GEN_PHOTO_WISH_TEXT_FALLBACK)
    return template.format(
        article=article,
        ref_number=ref_number,
        count=count,
        total_cost=total_cost,
    )


async def _msg_gen_photo_confirm(article: str, count: int, total_cost: int, balance: int, wish: str | None) -> str:
    template = await get_template("msg_gen_photo_confirm", fallback=_GEN_PHOTO_CONFIRM_TEXT_FALLBACK)
    wish_block = f'📝 Пожелания: "{wish}"\n\n' if wish else ""
    return template.format(
        article=article,
        count=count,
        wish_block=wish_block,
        total_cost=total_cost,
        balance=balance,
    )


async def _msg_gen_photo_generating(article: str, count: int) -> str:
    template = await get_template("msg_gen_photo_generating", fallback=_GEN_PHOTO_GENERATING_TEXT_FALLBACK)
    return template.format(article=article, count=count)


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_gen_photo_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_menu_gen_photo, pattern="^menu_gen_photo$"),
        ],
        states={
            _P_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_photo_count),
                CallbackQueryHandler(cb_quick_count, pattern="^gen_count_\d+$"),
                CallbackQueryHandler(cb_back_to_ref_card, pattern="^back_to_ref_card$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cb_close_alert_photo, pattern="^alert_close$"),
            ],
            _P_WISH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_photo_wish),
                CallbackQueryHandler(cb_no_wish, pattern="^gen_photo_no_wish$"),
                CallbackQueryHandler(cb_back_to_p_count, pattern="^back_to_p_count$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cb_close_alert_photo, pattern="^alert_close$"),
            ],
            _P_CONFIRM: [
                CallbackQueryHandler(cb_gen_photo_yes, pattern="^gen_photo_yes$"),
                CallbackQueryHandler(cb_back_to_p_wish, pattern="^back_to_p_wish$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
            _P_GENERATING: [
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cb_menu_gen_photo, pattern="^menu_gen_photo$"),
        ],
        name="gen_photo",
        persistent=False,
        allow_reentry=True,
    )
