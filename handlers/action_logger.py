"""
action_logger.py

Логирует все действия пользователей:
  - сообщения и команды → action_type: 'message' / 'command'
  - нажатия inline-кнопок  → action_type: 'callback'

Пишет в два места:
  1. logs/user_actions.jsonl — один JSON-объект на строку (удобно для grep/tail)
  2. PostgreSQL таблица user_actions — для аналитики и запросов
"""

import json
import logging
import os
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from database import log_user_action
from handlers.menu import BTN_PROFILE, BTN_PHOTO, BTN_VIDEO, BTN_IDEA, BTN_PRICING, BTN_HELP

MENU_BUTTONS = {BTN_PROFILE, BTN_PHOTO, BTN_VIDEO, BTN_IDEA, BTN_PRICING, BTN_HELP}

# ---------------------------------------------------------------------------
# Файловый логгер (JSONL)
# ---------------------------------------------------------------------------

os.makedirs("logs", exist_ok=True)

_file_logger = logging.getLogger("user_actions")
_file_logger.setLevel(logging.INFO)
_file_logger.propagate = False  # не дублировать в основной лог

_fh = logging.FileHandler("logs/user_actions.jsonl", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(message)s"))
_file_logger.addHandler(_fh)


def _write_jsonl(record: dict):
    _file_logger.info(json.dumps(record, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Обработчики (запускаются в group=-1, не блокируют основные хендлеры)
# ---------------------------------------------------------------------------

async def log_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Логирует текстовые сообщения и команды."""
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text
    action_type = "command" if text.startswith("/") else "message"

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user_id": user.id,
        "username": user.username,
        "action": action_type,
        "content": text,
    }
    _write_jsonl(record)

    try:
        await log_user_action(user.id, user.username, action_type, text)
    except Exception as exc:
        logging.getLogger(__name__).warning("Не удалось записать action в БД: %s", exc)

    if text in MENU_BUTTONS:
        try:
            await update.message.delete()
        except Exception:
            pass


async def log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Логирует нажатия inline-кнопок."""
    if not update.callback_query:
        return

    user = update.effective_user
    data = update.callback_query.data

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user_id": user.id,
        "username": user.username,
        "action": "callback",
        "content": data,
    }
    _write_jsonl(record)

    try:
        await log_user_action(user.id, user.username, "callback", data)
    except Exception as exc:
        logging.getLogger(__name__).warning("Не удалось записать callback в БД: %s", exc)
