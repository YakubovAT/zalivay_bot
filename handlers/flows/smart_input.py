"""
handlers/flows/smart_input.py

Умный перехват ввода артикулов.
Работает ГЛОБАЛЬНО. Если пользователь ввел артикул вне сценария — предлагаем поиск.
Также подхватывает выбор фото для таких сессий.
"""

from __future__ import annotations

import asyncio
import logging
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database import save_article
from handlers.flows.flow_helpers import safe_delete, animate_loading, get_msg_id
from services.wb_parser import get_product_info
from services.media_storage import ensure_article_media_dir, download_all_images

logger = logging.getLogger(__name__)

ARTICLE_PATTERNS = [
    re.compile(r"\b\d{6,9}\b"),
    re.compile(r"wildberries\.ru/catalog/(\d+)"),
]

MAX_PHOTOS = 15


def extract_article(text: str) -> str | None:
    for pattern in ARTICLE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1) if match.groups() else match.group(0)
    return None


def kb_smart_prompt(article: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Найти {article}", callback_data=f"smart_yes_{article}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="smart_no")],
    ])


def kb_photo_select(selected: list, current_idx: int, total: int, done: bool = False):
    row1 = []
    for i in range(1, 4):
        if i in [s for s, _ in selected]:
            row1.append(InlineKeyboardButton(f"✅ {i}", callback_data=f"smart_sel_{i}"))
        else:
            row1.append(InlineKeyboardButton("①②"[i-1], callback_data=f"smart_sel_{i}"))

    row2 = []
    if current_idx > 0:
        row2.append(InlineKeyboardButton("← Пред.", callback_data=f"smart_photo_{current_idx - 1}"))
    else:
        row2.append(InlineKeyboardButton(" ", callback_data="noop"))
    
    row2.append(InlineKeyboardButton(f"{current_idx + 1}/{total}", callback_data="noop"))
    
    if current_idx < total - 1:
        row2.append(InlineKeyboardButton("След. →", callback_data=f"smart_photo_{current_idx + 1}"))
    else:
        row2.append(InlineKeyboardButton(" ", callback_data="noop"))

    rows = [row1, row2]
    if done:
        rows.append([InlineKeyboardButton("✅ Утвердить выбор", callback_data="smart_photos_confirm")])
    
    return InlineKeyboardMarkup(rows)


def _selection_text(selected_count: int) -> str:
    if selected_count == 0: return "Выберите фото №1 — где товар виден лучше всего."
    elif selected_count == 1: return "Отлично! Теперь выберите фото №2."
    elif selected_count == 2: return "Осталось одно! Выберите фото №3."
    return ""


async def on_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text.startswith("/"): return
    
    # Игнорируем, если это ответ на inline query или что-то служебное
    if not update.message.text: return

    article = extract_article(update.message.text.strip())
    if not article: return

    user_id = update.effective_user.id
    # Удаляем сообщение пользователя в любом случае
    await safe_delete(context.bot, user_id, update.message.message_id)

    # Пытаемся найти ID текущего экрана, чтобы отредактировать его
    current_msg_id = get_msg_id(user_id)
    
    text = f"🔍 Распознан артикул: <b>{article}</b>\n\nХотите найти товар с этим артикулом сейчас?"
    keyboard = kb_smart_prompt(article)

    if current_msg_id:
        # Пытаемся отредактировать текущий экран
        try:
            await context.bot.edit_message_caption(
                chat_id=user_id, message_id=current_msg_id,
                caption=text, reply_markup=keyboard, parse_mode="HTML"
            )
            context.user_data[f"smart_prompt_{user_id}"] = current_msg_id
            return # Успешно отредактировали
        except Exception:
            pass # Если не вышло (например, другой тип медиа), отправим новое

    # Если редактирование не удалось или ID нет — шлем новое
    prompt_msg = await context.bot.send_photo(
        chat_id=user_id,
        photo=open("assets/banner_default.png", "rb"),
        caption=text, reply_markup=keyboard, parse_mode="HTML"
    )
    context.user_data[f"smart_prompt_{user_id}"] = prompt_msg.message_id


async def cb_smart_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    article = query.data.split("_")[-1]
    user_id = query.from_user.id
    
    # Если мы редактировали экран, то prompt_id == экрану. Не удаляем его, а меняем контент.
    prompt_id = context.user_data.pop(f"smart_prompt_{user_id}", None)
    
    # Показываем загрузку ПРЯМО В ЭТОМ ЖЕ ОКНЕ
    loading_caption = f"⏳ Ищу товар {article}..."
    try:
        if prompt_id:
            await context.bot.edit_message_caption(
                chat_id=user_id, message_id=prompt_id,
                caption=loading_caption
            )
            loading_msg_id = prompt_id
        else:
            msg = await context.bot.send_photo(
                chat_id=user_id, photo=open("assets/banner_default.png", "rb"),
                caption=loading_caption
            )
            loading_msg_id = msg.message_id
    except:
        # Fallback
        msg = await context.bot.send_message(chat_id=user_id, text=loading_caption)
        loading_msg_id = msg.message_id

    product = await get_product_info(article)
    
    # Удаляем загрузку
    await safe_delete(context.bot, user_id, loading_msg_id)

    if not product or not product.get("name"):
        # Алерт об ошибке (удаляется сам)
        alert = await context.bot.send_message(chat_id=user_id, text=f"❌ Артикул {article} не найден.")
        asyncio.get_event_loop().call_later(5, lambda: asyncio.create_task(safe_delete(context.bot, user_id, alert.message_id)))
        # Возвращаемся в меню? Или оставляем как было?
        # Лучше показать меню снова.
        # Но это сложно без контекста. Просто оставим алерт.
        return

    # Успех: сохраняем и переходим к фото
    await save_article(
        user_id=user_id, article_code=article, marketplace="WB",
        name=product.get("name"), color=product.get("colors", ["—"])[0] if product.get("colors") else "—",
        material=product.get("material", "—"), wb_images=product.get("images", [])
    )

    media_dir = ensure_article_media_dir(user_id, "WB", article)
    images = product.get("images", [])[:MAX_PHOTOS]
    local_paths = await download_all_images(images, media_dir)
    
    if not local_paths:
        await context.bot.send_message(chat_id=user_id, text="❌ Не удалось загрузить фото.")
        return

    context.user_data["smart_article"] = article
    context.user_data["smart_product"] = product
    context.user_data["smart_photo_paths"] = local_paths
    context.user_data["smart_photo_selected"] = []
    context.user_data["smart_photo_idx"] = 0

    # Показываем первое фото (создаем новое сообщение, т.к. загрузку удалили)
    await _show_smart_photo(context, user_id, 0, local_paths, [], is_new=True)


async def _show_smart_photo(context, user_id, idx, paths, selected, is_new=False, message_id=None):
    photo_path = paths[idx]
    total = len(paths)
    selected_count = len(selected)
    done = selected_count >= 3
    caption = f"Шаг 6 из N: Выбор фото — {idx + 1} из {total}\n\n{_selection_text(selected_count)}"
    keyboard = kb_photo_select(selected, idx, total, done)

    if message_id:
        try:
            await context.bot.edit_message_media(
                chat_id=user_id, message_id=message_id,
                media=InputMediaPhoto(media=open(photo_path, "rb"), caption=caption),
                reply_markup=keyboard
            )
        except:
            await context.bot.edit_message_caption(
                chat_id=user_id, message_id=message_id,
                caption=caption, reply_markup=keyboard
            )
    elif is_new:
        msg = await context.bot.send_photo(
            chat_id=user_id, photo=open(photo_path, "rb"),
            caption=caption, reply_markup=keyboard
        )
        context.user_data["smart_photo_msg_id"] = msg.message_id


async def cb_smart_photo_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[-1])
    paths = context.user_data.get("smart_photo_paths", [])
    selected = context.user_data.get("smart_photo_selected", [])
    context.user_data["smart_photo_idx"] = idx
    await _show_smart_photo(context, query.from_user.id, idx, paths, selected, message_id=query.message.message_id)


async def cb_smart_select_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    slot = int(query.data.split("_")[-1])
    paths = context.user_data.get("smart_photo_paths", [])
    selected = context.user_data.get("smart_photo_selected", [])
    idx = context.user_data.get("smart_photo_idx", 0)
    
    selected = [(s, i) for s, i in selected if s != slot]
    selected.append((slot, idx))
    selected.sort()
    context.user_data["smart_photo_selected"] = selected

    done = len(selected) >= 3
    next_idx = idx + 1 if idx < len(paths) - 1 and not done else idx
    await _show_smart_photo(context, query.from_user.id, next_idx if not done else idx, paths, selected, message_id=query.message.message_id)


async def cb_smart_photos_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    selected = context.user_data.get("smart_photo_selected", [])
    paths = context.user_data.get("smart_photo_paths", [])
    article = context.user_data.get("smart_article", "")
    
    chosen = [paths[idx] for _, idx in sorted(selected) if idx < len(paths)]
    
    caption = f"Шаг 7 из N: Подтверждение\n\n✅ Выбрано 3 фото для артикула {article}\nСледующий шаг: создание эталона."
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]])
    
    await context.bot.send_photo(
        chat_id=query.from_user.id, photo=open(chosen[0], "rb") if chosen else open("assets/banner_default.png", "rb"),
        caption=caption, reply_markup=keyboard
    )
    # Очистка контекста
    for k in list(context.user_data.keys()):
        if k.startswith("smart_"): del context.user_data[k]


async def cb_smart_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    prompt_id = context.user_data.pop(f"smart_prompt_{query.from_user.id}", None)
    if prompt_id: await safe_delete(context.bot, query.from_user.id, prompt_id)


def build_smart_input_handlers() -> list:
    return [
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_any_message),
        CallbackQueryHandler(cb_smart_yes, pattern="^smart_yes_"),
        CallbackQueryHandler(cb_smart_no, pattern="^smart_no$"),
        CallbackQueryHandler(cb_smart_photo_nav, pattern="^smart_photo_\d+$"),
        CallbackQueryHandler(cb_smart_select_photo, pattern="^smart_sel_\d$"),
        CallbackQueryHandler(cb_smart_photos_confirm, pattern="^smart_photos_confirm$"),
    ]
