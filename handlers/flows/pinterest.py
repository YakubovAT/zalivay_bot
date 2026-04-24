"""
handlers/flows/pinterest.py

Flow команды /pinterest — генерация CSV для загрузки в Pinterest.

Шаги:
  1. /pinterest — спрашивает желаемое количество строк (10-200)
  2. Пользователь вводит число
  3. Проверяем количество доступных файлов
     - Достаточно → генерируем CSV с рандомной выборкой → отправляем файл
     - Недостаточно → сообщаем сколько есть, предлагаем кнопки [Создать с X файлами / Отмена]
"""

from __future__ import annotations

import io
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database.db import get_all_unexported_media_files
from services.pinterest_csv_generator import generate_pinterest_csv

logger = logging.getLogger(__name__)

_ASK_COUNT, _CONFIRM_LOW = range(2)

_CTX_REQUESTED = "pinterest_requested"
_CTX_AVAILABLE = "pinterest_available"


async def cmd_pinterest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Точка входа: /pinterest — спрашиваем желаемое количество строк."""
    user_id = update.effective_user.id

    all_files = await get_all_unexported_media_files(user_id)
    if not all_files:
        await update.message.reply_text(
            "У вас нет новых медиафайлов для экспорта в Pinterest.\n"
            "Сначала создайте фото или видео для ваших товаров."
        )
        return ConversationHandler.END

    context.user_data[_CTX_AVAILABLE] = len(all_files)

    await update.message.reply_text(
        f"Сколько строк сгенерировать для Pinterest CSV?\n"
        f"Введите число от 10 до 200.\n\n"
        f"Доступно файлов: {len(all_files)}"
    )
    return _ASK_COUNT


async def on_count_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл количество строк."""
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text("Пожалуйста, введите число от 10 до 200.")
        return _ASK_COUNT

    requested = int(text)
    if requested < 10 or requested > 200:
        await update.message.reply_text("Число должно быть от 10 до 200. Попробуйте ещё раз.")
        return _ASK_COUNT

    available = context.user_data.get(_CTX_AVAILABLE, 0)
    context.user_data[_CTX_REQUESTED] = requested

    if available >= requested:
        return await _do_generate(update, context, requested)

    # Файлов меньше чем запрошено
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"Создать с {available} файлами", callback_data="pinterest_use_available"),
            InlineKeyboardButton("Отмена", callback_data="pinterest_cancel"),
        ]
    ])
    await update.message.reply_text(
        f"У вас только {available} необработанных файлов, а вы запросили {requested}.\n\n"
        f"Хотите создать CSV с {available} строками?",
        reply_markup=keyboard,
    )
    return _CONFIRM_LOW


async def cb_use_available(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь согласился генерировать с доступным количеством."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()

    available = context.user_data.get(_CTX_AVAILABLE, 0)
    return await _do_generate(update, context, available)


async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь отменил генерацию."""
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Генерация отменена.")
    context.user_data.pop(_CTX_REQUESTED, None)
    context.user_data.pop(_CTX_AVAILABLE, None)
    return ConversationHandler.END


async def _do_generate(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    count: int,
) -> int:
    """Запускает генерацию и отправляет CSV файл."""
    user_id = update.effective_user.id
    msg = update.effective_message

    status_msg = await msg.reply_text(f"Генерирую Pinterest CSV ({count} строк)…")

    result = await generate_pinterest_csv(user_id, count)

    generated = result["stats"]["count"]
    errors = result["stats"]["errors"]

    if generated == 0:
        await status_msg.edit_text(
            "Не удалось сгенерировать строки.\n"
            + ("\n".join(errors) if errors else "Нет данных для экспорта.")
        )
        return ConversationHandler.END

    csv_bytes = result["content"].encode("utf-8")
    filename = f"pinterest_{result['batch_id']}.csv"

    caption_lines = [f"Pinterest CSV готов — {generated} строк"]
    if errors:
        caption_lines.append(f"Ошибок: {len(errors)}")

    await status_msg.delete()
    await msg.reply_document(
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption="\n".join(caption_lines),
    )

    context.user_data.pop(_CTX_REQUESTED, None)
    context.user_data.pop(_CTX_AVAILABLE, None)
    return ConversationHandler.END


def build_pinterest_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("pinterest", cmd_pinterest)],
        states={
            _ASK_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_count_input),
            ],
            _CONFIRM_LOW: [
                CallbackQueryHandler(cb_use_available, pattern="^pinterest_use_available$"),
                CallbackQueryHandler(cb_cancel, pattern="^pinterest_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("pinterest", cmd_pinterest)],
        name="pinterest_flow",
        persistent=False,
    )
