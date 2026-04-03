import asyncio

from telegram import Message, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

# Сколько символов добавляем за один шаг редактирования.
# При 4 символах и задержке 0.05с скорость ~80 симв/с,
# при этом правки идут раз в 0.05с — хорошо вписывается в rate limit Telegram.
_CHUNK = 4
_DELAY = 0.05


async def type_message(
    text: str,
    reply_to: Message,
    reply_markup=None,
) -> Message:
    """Отправляет сообщение с эффектом печатной машинки."""
    msg = await reply_to.reply_text("▌", reply_markup=reply_markup)

    full = ""
    for i, char in enumerate(text):
        full += char
        if (i + 1) % _CHUNK == 0 or i == len(text) - 1:
            display = full if i == len(text) - 1 else full + "▌"
            try:
                await msg.edit_text(display, reply_markup=reply_markup)
            except Exception:
                pass
            await asyncio.sleep(_DELAY)

    return msg


async def type_send(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup=None,
) -> Message:
    """Аналог context.bot.send_message с эффектом печатной машинки."""
    msg = await context.bot.send_message(chat_id=chat_id, text="▌")

    full = ""
    for i, char in enumerate(text):
        full += char
        if (i + 1) % _CHUNK == 0 or i == len(text) - 1:
            display = full if i == len(text) - 1 else full + "▌"
            try:
                await msg.edit_text(display, reply_markup=reply_markup)
            except Exception:
                pass
            await asyncio.sleep(_DELAY)

    return msg
