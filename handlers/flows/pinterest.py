"""
handlers/flows/pinterest.py

Flow команды /pinterest — генерация CSV для загрузки в Pinterest.

Шаги:
  1. /pinterest — проверяет баланс, спрашивает кол-во строк (10-200)
  2. Пользователь вводит число
  3. Проверяем кол-во доступных файлов и баланс
     - Достаточно файлов и баланса → показываем стоимость, кнопка [Подтвердить / Отмена]
     - Файлов меньше → предлагаем кол-во по файлам
     - Баланса не хватает → сообщаем сколько строк можно позволить
  4. Пользователь подтверждает → генерируем CSV → списываем баланс → отправляем файл
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

from config import PINTEREST_CSV_COST
from database.db import get_all_unexported_media_files, get_user_stats, deduct_balance
from handlers.flows.messages.pinterest import (
    msg_pinterest_no_files,
    msg_pinterest_ask_count,
    msg_pinterest_invalid_input,
    msg_pinterest_out_of_range,
    msg_pinterest_insufficient_funds,
    msg_pinterest_balance_low,
    msg_pinterest_fewer_files,
    msg_pinterest_confirm,
    msg_pinterest_cancel,
    msg_pinterest_generating,
    msg_pinterest_no_result,
    msg_pinterest_done,
    msg_pinterest_errors_line,
)
from services.pinterest_csv_generator import generate_pinterest_csv

logger = logging.getLogger(__name__)

_ASK_COUNT, _CONFIRM = range(2)

_CTX_COUNT     = "pinterest_count"
_CTX_AVAILABLE = "pinterest_available"
_CTX_COST      = "pinterest_cost"


async def cmd_pinterest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Точка входа: /pinterest."""
    user_id = update.effective_user.id

    all_files = await get_all_unexported_media_files(user_id)
    if not all_files:
        await update.message.reply_text(await msg_pinterest_no_files())
        return ConversationHandler.END

    stats = await get_user_stats(user_id)
    balance = stats["balance"]
    available = len(all_files)
    context.user_data[_CTX_AVAILABLE] = available

    max_affordable = balance // PINTEREST_CSV_COST

    await update.message.reply_text(
        await msg_pinterest_ask_count(available, balance, min(max_affordable, 100), PINTEREST_CSV_COST)
    )
    return _ASK_COUNT


async def on_count_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь ввёл количество строк."""
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text(await msg_pinterest_invalid_input())
        return _ASK_COUNT

    requested = int(text)
    if requested < 10 or requested > 100:
        await update.message.reply_text(await msg_pinterest_out_of_range())
        return _ASK_COUNT

    available = context.user_data.get(_CTX_AVAILABLE, 0)
    stats = await get_user_stats(update.effective_user.id)
    balance = stats["balance"]

    # Итоговое количество строк с учётом файлов
    count = min(requested, available)
    cost  = count * PINTEREST_CSV_COST

    # Недостаточно баланса
    if balance < cost:
        affordable = balance // PINTEREST_CSV_COST
        if affordable < 10:
            await update.message.reply_text(
                await msg_pinterest_insufficient_funds(balance, affordable)
            )
            return ConversationHandler.END

        affordable_cost = affordable * PINTEREST_CSV_COST
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"Создать {affordable} строк ({affordable_cost} руб.)", callback_data="pinterest_confirm"),
            InlineKeyboardButton("Отмена", callback_data="pinterest_cancel"),
        ]])
        context.user_data[_CTX_COUNT] = affordable
        context.user_data[_CTX_COST]  = affordable_cost
        await update.message.reply_text(
            await msg_pinterest_balance_low(balance, count, cost, affordable, affordable_cost),
            reply_markup=keyboard,
        )
        return _CONFIRM

    # Файлов меньше чем запрошено
    if available < requested:
        cost = available * PINTEREST_CSV_COST
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"Создать {available} строк ({cost} руб.)", callback_data="pinterest_confirm"),
            InlineKeyboardButton("Отмена", callback_data="pinterest_cancel"),
        ]])
        context.user_data[_CTX_COUNT] = available
        context.user_data[_CTX_COST]  = cost
        await update.message.reply_text(
            await msg_pinterest_fewer_files(available, requested, cost),
            reply_markup=keyboard,
        )
        return _CONFIRM

    # Всё в порядке — показываем подтверждение
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"Создать {count} строк ({cost} руб.)", callback_data="pinterest_confirm"),
        InlineKeyboardButton("Отмена", callback_data="pinterest_cancel"),
    ]])
    context.user_data[_CTX_COUNT] = count
    context.user_data[_CTX_COST]  = cost
    await update.message.reply_text(
        await msg_pinterest_confirm(balance, cost, count, balance - cost),
        reply_markup=keyboard,
    )
    return _CONFIRM


async def cb_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь подтвердил генерацию."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()

    count = context.user_data.get(_CTX_COUNT, 0)
    return await _do_generate(update, context, count)


async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь отменил генерацию."""
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(await msg_pinterest_cancel())
    _clear(context)
    return ConversationHandler.END


async def _do_generate(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    count: int,
) -> int:
    """Запускает генерацию, списывает баланс, отправляет CSV."""
    user_id = update.effective_user.id
    msg = update.effective_message

    status_msg = await msg.reply_text(await msg_pinterest_generating(count))

    result = await generate_pinterest_csv(user_id, count)

    generated = result["stats"]["count"]
    errors    = result["stats"]["errors"]

    if generated == 0:
        no_result_text = await msg_pinterest_no_result()
        if errors:
            no_result_text += "\n" + "\n".join(errors)
        await status_msg.edit_text(no_result_text)
        _clear(context)
        return ConversationHandler.END

    # Списываем за фактически сгенерированные строки
    actual_cost = generated * PINTEREST_CSV_COST
    new_balance = await deduct_balance(user_id, actual_cost)

    logger.info("PINTEREST | user=%d | rows=%d | cost=%d | balance=%d", user_id, generated, actual_cost, new_balance)

    csv_bytes = result["content"].encode("utf-8")
    filename  = f"pinterest_{result['batch_id']}.csv"

    caption = await msg_pinterest_done(generated, actual_cost, new_balance)
    if errors:
        caption += "\n" + await msg_pinterest_errors_line(len(errors))

    await status_msg.delete()
    await msg.reply_document(
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption=caption,
    )

    _clear(context)
    return ConversationHandler.END


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (_CTX_COUNT, _CTX_AVAILABLE, _CTX_COST):
        context.user_data.pop(key, None)


def build_pinterest_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("pinterest", cmd_pinterest)],
        states={
            _ASK_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_count_input),
            ],
            _CONFIRM: [
                CallbackQueryHandler(cb_confirm, pattern="^pinterest_confirm$"),
                CallbackQueryHandler(cb_cancel,  pattern="^pinterest_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("pinterest", cmd_pinterest)],
        name="pinterest_flow",
        persistent=False,
    )
