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
import time
from pathlib import Path

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
from handlers.keyboards import kb_marketplace, kb_enter_article, kb_main_menu, kb_product_confirm, kb_confirm_reference
from services.wb_parser import get_product_info
from services.media_storage import download_image, ensure_article_media_dir, download_all_images
from services.image_merger import merge_photos_horizontal

logger = logging.getLogger(__name__)

# Состояния
_MP_SELECT, _ARTICLE_INPUT, _PRODUCT_CONFIRM, _PHOTO_SELECT, _PHOTO_CONFIRM, _REFERENCE_CONFIRM = range(6)

# Максимум фото для выбора (как в парсере WB)
MAX_PHOTOS = 30

# Валидация артикула WB: только цифры, 6-9 знаков
ARTICLE_RE = re.compile(r"^\d{6,9}$")


# ---------------------------------------------------------------------------
# Шаг 3. Выбор маркетплейса
# ---------------------------------------------------------------------------

_MARKETPLACE_TEXT = (
    "Шаг 3: Выбор маркетплейса\n\n"
    "Выберите маркетплейс, на котором продаётся ваш товар. "
    "После мы с вами создадим фото и видео контент "
    "для последующего размещения в социальных сетях. "
    "Вам нужно будет ввести артикул товара, и мы создадим эталон "
    "вашего товара для генерации фото и видео контента."
)

_LOCKED_TEXT = "⏳ Этот маркетплейс скоро будет доступен"

_ARTICLE_INPUT_TEXT = (
    "Шаг 4: Ввод артикула\n\n"
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

    # Анимация на временном окне (максимум 5 сек)
    stop_event = await animate_loading(
        bot=context.bot,
        chat_id=user.id,
        message_id=loading_msg.message_id,
        max_count=5,
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
        f"Шаг 5: Найден товар\n\n"
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

    # Создаём папку
    media_dir = ensure_article_media_dir(user.id, "WB", article)

    # Отправляем НОВОЕ временное окно загрузки (отдельное сообщение, как при вводе артикула)
    loading_text = f"⏳ Загружаю фото..."
    loading_msg = await context.bot.send_photo(
        chat_id=user.id,
        photo=open("assets/banner_default.png", "rb"),
        caption=loading_text,
    )

    start_time = time.monotonic()

    # Скачиваем фото в фоне
    to_download = images[:MAX_PHOTOS]
    download_task = asyncio.create_task(download_all_images(to_download, media_dir))

    # Анимация в фоне
    context.user_data["_loading_stop"] = asyncio.Event()

    async def _run_animation():
        count = 0
        stop = context.user_data.get("_loading_stop")
        while not stop.is_set() and count < 5:
            count += 1
            try:
                await context.bot.edit_message_caption(
                    chat_id=user.id,
                    message_id=loading_msg.message_id,
                    caption=f"⏳ Загружаю фото...{count}",
                )
            except:
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    asyncio.create_task(_run_animation())

    # Ждём скачивание
    local_paths = await download_task

    # Ждём минимум 5 сек от начала
    elapsed = time.monotonic() - start_time
    if elapsed < 5:
        await asyncio.sleep(5 - elapsed)

    # Останавливаем анимацию и УДАЛЯЕМ временное окно
    context.user_data["_loading_stop"].set()
    await safe_delete(context.bot, user.id, loading_msg.message_id)

    if not local_paths:
        await context.bot.edit_message_caption(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            caption="❌ Не удалось загрузить фото.",
        )
        return ConversationHandler.END

    logger.info("PHOTOS_DOWNLOADED | user=%s article=%s count=%d", user.id, article, len(local_paths))

    # Сохраняем список фото в контекст
    context.user_data["photo_paths"] = local_paths
    context.user_data["photo_selected"] = []
    context.user_data["photo_idx"] = 0

    # РЕДАКТИРУЕМ Шаг 5 → Шаг 6 (выбор фото)
    await _show_photo(context, user.id, query.message.message_id, 0, local_paths, [])
    return _PHOTO_SELECT


# ---------------------------------------------------------------------------
# Шаг 7: Выбор 3 лучших фото
# ---------------------------------------------------------------------------

def _kb_photo_select(selected: list, current_idx: int, total: int, done: bool = False):
    """Клавиатура для выбора фото (Эмодзи-круги, без пустых кнопок)."""
    row1 = []
    selected_slots = [s for s, _ in selected]
    for i in range(1, 4):
        if i in selected_slots:
            row1.append(InlineKeyboardButton(f"🔘 {i}", callback_data=f"sel_{i}"))
        else:
            row1.append(InlineKeyboardButton(f"⚪ {i}", callback_data=f"sel_{i}"))

    # Динамический второй ряд (2-3 кнопки)
    row2 = []
    has_prev = current_idx > 0
    has_next = current_idx < total - 1

    if has_prev:
        row2.append(InlineKeyboardButton("← Пред.", callback_data=f"photo_prev_{current_idx - 1}"))
    
    row2.append(InlineKeyboardButton(f"{current_idx + 1}/{total}", callback_data="noop"))

    if has_next:
        row2.append(InlineKeyboardButton("След. →", callback_data=f"photo_next_{current_idx + 1}"))

    rows = [row1, row2]
    if done:
        rows.append([InlineKeyboardButton("✅ Утвердить выбор", callback_data="photos_confirm")])
    
    rows.append([
        InlineKeyboardButton("← Назад", callback_data="back_to_mp"),
        InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
    ])

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
    
    caption = f"Шаг 6: Выбор фото — {idx + 1} из {total}\n\n{_selection_text(selected_count)}"
    keyboard = _kb_photo_select(selected, idx, total, done)

    if message_id is not None:
        try:
            await context.bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=InputMediaPhoto(media=open(photo_path, "rb"), caption=caption),
                reply_markup=keyboard,
            )
        except Exception as e:
            if "Message is not modified" in str(e):
                pass
            else:
                try:
                    await context.bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=message_id,
                        caption=caption,
                        reply_markup=keyboard,
                    )
                except Exception as e2:
                    if "Message is not modified" not in str(e2):
                        logger.warning("edit_caption failed: %s", e2)
    else:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=open(photo_path, "rb"),
            caption=caption,
            reply_markup=keyboard,
        )


async def cb_photo_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Листание фото (пропускает уже выбранные)."""
    query = update.callback_query
    await query.answer()

    # Парсим: photo_prev_3 или photo_next_5
    parts = query.data.split("_")
    target_idx = int(parts[-1])
    
    context.user_data["photo_idx"] = target_idx
    paths = context.user_data.get("photo_paths", [])
    selected = context.user_data.get("photo_selected", [])
    selected_indices = {idx for _, idx in selected}

    # Проверяем, не выбрано ли это фото
    if target_idx in selected_indices:
        # Ищем ближайший невыбранный
        step = -1 if "prev" in query.data else 1
        new_idx = target_idx + step
        while 0 <= new_idx < len(paths):
            if new_idx not in selected_indices:
                break
            new_idx += step
        
        if new_idx < 0 or new_idx >= len(paths):
            await query.answer("Нет доступных фото", show_alert=True)
            return _PHOTO_SELECT
        context.user_data["photo_idx"] = new_idx
        target_idx = new_idx

    await _show_photo(context, query.from_user.id, query.message.message_id, target_idx, paths, selected)
    return _PHOTO_SELECT


async def cb_select_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор или отмена выбора фото."""
    query = update.callback_query
    await query.answer()

    slot = int(query.data.split("_")[1])
    paths = context.user_data.get("photo_paths", [])
    selected = context.user_data.get("photo_selected", [])
    idx = context.user_data.get("photo_idx", 0)

    # Проверяем: этот слот уже выбран ТЕКУЩИМ фото? → ОТМЕНА
    existing = next((s for s, i in selected if s == slot), None)
    if existing == idx:
        # Отменяем выбор: убираем этот слот
        selected = [(s, i) for s, i in selected if s != slot]
        context.user_data["photo_selected"] = selected
        await _show_photo(context, query.from_user.id, query.message.message_id, idx, paths, selected)
        return _PHOTO_SELECT

    # Иначе: записываем фото в слот (заменяем если слот был занят)
    selected = [(s, i) for s, i in selected if s != slot]
    selected.append((slot, idx))
    selected.sort()
    context.user_data["photo_selected"] = selected

    done = len(selected) >= 3
    # Если выбрано — ищем следующее невыбранное
    if not done:
        selected_indices = {i for _, i in selected}
        next_idx = idx + 1
        while next_idx < len(paths) and next_idx in selected_indices:
            next_idx += 1
        if next_idx >= len(paths):
            next_idx = idx
    else:
        next_idx = idx

    await _show_photo(context, query.from_user.id, query.message.message_id, next_idx, paths, selected)
    return _PHOTO_CONFIRM if done else _PHOTO_SELECT


async def cb_photos_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Утверждение выбора 3 фото → показ Шага 7 (коллаж + подтверждение создания эталона)."""
    query = update.callback_query
    await query.answer()

    selected = context.user_data.get("photo_selected", [])
    paths = context.user_data.get("photo_paths", [])
    article = context.user_data.get("article_code", "")

    # Собираем пути выбранных фото по порядку слотов
    chosen_paths = [paths[idx] for _, idx in sorted(selected) if idx < len(paths)]
    context.user_data["chosen_photo_paths"] = chosen_paths

    logger.info("PHOTOS_CONFIRMED | user=%s article=%s chosen=%d",
                query.from_user.id, article, len(chosen_paths))

    # Склеиваем 3 фото в коллаж
    merged_path = f"media/{query.from_user.id}/temp/{article}_collage.png"
    merge_ok = merge_photos_horizontal(chosen_paths, merged_path, target_height=350, spacing=8)

    if not merge_ok or not Path(merged_path).exists():
        merged_path = chosen_paths[0] if chosen_paths else "assets/banner_default.png"

    caption = (
        f"Шаг 7 из N: Создание эталона\n\n"
        f"Вы выбрали 3 фото для артикула <code>{article}</code>.\n\n"
        f"Убедитесь, что на этих фото товар виден лучше всего — "
        f"по ним будет создан эталон для генерации контента."
    )

    # Редактируем текущий экран
    try:
        await context.bot.edit_message_media(
            chat_id=query.from_user.id,
            message_id=query.message.message_id,
            media=InputMediaPhoto(media=open(merged_path, "rb"), caption=caption, parse_mode="HTML"),
            reply_markup=kb_confirm_reference(),
        )
    except Exception:
        await context.bot.edit_message_caption(
            chat_id=query.from_user.id,
            message_id=query.message.message_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb_confirm_reference(),
        )

    return _REFERENCE_CONFIRM


# ---------------------------------------------------------------------------
# Шаг 8: Создание эталона (TODO)
# ---------------------------------------------------------------------------

async def cb_create_reference(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь нажал «✅ Создать эталон»."""
    query = update.callback_query
    await query.answer()

    article = context.user_data.get("article_code", "")
    chosen_paths = context.user_data.get("chosen_photo_paths", [])
    user = query.from_user

    logger.info("CREATE_REFERENCE | user=%s article=%s photos=%d", user.id, article, len(chosen_paths))

    # TODO: Здесь будет:
    # 1. Проверка баланса (get_price('create_reference'))
    # 2. Если баланс OK → списание + T2I генерация
    # 3. Если баланс < нужного → алерт "Недостаточно средств"
    
    await context.bot.edit_message_caption(
        chat_id=user.id,
        message_id=query.message.message_id,
        caption=f"Шаг 8 из N: Создание эталона\n\n⏳ Генерирую эталон для артикула <code>{article}</code>...\n\n(Функция генерации будет добавлена позже)",
        parse_mode="HTML",
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
                CallbackQueryHandler(cb_photo_nav, pattern="^photo_(prev|next)_\d+$"),
                CallbackQueryHandler(cb_select_photo, pattern="^sel_\d$"),
                CallbackQueryHandler(cb_back_to_mp, pattern="^back_to_mp$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
            _PHOTO_CONFIRM: [
                CallbackQueryHandler(cb_photos_confirm, pattern="^photos_confirm$"),
                CallbackQueryHandler(cb_photo_nav, pattern="^photo_(prev|next)_\d+$"),
                CallbackQueryHandler(cb_select_photo, pattern="^sel_\d$"),
                CallbackQueryHandler(cb_back_to_mp, pattern="^back_to_mp$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
            _REFERENCE_CONFIRM: [
                CallbackQueryHandler(cb_create_reference, pattern="^ref_create_yes$"),
                CallbackQueryHandler(cb_back_to_mp, pattern="^back_to_mp$"),
                CallbackQueryHandler(cb_back_to_menu, pattern="^back_to_menu$"),
            ],
        },
        fallbacks=[],
        allow_reentry=True,
        name="new_article",
        persistent=False,
    )
