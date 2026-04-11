"""
handlers/flows/flow_helpers.py

Общие функции для отправки экранов с баннером.

Правила:
- Каждый экран — ОДНО сообщение (фото-баннер + caption)
- При переходах — редактируем текущее сообщение (edit_message_caption / edit_message_media)
- НЕ отправляем новые сообщения — только edit
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application

from config import BANNER_PATH

logger = logging.getLogger(__name__)

_banner_bytes: bytes | None = None


def _get_banner() -> bytes:
    """Загружает баннер один раз в память."""
    global _banner_bytes
    if _banner_bytes is None:
        _banner_bytes = Path(BANNER_PATH).read_bytes()
    return _banner_bytes


async def send_screen(
    app_or_bot,
    chat_id: int,
    message_id: int | None = None,
    text: str = "",
    keyboard: InlineKeyboardMarkup | None = None,
    parse_mode: str = "HTML",
    banner_path: str | None = None,
) -> None:
    """
    Отправляет экран: баннер + caption + inline-кнопки.

    Если message_id указан — редактирует существующее сообщение.
    Если message_id = None — отправляет новое.
    parse_mode: "HTML" (по умолчанию) или "MarkdownV2" (для цитат).
    banner_path: путь к баннеру (по умолчанию assets/banner_default.png).
    """
    if banner_path:
        banner = Path(banner_path).read_bytes()
    else:
        banner = _get_banner()

    if message_id is not None:
        # Редактируем существующее сообщение
        try:
            await app_or_bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=InputMediaPhoto(media=banner, caption=text, parse_mode=parse_mode),
                reply_markup=keyboard,
            )
        except Exception as e:
            try:
                await app_or_bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=keyboard,
                )
            except Exception as e2:
                logger.warning("edit_screen failed: %s", e2)
    else:
        # Отправляем новое сообщение — сохраняем ID как текущий экран
        new_msg = await app_or_bot.send_photo(
            chat_id=chat_id,
            photo=banner,
            caption=text,
            parse_mode=parse_mode,
            reply_markup=keyboard,
        )
        # Запоминаем ID экранного сообщения для пользователя
        store_msg_id(chat_id, new_msg.message_id)


async def edit_screen(
    app_or_bot,
    chat_id: int,
    message_id: int,
    text: str = "",
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    """Редактирует текущий экран (баннер + caption)."""
    await send_screen(app_or_bot, chat_id, message_id=message_id, text=text, keyboard=keyboard)


# ---------------------------------------------------------------------------
# Утилиты (stub — будут доработаны)
# ---------------------------------------------------------------------------

async def safe_delete(bot, chat_id: int, message_id: int) -> None:
    """Безопасное удаление сообщения (без raise при ошибке)."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def edit_text(bot, chat_id: int, message_id: int, text: str, **kwargs) -> None:
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, **kwargs)
    except Exception:
        pass


async def edit_caption(bot, chat_id: int, message_id: int, caption: str, **kwargs) -> None:
    try:
        await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=caption, **kwargs)
    except Exception:
        pass


async def edit_reply_markup(bot, chat_id: int, message_id: int, reply_markup=None, **kwargs) -> None:
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=reply_markup, **kwargs)
    except Exception:
        pass


async def clean_user_message(bot, chat_id: int, message_id: int) -> None:
    await safe_delete(bot, chat_id, message_id)


async def clean_bot_message(bot, chat_id: int, message_id: int) -> None:
    await safe_delete(bot, chat_id, message_id)


_msg_store: dict[int, int] = {}


def store_msg_id(user_id: int, message_id: int) -> None:
    _msg_store[user_id] = message_id


def get_msg_id(user_id: int) -> int | None:
    return _msg_store.get(user_id)


def pop_msg_id(user_id: int) -> int | None:
    return _msg_store.pop(user_id, None)


async def clear_previous_screen(bot, user_id: int) -> None:
    """Удаляет предыдущее экранное сообщение пользователя (при /start)."""
    msg_id = pop_msg_id(user_id)
    if msg_id is not None:
        await safe_delete(bot, user_id, msg_id)


async def replace_screen(bot, chat_id: int, old_message_id: int, text: str,
                          keyboard: InlineKeyboardMarkup | None = None) -> int:
    """Удаляет старый экран и отправляет новый. Возвращает новый message_id."""
    try:
        await safe_delete(bot, chat_id, old_message_id)
    except Exception:
        pass
    new_msg = await bot.send_photo(
        chat_id=chat_id,
        photo=_get_banner(),
        caption=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    store_msg_id(chat_id, new_msg.message_id)
    return new_msg.message_id


# ---------------------------------------------------------------------------
# Анимация загрузки
# ---------------------------------------------------------------------------

async def animate_loading(
    bot,
    chat_id: int,
    message_id: int,
    prefix: str = "⏳ Ищу товар",
    interval: float = 1.0,
    max_count: int = 15,
) -> asyncio.Event:
    """
    Анимированно обновляет caption сообщения: "⏳ Ищу товар...1", "...2", ...
    Возвращает Event — установите его, чтобы остановить анимацию.
    """
    stop_event = asyncio.Event()
    count = 0

    while not stop_event.is_set() and count < max_count:
        count += 1
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=f"{prefix}...{count}",
            )
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

    return stop_event
