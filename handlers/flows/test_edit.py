"""
handlers/flows/test_edit.py

Тестовый handler для проверки различия между edit и replace.
Команда: /test_edit
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

from handlers.flows.flow_helpers import replace_screen

_TEST_INIT, _TEST_EDIT, _TEST_REPLACE = range(3)

TEST_TEXT = """это сообщение для проверки того как бот ведет себя в режиме edit и replace, как появляется и удалется сообщение в интерфейче телеграм. Просто для проверки! Для простой такой проверки!"""


async def cmd_test_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /test_edit — показываем начальное сообщение."""
    text = TEST_TEXT + "\n\n✏️ edit edit edit"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Тест edit!", callback_data="test_edit_btn"),
            InlineKeyboardButton("Тест replace!", callback_data="test_replace_btn"),
        ],
    ])

    msg = await context.bot.send_message(
        chat_id=update.effective_user.id,
        text=text,
        reply_markup=keyboard,
    )

    context.user_data["test_msg_id"] = msg.message_id
    return _TEST_INIT


async def cb_test_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Нажата кнопка 'Тест edit!' — редактируем сообщение (edit_message_text)."""
    query = update.callback_query
    await query.answer()

    text = TEST_TEXT + "\n\n✏️ edit edit edit (ОТРЕДАКТИРОВАНО edit_message_text)"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Тест edit!", callback_data="test_edit_btn"),
            InlineKeyboardButton("Тест replace!", callback_data="test_replace_btn"),
        ],
    ])

    await query.edit_message_text(
        text=text,
        reply_markup=keyboard,
    )

    return _TEST_EDIT


async def cb_test_replace(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Нажата кнопка 'Тест replace!' — удаляем старое и создаём новое."""
    query = update.callback_query
    await query.answer()

    text = TEST_TEXT + "\n\n🗑️ replace replace replace (ПЕРЕДЕЛАНО replace_screen: удалено старое, создано новое)"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Тест edit!", callback_data="test_edit_btn"),
            InlineKeyboardButton("Тест replace!", callback_data="test_replace_btn"),
        ],
    ])

    await replace_screen(
        bot=context.bot,
        chat_id=query.from_user.id,
        old_message_id=query.message.message_id,
        text=text,
        keyboard=keyboard,
    )

    return _TEST_REPLACE


def build_test_edit_handler():
    """Собираем handler для тестирования."""
    return [
        CommandHandler("test_edit", cmd_test_edit),
        CallbackQueryHandler(cb_test_edit, pattern="^test_edit_btn$"),
        CallbackQueryHandler(cb_test_replace, pattern="^test_replace_btn$"),
    ]
