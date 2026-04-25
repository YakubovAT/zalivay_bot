"""
handlers/flows/pinterest_admin.py

Секретная команда /pinterest2 — генерация CSV только для артикула 00000.
Доступна только администраторам (ADMIN_USER_IDS в .env).
Баланс не проверяется и не списывается.

Flow:
  1. /pinterest2 → проверка прав, показ кол-ва доступных файлов
  2. Ввод количества строк (1–500)
  3. Генерация и отправка CSV
"""

from __future__ import annotations

import io
import logging
import os

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from services.pinterest_csv_generator import generate_pinterest_csv
from database.db import get_all_unexported_media_files

logger = logging.getLogger(__name__)

_ADMIN_IDS: frozenset[int] = frozenset(
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()
)

_ARTICLE_CODE = "00000"
_USER_ID      = 171470918
_MAX_COUNT    = 500

_CTX_AVAILABLE = "p2_available"
_WAIT_COUNT    = 0


async def cmd_pinterest2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in _ADMIN_IDS:
        return ConversationHandler.END

    all_files = await get_all_unexported_media_files(_USER_ID)
    available = len([f for f in all_files if f["article_code"] == _ARTICLE_CODE])
    context.user_data[_CTX_AVAILABLE] = available

    if available == 0:
        await update.message.reply_text(
            f"❌ Нет файлов для артикула {_ARTICLE_CODE}.\n"
            "Сначала запусти генерацию через /08111981"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"📊 Pinterest CSV — артикул {_ARTICLE_CODE}\n\n"
        f"Доступно файлов: {available}\n\n"
        f"Сколько строк сгенерировать? (1–{min(available, _MAX_COUNT)})"
    )
    return _WAIT_COUNT


async def on_count_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    available = context.user_data.get(_CTX_AVAILABLE, 0)

    if not text.isdigit():
        await update.message.reply_text("Введи число, например: 50")
        return _WAIT_COUNT

    count = int(text)
    if count < 1 or count > _MAX_COUNT:
        await update.message.reply_text(f"Число должно быть от 1 до {_MAX_COUNT}")
        return _WAIT_COUNT

    count = min(count, available)

    status = await update.message.reply_text(f"⏳ Генерирую CSV ({count} строк)...")

    result = await generate_pinterest_csv(
        user_id=_USER_ID,
        rows_count=count,
        article_code_filter=_ARTICLE_CODE,
    )

    generated = result["stats"]["count"]
    errors    = result["stats"]["errors"]

    if generated == 0:
        await status.edit_text("❌ Не удалось сгенерировать CSV.\n" + "\n".join(errors))
        context.user_data.pop(_CTX_AVAILABLE, None)
        return ConversationHandler.END

    csv_bytes = result["content"].encode("utf-8")
    filename  = f"pinterest_{_ARTICLE_CODE}_{result['batch_id']}.csv"
    caption   = f"✅ Готово! Строк: {generated}"
    if errors:
        caption += f"\n⚠️ Ошибок: {len(errors)}"

    await status.delete()
    await update.message.reply_document(
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption=caption,
    )

    context.user_data.pop(_CTX_AVAILABLE, None)
    return ConversationHandler.END


def build_pinterest_admin_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("pinterest2", cmd_pinterest2)],
        states={
            _WAIT_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_count_input)],
        },
        fallbacks=[CommandHandler("pinterest2", cmd_pinterest2)],
        name="pinterest_admin_flow",
        persistent=False,
    )
