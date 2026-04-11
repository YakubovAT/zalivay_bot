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
from handlers.keyboards import kb_marketplace, kb_enter_article, kb_main_menu, kb_product_confirm
from services.wb_parser import get_product_info
from services.media_storage import download_image, ensure_article_media_dir, download_all_images

logger = logging.getLogger(__name__)

# Состояния
_MP_SELECT, _ARTICLE_INPUT, _PRODUCT_CONFIRM, _PHOTO_SELECT, _PHOTO_CONFIRM = range(5)

# Максимум фото для выбора
MAX_PHOTOS = 15

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

    # Запоминаем ID текущего экрана (Шаг 4) — будем редактировать его в Шаг 5
    screen_msg_id = get_msg_id(user.id)
    
    # Отправляем ВРЕМЕННОЕ окно скачивания (отдельное сообщение)
    loading_msg = await context.bot.send_photo(
        chat_id=user.id,
        photo=open("assets/banner_default.png", "rb"),
        caption="⏳ Ищу товар...1",
    )

    # Анимация на временном окне
    stop_event = await animate_loading(
        bot=context.bot,
        chat_id=user.id,
        message_id=loading_msg.message_id,
    )

    # Парсим WB
    product = await get_product_info(article_code)

    # Останавливаем анимацию и УДАЛЯЕМ временное окно скачивания
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

    # Товар найден — РЕДАКТИРУЕМ экран Шага 4 в экран Шага 5
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
        f"Шаг 5 из N: Найден товар\n\n"
        f"📦 {name}\n"
        f"🏷 Бренд: {brand}\n"
        f"🎨 Цвет: {color}\n"
        f"🧵 Состав: {material}\n\n"
        "Это тот товар?"
    )

    # РЕДАКТИРУЕМ экран Шага 4 → Шаг 5 (фото + текст + кнопки)
    photo_to_send = open(local_path, "rb") if local_path and os.path.exists(local_path) else open("assets/banner_default.png", "rb")
    
    if screen_msg_id:
        try:
            await context.bot.edit_message_media(
                chat_id=user.id,
                message_id=screen_msg_id,
                media=InputMediaPhoto(media=photo_to_send, caption=text),
                reply_markup=kb_product_confirm(),
            )
        except Exception:
            # Fallback: если не вышло — отправим новое и запомним
            new_msg = await context.bot.send_photo(
                chat_id=user.id,
                photo=photo_to_send,
                caption=text,
                reply_markup=kb_product_confirm(),
            )
            store_msg_id(user.id, new_msg.message_id)
            return _PRODUCT_CONFIRM
    else:
        # Если ID экрана нет — отправляем новое
        new_msg = await context.bot.send_photo(
            chat_id=user.id,
            photo=photo_to_send,
            caption=text,
            reply_markup=kb_product_confirm(),
        )
        store_msg_id(user.id, new_msg.message_id)
        return _PRODUCT_CONFIRM

    return _PRODUCT_CONFIRM


# ---------------------------------------------------------------------------
# Шаг 6: Подтверждение товара
# ---------------------------------------------------------------------------

async def cb_product_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь подтвердил: «Да, это он» → скачиваем фото."""
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

    # Создаём папку и скачиваем все фото (до MAX_PHOTOS)
    media_dir = ensure_article_media_dir(user.id, "WB", article)
    
    # Показываем загрузку
    loading_text = f"Шаг 6 из N: Загрузка фото\n\n📦 {name}\n🧵 Состав: {composition}\n\n⏳ Загружаю фото..."
    loading_msg = await context.bot.send_photo(
        chat_id=user.id,
        photo=open("assets/banner_default.png", "rb"),
        caption=loading_text,
    )

    # Скачиваем фото
    to_download = images[:MAX_PHOTOS]
    local_paths = await download_all_images(to_download, media_dir)
    
    # Удаляем загрузочное
    await safe_delete(context.bot, user.id, loading_msg.message_id)

    if not local_paths:
        await context.bot.send_message(
            chat_id=user.id,
            text="❌ Не удалось загрузить фото. Попробуйте снова.",
        )
        return ConversationHandler.END

    logger.info("PHOTOS_DOWNLOADED | user=%s article=%s count=%d", user.id, article, len(local_paths))

    # Сохраняем список фото в контекст
    context.user_data["photo_paths"] = local_paths
    context.user_data["photo_selected"] = []  # [(slot, idx), ...]
    context.user_data["photo_idx"] = 0

    # Показываем первое фото
    await _show_photo(context, user.id, query.message.message_id, 0, local_paths, [])
    return _PHOTO_SELECT


# ---------------------------------------------------------------------------
# Шаг 7: Выбор 3 лучших фото
# ---------------------------------------------------------------------------

def _kb_photo_select(selected: list, current_idx: int, total: int, done: bool = False):
    """Клавиатура для выбора фото."""
    row1 = []
    for i in range(1, 4):
        if i in [s for s, _ in selected]:
            row1.append(InlineKeyboardButton(f"✅ {i}", callback_data=f"sel_{i}"))
        else:
            row1.append(InlineKeyboardButton("①②③"[i-1], callback_data=f"sel_{i}"))

    row2 = []
    if current_idx > 0:
        row2.append(InlineKeyboardButton("← Пред.", callback_data=f"photo_{current_idx - 1}"))
    else:
        row2.append(InlineKeyboardButton(" ", callback_data="noop"))
    
    row2.append(InlineKeyboardButton(f"{current_idx + 1}/{total}", callback_data="noop"))
    
    if current_idx < total - 1:
        row2.append(InlineKeyboardButton("След. →", callback_data=f"photo_{current_idx + 1}"))
    else:
        row2.append(InlineKeyboardButton(" ", callback_data="noop"))

    rows = [row1, row2]
    if done:
        rows.append([InlineKeyboardButton("✅ Утвердить выбор", callback_data="photos_confirm")])
    
    return InlineKeyboardMarkup(rows)


def _selection_text(selected_count: int) -> str:
    if selected_count == 0:
        return "Выберите фото №1 — где товар виден лучше всего."
    elif selected_count == 1:
        return "Отлично! Теперь выберите фото №2."
    elif selected_count == 2:
        return "Осталось одно! Выберите фото №3."
    return ""


async def _show_photo(context, chat_id, message_id, idx, paths, selected):
    """Показывает фото по индексу."""
    photo_path = paths[idx]
    total = len(paths)
    selected_count = len(selected)
    done = selected_count >= 3
    
    caption = f"Шаг 6 из N: Выбор фото — {idx + 1} из {total}\n\n{_selection_text(selected_count)}"
    keyboard = _kb_photo_select(selected, idx, total, done)

    if message_id is not None:
        try:
            await context.bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=InputMediaPhoto(media=open(photo_path, "rb"), caption=caption),
                reply_markup=keyboard,
            )
        except Exception:
            await context.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=caption,
                reply_markup=keyboard,
            )
    else:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=open(photo_path, "rb"),
            caption=caption,
            reply_markup=keyboard,
        )


async def cb_photo_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Листание фото."""
    query = update.callback_query
    await query.answer()

    idx = int(query.data.split("_")[1])
    paths = context.user_data.get("photo_paths", [])
    selected = context.user_data.get("photo_selected", [])
    
    context.user_data["photo_idx"] = idx
    await _show_photo(context, query.from_user.id, query.message.message_id, idx, paths, selected)
    return _PHOTO_SELECT


async def cb_select_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор фото как №1/2/3."""
    query = update.callback_query
    await query.answer()

    slot = int(query.data.split("_")[1])
    paths = context.user_data.get("photo_paths", [])
    selected = context.user_data.get("photo_selected", [])
    idx = context.user_data.get("photo_idx", 0)
    
    # Убираем старый выбор этого слота
    selected = [(s, i) for s, i in selected if s != slot]
    selected.append((slot, idx))
    selected.sort()
    context.user_data["photo_selected"] = selected

    done = len(selected) >= 3
    next_idx = idx + 1 if idx < len(paths) - 1 and not done else idx
    
    await _show_photo(context, query.from_user.id, query.message.message_id, next_idx if not done else idx, paths, selected)
    return _PHOTO_CONFIRM if done else _PHOTO_SELECT


async def cb_photos_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Утверждение выбора 3 фото."""
    query = update.callback_query
    await query.answer()

    selected = context.user_data.get("photo_selected", [])
    paths = context.user_data.get("photo_paths", [])
    article = context.user_data.get("article_code", "")
    composition = context.user_data.get("product", {}).get("material", "—")
    
    chosen_paths = [paths[idx] for _, idx in sorted(selected) if idx < len(paths)]
    context.user_data["chosen_photo_paths"] = chosen_paths
    
    logger.info("PHOTOS_CONFIRMED | user=%s article=%s chosen=%d", 
                query.from_user.id, article, len(chosen_paths))

    caption = (
        f"Шаг 7 из N: Подтверждение\n\n"
        f"✅ Выбрано 3 фото для артикула {article}\n"
        f"🧵 Состав: {composition}\n\n"
        "Следующий шаг: создание эталона."
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]
    ])
    
    await context.bot.send_photo(
        chat_id=query.from_user.id,
        photo=open(chosen_paths[0], "rb") if chosen_paths else open("assets/banner_default.png", "rb"),
        caption=caption,
        reply_markup=keyboard,
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
            _PHOTO_SELECT: [
                CallbackQueryHandler(cb_photo_nav, pattern="^photo_\d+$"),
                CallbackQueryHandler(cb_select_photo, pattern="^sel_\d$"),
            ],
            _PHOTO_CONFIRM: [
                CallbackQueryHandler(cb_photos_confirm, pattern="^photos_confirm$"),
                CallbackQueryHandler(cb_photo_nav, pattern="^photo_\d+$"),
                CallbackQueryHandler(cb_select_photo, pattern="^sel_\d$"),
            ],
        },
        fallbacks=[],
        allow_reentry=True,
        name="new_article",
        persistent=False,
    )
