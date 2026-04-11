"""
handlers/flows/new_article.py

Шаг 3: Выбор маркетплейса
Шаг 4: Ввод артикула
Шаг 5: Парсинг WB
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import get_user_stats
from handlers.flows.flow_helpers import (
    send_screen, store_msg_id, safe_delete, animate_loading,
)
from handlers.keyboards import kb_marketplace, kb_enter_article, kb_main_menu, kb_product_confirm
from services.wb_parser import get_product_info
from services.media_storage import download_image

logger = logging.getLogger(__name__)

# Состояния
_MP_SELECT, _ARTICLE_INPUT, _PRODUCT_CONFIRM = range(3)

# Валидация артикула WB: только цифры, 6-9 знаков
ARTICLE_RE = re.compile(r"^\d{6,9}$")


# ---------------------------------------------------------------------------
# Шаг 3. Выбор маркетплейса
# ---------------------------------------------------------------------------

_MARKETPLACE_TEXT = (
    "Выберите маркетплейс, на котором продаётся ваш товар. "
    "После мы с вами создадим фото и видео контент "
    "для последующего размещения в социальных сетях. "
    "Вам нужно будет ввести артикул товара, и мы создадим эталон "
    "вашего товара для генерации фото и видео контента."
)

_LOCKED_TEXT = "⏳ Этот маркетплейс скоро будет доступен"

_ARTICLE_INPUT_TEXT = (
    "В строку сообщений введите артикул.\n\n"
    "Мы загрузим фото из карточки. Выберите "
    "3 лучших — где ваш товар виден наиболее "
    "чётко и детально. Это станет основой "
    "для генерации фото и видео контента."
)


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
    """Пользователь выбрал WB."""
    query = update.callback_query
    await query.answer()

    await send_screen(
        context.bot,
        chat_id=query.from_user.id,
        message_id=query.message.message_id,
        text=_ARTICLE_INPUT_TEXT,
        keyboard=kb_enter_article(),
    )
    return _ARTICLE_INPUT


async def cb_mp_locked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь выбрал ещё не доступный маркетплейс."""
    query = update.callback_query
    await query.answer(_LOCKED_TEXT, show_alert=True)
    return _MP_SELECT


async def cb_back_to_mp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка «← Назад» — возврат к выбору маркетплейса."""
    query = update.callback_query
    await query.answer()

    await send_screen(
        context.bot,
        chat_id=query.from_user.id,
        message_id=query.message.message_id,
        text=_MARKETPLACE_TEXT,
        keyboard=kb_marketplace(),
    )
    return _MP_SELECT


async def cb_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка «← Назад» — возврат в Меню."""
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
# Шаг 4-5. Ввод артикула + Парсинг
# ---------------------------------------------------------------------------

async def msg_article_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл артикул — валидируем, парсим, показываем карточку."""
    user = update.effective_user
    text = update.message.text.strip()

    # Удаляем сообщение пользователя
    try:
        await update.message.delete()
    except Exception:
        pass

    logger.info("ARTICLE_INPUT | user=%s text=%r", user.id, text)

    # Извлекаем артикул: ищем 7-10 цифр подряд (или 6-9 для строгой валидации)
    digits = re.findall(r"\d{6,10}", text)
    if not digits:
        # Алерт: не распознан
        alert = await context.bot.send_message(
            chat_id=user.id,
            text="❌ Не удалось распознать артикул.\nВведите артикул (6-9 цифр) или ссылку на товар.",
        )
        asyncio.get_event_loop().call_later(5, lambda: asyncio.create_task(safe_delete(context.bot, user.id, alert.message_id)))
        return _ARTICLE_INPUT

    article_code = digits[-1]  # берём последнее найденное число
    logger.info("ARTICLE_EXTRACTED | user=%s article=%s", user.id, article_code)

    # Отправляем экран загрузки (с баннером)
    loading_msg = await context.bot.send_photo(
        chat_id=user.id,
        photo=open("assets/banner_default.png", "rb"),
        caption="⏳ Ищу товар...1",
    )

    # Запускаем анимацию в фоне
    stop_event = await animate_loading(
        bot=context.bot,
        chat_id=user.id,
        message_id=loading_msg.message_id,
    )

    # Парсим WB
    product = await get_product_info(article_code)

    # Останавливаем анимацию и удаляем экран загрузки
    stop_event.set()
    await safe_delete(context.bot, user.id, loading_msg.message_id)

    if not product or not product.get("name"):
        # Алерт: товар не найден
        alert = await context.bot.send_message(
            chat_id=user.id,
            text=f"❌ Артикул {article_code} не найден. Проверьте и попробуйте снова.",
        )
        asyncio.get_event_loop().call_later(5, lambda: asyncio.create_task(safe_delete(context.bot, user.id, alert.message_id)))
        return _ARTICLE_INPUT

    # Товар найден — скачиваем первое фото, показываем карточку
    context.user_data["article_code"] = article_code
    context.user_data["product"] = product
    logger.info("PRODUCT_FOUND | user=%s name=%s", user.id, product.get("name"))

    # Скачиваем первое фото товара
    images = product.get("images", [])
    first_image_url = images[0] if images else ""
    local_path = ""

    if first_image_url:
        local_path = f"media/{user.id}/temp/{article_code}_first.webp"
        await download_image(first_image_url, local_path)

    # Формируем описание
    name = product.get("name", "—")
    brand = product.get("brand", "—")
    color = product.get("colors", ["—"])[0] if product.get("colors") else "—"
    material = product.get("material", "—")

    text = (
        f"Нашёл товар:\n\n"
        f"📦 {name}\n"
        f"🏷 Бренд: {brand}\n"
        f"🎨 Цвет: {color}\n"
        f"🧵 Состав: {material}\n\n"
        "Это тот товар?"
    )

    # Отправляем карточку: фото товара + описание
    await context.bot.send_photo(
        chat_id=user.id,
        photo=open(local_path, "rb") if local_path and os.path.exists(local_path) else open("assets/banner_default.png", "rb"),
        caption=text,
        reply_markup=kb_product_confirm(),
    )

    return _PRODUCT_CONFIRM


# ---------------------------------------------------------------------------
# Шаг 6: Подтверждение товара
# ---------------------------------------------------------------------------

async def cb_product_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь подтвердил: «Да, это он»."""
    query = update.callback_query
    await query.answer()
    
    article = context.user_data.get("article_code", "?")
    product = context.user_data.get("product", {})
    
    logger.info("PRODUCT_CONFIRMED | user=%s article=%s", query.from_user.id, article)

    # TODO: Шаг 7 — проверка баланса + предложение создать эталон
    await context.bot.edit_message_caption(
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        caption=f"✅ Отлично! Товар подтверждён.\n\n📦 {product.get('name', article)}\n\nСледующий шаг: создание эталона.",
    )
    return ConversationHandler.END


async def cb_product_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь отказался: «Нет, другой»."""
    query = update.callback_query
    await query.answer()
    
    logger.info("PRODUCT_REJECTED | user=%s", query.from_user.id)

    # Возврат к вводу артикула
    await send_screen(
        context.bot,
        chat_id=query.from_user.id,
        message_id=query.message.message_id,
        text=_ARTICLE_INPUT_TEXT,
        keyboard=kb_enter_article(),
    )
    return _ARTICLE_INPUT


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
                CallbackQueryHandler(cb_back_to_mp, pattern="^back_to_mp$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_article_input),
            ],
            _PRODUCT_CONFIRM: [
                CallbackQueryHandler(cb_product_yes, pattern="^product_yes$"),
                CallbackQueryHandler(cb_product_no, pattern="^product_no$"),
                CallbackQueryHandler(cb_back_to_mp, pattern="^back_to_mp$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
        },
        fallbacks=[],
        allow_reentry=True,
        name="new_article",
        persistent=False,
    )
