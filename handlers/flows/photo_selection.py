"""
handlers/flows/photo_selection.py

Шаг 6: Выбор 3 лучших фото из карточки товара.
Шаг 7: Подтверждение создания эталона (коллаж).
Шаг 8: Создание эталона (заглушка).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
)

from database import save_article
from handlers.flows.flow_helpers import safe_delete, animate_loading
from handlers.keyboards import kb_confirm_reference, kb_photo_select
from services.media_storage import ensure_article_media_dir, download_all_images
from services.image_merger import merge_photos_horizontal
from services.prompt_store import get_template

logger = logging.getLogger(__name__)

# Состояния (10-12, чтобы не пересекаться с new_article 0-2)
_PHOTO_SELECT, _PHOTO_CONFIRM, _REFERENCE_CONFIRM = range(10, 13)
_REFERENCE_GENERATING = 13  # Из create_reference.py


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

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

    selection_text = _selection_text(selected_count)
    template = await get_template("msg_photo_select")
    caption = template.format(
        current=idx + 1,
        total=total,
        selection_text=selection_text,
    )
    keyboard = kb_photo_select(selected, idx, total, done)

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


# ---------------------------------------------------------------------------
# Вход в flow (вызывается из new_article)
# ---------------------------------------------------------------------------

async def start_photo_selection(context: ContextTypes.DEFAULT_TYPE, user_id: int, message_id: int, article: str, product: dict, name: str, composition: str, images: list) -> int:
    """Запускает процесс выбора фото. Вызывается после подтверждения товара."""
    # Создаём папку и скачиваем фото
    media_dir = ensure_article_media_dir(user_id, "WB", article)
    
    loading_text = f"⏳ Загружаю фото..."
    loading_msg = await context.bot.send_photo(
        chat_id=user_id,
        photo=open("assets/banner_default.png", "rb"),
        caption=loading_text,
    )

    start_time = time.monotonic()

    # Скачиваем фото в фоне
    to_download = images[:30]  # MAX_PHOTOS
    download_task = asyncio.create_task(download_all_images(to_download, media_dir))

    # Анимация
    context.user_data["_loading_stop"] = asyncio.Event()

    async def _run_animation():
        count = 0
        stop = context.user_data.get("_loading_stop")
        while not stop.is_set() and count < 5:
            count += 1
            try:
                await context.bot.edit_message_caption(
                    chat_id=user_id,
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

    local_paths = await download_task

    # Ждём минимум 5 сек
    elapsed = time.monotonic() - start_time
    if elapsed < 5:
        await asyncio.sleep(5 - elapsed)

    context.user_data["_loading_stop"].set()
    await safe_delete(context.bot, user_id, loading_msg.message_id)

    if not local_paths:
        await context.bot.edit_message_caption(
            chat_id=user_id,
            message_id=message_id,
            caption="❌ Не удалось загрузить фото.",
        )
        return ConversationHandler.END

    context.user_data["photo_paths"] = local_paths
    context.user_data["photo_selected"] = []
    context.user_data["photo_idx"] = 0

    await _show_photo(context, user_id, message_id, 0, local_paths, [])
    return _PHOTO_SELECT


# ---------------------------------------------------------------------------
# Обработчики
# ---------------------------------------------------------------------------

async def cb_photo_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Листание фото."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    target_idx = int(parts[-1])
    
    context.user_data["photo_idx"] = target_idx
    paths = context.user_data.get("photo_paths", [])
    selected = context.user_data.get("photo_selected", [])

    await _show_photo(context, query.from_user.id, query.message.message_id, target_idx, paths, selected)
    return _PHOTO_SELECT


async def cb_select_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Логика переключателя (Toggle) для слотов 1, 2, 3."""
    query = update.callback_query
    await query.answer()

    slot = int(query.data.split("_")[1])
    paths = context.user_data.get("photo_paths", [])
    selected = context.user_data.get("photo_selected", [])
    idx = context.user_data.get("photo_idx", 0)

    # Проверяем, занят ли этот слот
    idx_in_slot = next((i for s, i in selected if s == slot), None)

    if idx_in_slot is not None:
        # Слот ЗАНЯТ -> ОТМЕНЯЕМ выбор
        selected = [(s, i) for s, i in selected if s != slot]
    else:
        # Слот ПУСТ -> ЗАНИМАЕМ его текущим фото
        selected = [(s, i) for s, i in selected if i != idx]
        selected.append((slot, idx))
    
    selected.sort()
    context.user_data["photo_selected"] = selected

    done = len(selected) >= 3
    next_idx = idx

    if not done and idx_in_slot is None:
        selected_indices = {i for _, i in selected}
        
        # 1. Ищем вперед
        found = False
        curr = idx + 1
        while curr < len(paths):
            if curr not in selected_indices:
                next_idx = curr
                found = True
                break
            curr += 1
            
        # 2. Если не нашли, ищем с начала (циклически)
        if not found:
            curr = 0
            while curr < idx:
                if curr not in selected_indices:
                    next_idx = curr
                    found = True
                    break
                curr += 1
    
    context.user_data["photo_idx"] = next_idx

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

    template = await get_template("msg_reference_create_confirm")
    caption = template.format(article=article)

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


async def cb_back_to_photo_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка «← Назад» с Шага 7 (подтверждение эталона) -> возврат к Шагу 6 (выбор фото)."""
    query = update.callback_query
    await query.answer()

    paths = context.user_data.get("photo_paths", [])
    selected = context.user_data.get("photo_selected", [])
    idx = context.user_data.get("photo_idx", 0)

    if not paths:
        from handlers.flows.onboarding import cb_back_to_menu
        return await cb_back_to_menu(update, context)

    await _show_photo(context, query.from_user.id, query.message.message_id, idx, paths, selected)
    return _PHOTO_SELECT


async def cb_back_to_product_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка «← Назад (к карточке)» с Шага 6 -> возврат к Шагу 5 (подтверждение товара)."""
    query = update.callback_query
    await query.answer()

    article = context.user_data.get("article_code", "")
    product = context.user_data.get("product", {})
    name = product.get("name", "—")
    brand = product.get("brand", "—")
    color = product.get("colors", ["—"])[0] if product.get("colors") else "—"
    composition = product.get("material", "—")

    caption = (
        f"Шаг 5 из N: Найден товар\n\n"
        f"📦 {name}\n"
        f"🏷 Бренд: {brand}\n"
        f"🎨 Цвет: {color}\n"
        f"🧵 Состав: {composition}\n\n"
        "Это тот товар?"
    )

    # Возвращаем клавиатуру подтверждения товара
    from handlers.keyboards import kb_product_confirm
    first_photo_path = f"media/{query.from_user.id}/temp/{article}_first.webp"

    try:
        media = InputMediaPhoto(
            media=open(first_photo_path, "rb") if Path(first_photo_path).exists() else open("assets/banner_default.png", "rb"),
            caption=caption
        )
        await context.bot.edit_message_media(
            chat_id=query.from_user.id,
            message_id=query.message.message_id,
            media=media,
            reply_markup=kb_product_confirm(),
        )
    except Exception:
        await context.bot.edit_message_caption(
            chat_id=query.from_user.id,
            message_id=query.message.message_id,
            caption=caption,
            reply_markup=kb_product_confirm(),
        )

    # Возвращаем состояние _PRODUCT_CONFIRM (2, как в new_article.py)
    return 2


async def cb_create_reference(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь нажал «✅ Создать эталон» → передаём управление create_reference."""
    query = update.callback_query
    await query.answer()

    from handlers.flows.create_reference import start_reference_generation
    result = await start_reference_generation(
        context=context,
        user_id=query.from_user.id,
        message_id=query.message.message_id,
    )
    # Возвращаем результат start_reference_generation:
    # _REFERENCE_GENERATING — если алерт (недостаточно средств), кнопки остаются активными
    # ConversationHandler.END — если эталон создан успешно
    return result


async def cb_back_to_menu_from_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возврат в главное меню из любого состояния выбора фото."""
    from handlers.flows.onboarding import cb_back_to_menu
    return await cb_back_to_menu(update, context)


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_photo_selection_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[],  # Вызывается программно через start_photo_selection
        states={
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
                CallbackQueryHandler(cb_back_to_menu_from_photo, pattern="^back_to_menu$"),
            ],
            _REFERENCE_CONFIRM: [
                CallbackQueryHandler(cb_create_reference, pattern="^ref_create_yes$"),
                CallbackQueryHandler(cb_back_to_photo_select, pattern="^back_to_photo_select$"),
                CallbackQueryHandler(cb_back_to_menu_from_photo, pattern="^back_to_menu$"),
            ],
        },
        fallbacks=[],
        name="photo_selection",
        persistent=False,
    )
