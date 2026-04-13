"""
handlers/flows/new_article.py

Шаг 3: Выбор маркетплейса
Шаг 4: Ввод артикула
Шаг 5: Показ карточки товара и подтверждение
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import get_user_stats, save_article
from handlers.flows.flow_helpers import (
    send_screen, store_msg_id, get_msg_id, safe_delete, animate_loading,
)
from handlers.flows.photo_selection import (
    start_photo_selection,
    _PHOTO_SELECT, _PHOTO_CONFIRM, _REFERENCE_CONFIRM,
    cb_photo_nav, cb_select_photo, cb_photos_confirm,
    cb_back_to_photo_select, cb_back_to_product_confirm,
    cb_create_reference, cb_back_to_menu_from_photo,
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
    "Шаг 3 из N: Выбор маркетплейса\n\n"
    "Выберите маркетплейс, на котором продаётся ваш товар. "
    "После мы с вами создадим фото и видео контент "
    "для последующего размещения в социальных сетях. "
    "Вам нужно будет ввести артикул товара, и мы создадим эталон "
    "вашего товара для генерации фото и видео контента."
)

_LOCKED_TEXT = "⏳ Этот маркетплейс скоро будет доступен"

_ARTICLE_INPUT_TEXT = (
    "Шаг 4 из N: Ввод артикула\n\n"
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
    """Кнопка «🏠 Меню» — возврат в Меню."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    stats = await get_user_stats(user.id)

    text = (
        f"Шаг 2: Профиль\n\n"
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

    from handlers.keyboards import kb_main_menu
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

    # Извлекаем артикул
    digits = re.findall(r"\d{6,10}", text)
    if not digits:
        alert = await context.bot.send_message(
            chat_id=user.id,
            text="❌ Не удалось распознать артикул.\nВведите артикул (6-9 цифр) или ссылку на товар.",
        )
        asyncio.get_event_loop().call_later(5, lambda: asyncio.create_task(safe_delete(context.bot, user.id, alert.message_id)))
        return _ARTICLE_INPUT

    article_code = digits[-1]
    logger.info("ARTICLE_EXTRACTED | user=%s article=%s", user.id, article_code)

    # Получаем ID текущего экрана
    screen_msg_id = get_msg_id(user.id)
    
    # Отправляем ВРЕМЕННОЕ окно скачивания
    loading_msg = await context.bot.send_photo(
        chat_id=user.id,
        photo=open("assets/banner_default.png", "rb"),
        caption="⏳ Ищу товар...1",
    )

    # Анимация на временном окне (максимум 5 сек)
    stop_event = await animate_loading(
        bot=context.bot,
        chat_id=user.id,
        message_id=loading_msg.message_id,
        max_count=5,
    )

    # Парсим WB
    product = await get_product_info(article_code)

    # Останавливаем анимацию и УДАЛЯЕМ временное окно
    stop_event.set()
    await safe_delete(context.bot, user.id, loading_msg.message_id)

    if not product or not product.get("name"):
        alert = await context.bot.send_message(
            chat_id=user.id,
            text=f"❌ Артикул {article_code} не найден. Проверьте и попробуйте снова.",
        )
        asyncio.get_event_loop().call_later(5, lambda: asyncio.create_task(safe_delete(context.bot, user.id, alert.message_id)))
        return _ARTICLE_INPUT

    # Товар найден — РЕДАКТИРУЕМ экран Шага 4 в Шаг 5
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

    caption = (
        f"Шаг 5 из N: Найден товар\n\n"
        f"📦 {name}\n"
        f"🏷 Бренд: {brand}\n"
        f"🎨 Цвет: {color}\n"
        f"🧵 Состав: {material}\n\n"
        "Это тот товар?"
    )

    # РЕДАКТИРУЕМ экран Шага 4 → Шаг 5
    photo_to_send = open(local_path, "rb") if local_path and os.path.exists(local_path) else open("assets/banner_default.png", "rb")
    
    if screen_msg_id:
        try:
            await context.bot.edit_message_media(
                chat_id=user.id,
                message_id=screen_msg_id,
                media=InputMediaPhoto(media=photo_to_send, caption=caption),
                reply_markup=kb_product_confirm(),
            )
        except Exception:
            new_msg = await context.bot.send_photo(
                chat_id=user.id,
                photo=photo_to_send,
                caption=caption,
                reply_markup=kb_product_confirm(),
            )
            store_msg_id(user.id, new_msg.message_id)
            return _PRODUCT_CONFIRM
    else:
        new_msg = await context.bot.send_photo(
            chat_id=user.id,
            photo=photo_to_send,
            caption=caption,
            reply_markup=kb_product_confirm(),
        )
        store_msg_id(user.id, new_msg.message_id)
        return _PRODUCT_CONFIRM

    return _PRODUCT_CONFIRM


# ---------------------------------------------------------------------------
# Шаг 6: Подтверждение товара
# ---------------------------------------------------------------------------

async def cb_product_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь подтвердил: «Да, это он» → передаём управление photo_selection."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    article = context.user_data.get("article_code", "")
    product = context.user_data.get("product", {})
    images = product.get("images", [])
    name = product.get("name", "Товар")
    composition = product.get("material", "—")

    logger.info("PRODUCT_CONFIRMED | user=%s article=%s", user.id, article)

    if not article or not images:
        await context.bot.edit_message_caption(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            caption="❌ Не удалось найти фото товара.",
        )
        return ConversationHandler.END

    # Сохраняем артикул в БД
    await save_article(
        user_id=user.id,
        article_code=article,
        marketplace="WB",
        name=name,
        color=product.get("colors", ["—"])[0] if product.get("colors") else "—",
        material=composition,
        wb_images=images,
    )

    # Передаём управление модулю выбора фото
    return await start_photo_selection(context, user.id, query.message.message_id, article, product, name, composition, images)


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
            # Состояния из photo_selection.py
            _PHOTO_SELECT: [
                CallbackQueryHandler(cb_photo_nav, pattern=r"^photo_(prev|next)_\d+$"),
                CallbackQueryHandler(cb_select_photo, pattern=r"^sel_\d$"),
                CallbackQueryHandler(cb_back_to_product_confirm, pattern="^back_to_product_confirm$"),
                CallbackQueryHandler(cb_back_to_menu_from_photo, pattern="^back_to_menu$"),
            ],
            _PHOTO_CONFIRM: [
                CallbackQueryHandler(cb_photos_confirm, pattern="^photos_confirm$"),
                CallbackQueryHandler(cb_photo_nav, pattern=r"^photo_(prev|next)_\d+$"),
                CallbackQueryHandler(cb_select_photo, pattern=r"^sel_\d$"),
                CallbackQueryHandler(cb_back_to_product_confirm, pattern="^back_to_product_confirm$"),
                CallbackQueryHandler(cb_back_to_menu_from_photo, pattern="^back_to_menu$"),
            ],
            _REFERENCE_CONFIRM: [
                CallbackQueryHandler(cb_create_reference, pattern="^ref_create_yes$"),
                CallbackQueryHandler(cb_back_to_photo_select, pattern="^back_to_photo_select$"),
                CallbackQueryHandler(cb_back_to_menu_from_photo, pattern="^back_to_menu$"),
            ],
        },
        fallbacks=[],
        allow_reentry=True,
        name="new_article",
        persistent=False,
    )
