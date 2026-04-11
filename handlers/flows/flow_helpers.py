"""
flow_helpers.py

Утилиты для паттерна «одно окно»:
  - safe_delete: удаляет сообщение, игнорируя ошибки
  - edit_or_reply: редактирует сообщение бота или отправляет новое
  - clean_input: удаляет сообщение пользователя + подсказку бота, возвращает chat_id

Принцип: пользователь всегда видит ОДНО сообщение бота с кнопками.
При нажатии кнопки — сообщение редактируется (edit_message_text / edit_message_reply_markup).
При нажатии «Назад» — возвращается предыдущий экран.
"""

import logging
from typing import Optional

from telegram import Update, Message, InputMediaPhoto
from telegram.ext import ContextTypes

from config import BANNER_PATH

logger = logging.getLogger(__name__)


async def safe_delete(chat_id: int, message_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Удаляет сообщение, игнорируя ошибки."""
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug("Не удалось удалить сообщение %s: %s", message_id, e)


async def edit_text(
    chat_id: int,
    message_id: int,
    text: str,
    context: ContextTypes.DEFAULT_TYPE,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:
    """Редактирует текст сообщения. Если не вышло — возвращает False."""
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return True
    except Exception as e:
        logger.debug("edit_text failed: %s", e)
        return False


async def edit_caption(
    chat_id: int,
    message_id: int,
    caption: str,
    context: ContextTypes.DEFAULT_TYPE,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:
    """Редактирует подпись к фото."""
    try:
        await context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return True
    except Exception as e:
        logger.debug("edit_caption failed: %s", e)
        return False


async def edit_reply_markup(
    chat_id: int,
    message_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    reply_markup=None,
) -> bool:
    """Редактирует только кнопки (reply_markup)."""
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
        return True
    except Exception as e:
        logger.debug("edit_reply_markup failed: %s", e)
        return False


async def clean_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Удаляет текстовое сообщение пользователя (например, артикул)."""
    if update.message:
        await safe_delete(update.message.chat.id, update.message.message_id, context)


async def clean_bot_message(chat_id: int, message_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Удаляет сообщение бота (например, «Загружаю информацию...»)."""
    await safe_delete(chat_id, message_id, context)


def store_msg_id(context: ContextTypes.DEFAULT_TYPE, key: str, message_id: int) -> None:
    """Сохраняет message_id в context.user_data для последующего редактирования."""
    context.user_data[key] = message_id


def get_msg_id(context: ContextTypes.DEFAULT_TYPE, key: str) -> Optional[int]:
    """Получает сохранённый message_id."""
    return context.user_data.get(key)


def pop_msg_id(context: ContextTypes.DEFAULT_TYPE, key: str) -> Optional[int]:
    """Получает и удаляет сохранённый message_id."""
    return context.user_data.pop(key, None)


# ---------------------------------------------------------------------------
# Баннер — единая ширина экрана
# ---------------------------------------------------------------------------

async def send_screen(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
    banner_path: str = None,
) -> Optional[int]:
    """
    Отправляет экран: баннер + текст + кнопки.
    Возвращает message_id текстового сообщения (для последующего edit).
    """
    path = banner_path or BANNER_PATH
    # Сначала баннер
    try:
        with open(path, "rb") as f:
            banner_msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
            )
    except Exception as e:
        logger.warning("send_screen: не удалось отправить баннер %s: %s", path, e)
        banner_msg = None

    # Затем текст с кнопками
    try:
        text_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as e:
        logger.error("send_screen: не удалось отправить текст: %s", e)
        return None

    # Сохраняем оба ID
    if banner_msg:
        store_msg_id(context, "screen_banner_msg_id", banner_msg.message_id)
    store_msg_id(context, "screen_text_msg_id", text_msg.message_id)

    return text_msg.message_id


async def edit_screen(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:
    """
    Редактирует текст и кнопки текущего экрана.
    Баннер остаётся на месте — редактируем только текстовое сообщение.
    """
    msg_id = get_msg_id(context, "screen_text_msg_id")
    if not msg_id:
        # Fallback: отправляем новый экран
        logger.warning("edit_screen: нет screen_text_msg_id, отправляю новый экран")
        await send_screen(chat_id, context, text, reply_markup, parse_mode)
        return True

    success = await edit_text(chat_id, msg_id, context, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    if not success:
        # Сообщение уже нельзя редактировать — новый экран
        logger.warning("edit_screen: edit failed, sending new screen")
        await send_screen(chat_id, context, text, reply_markup, parse_mode)
    return success


async def replace_screen(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
    banner_path: str = None,
) -> Optional[int]:
    """
    Полная замена экрана: удаляет старый баннер + текст, отправляет новый.
    """
    old_banner = pop_msg_id(context, "screen_banner_msg_id")
    old_text = pop_msg_id(context, "screen_text_msg_id")

    if old_banner:
        await safe_delete(chat_id, old_banner, context)
    if old_text:
        await safe_delete(chat_id, old_text, context)

    return await send_screen(chat_id, context, text, reply_markup, parse_mode, banner_path)
