"""
handlers/flows/flow_helpers.py

Общие функции для отправки экранов с баннером.

Правила:
- Каждый экран — ОДНО сообщение (фото-баннер + caption)
- При переходах — редактируем текущее сообщение (edit_message_caption / edit_message_media)
- НЕ отправляем новые сообщения — только edit
"""

from __future__ import annotations

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
) -> None:
    """
    Отправляет экран: баннер + caption + inline-кнопки.

    Если message_id указан — редактирует существующее сообщение.
    Если message_id = None — отправляет новое.
    """
    banner = _get_banner()

    if message_id is not None:
        # Редактируем существующее сообщение
        try:
            await app_or_bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
                reply_markup=keyboard,
            )
        except Exception as e:
            # Если ошибка — попробуем просто edit_caption
            try:
                await app_or_bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            except Exception as e2:
                logger.warning("edit_screen failed: %s", e2)
    else:
        # Отправляем новое сообщение
        await app_or_bot.send_photo(
            chat_id=chat_id,
            photo=banner,
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )


async def edit_screen(
    app_or_bot,
    chat_id: int,
    message_id: int,
    text: str = "",
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    """Редактирует текущий экран (баннер + caption)."""
    await send_screen(app_or_bot, chat_id, message_id=message_id, text=text, keyboard=keyboard)
