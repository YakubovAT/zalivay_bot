"""
handlers/flows/messages/watermark.py

Тексты flow /watermark (нанесение watermark на фото).
"""

from services.prompt_store import get_template

_MSG_WATERMARK_ALL_DONE_FALLBACK = (
    "Все ваши фото уже обработаны — артикул и название нанесены."
)


async def msg_watermark_all_done() -> str:
    return await get_template("msg_watermark_all_done", fallback=_MSG_WATERMARK_ALL_DONE_FALLBACK)


_MSG_WATERMARK_CONFIRM_FALLBACK = (
    "Фото без текста: {count}\n\n"
    "На каждое фото будет нанесено:\n"
    "• артикул товара (по диагонали)\n"
    "• название товара (по диагонали)\n\n"
    "Оригиналы остаются без изменений."
)


async def msg_watermark_confirm(count: int) -> str:
    template = await get_template("msg_watermark_confirm", fallback=_MSG_WATERMARK_CONFIRM_FALLBACK)
    return template.format(count=count)


_MSG_WATERMARK_PROCESSING_FALLBACK = "Наношу текст на фото…"


async def msg_watermark_processing() -> str:
    return await get_template("msg_watermark_processing", fallback=_MSG_WATERMARK_PROCESSING_FALLBACK)


_MSG_WATERMARK_DONE_FALLBACK = "Готово! Обработано фото: {done}"


async def msg_watermark_done(done: int) -> str:
    template = await get_template("msg_watermark_done", fallback=_MSG_WATERMARK_DONE_FALLBACK)
    return template.format(done=done)


_MSG_WATERMARK_FAILED_LINE_FALLBACK = "Не удалось обработать: {failed}"


async def msg_watermark_failed_line(failed: int) -> str:
    template = await get_template("msg_watermark_failed_line", fallback=_MSG_WATERMARK_FAILED_LINE_FALLBACK)
    return template.format(failed=failed)


_MSG_WATERMARK_CANCEL_FALLBACK = "Отменено."


async def msg_watermark_cancel() -> str:
    return await get_template("msg_watermark_cancel", fallback=_MSG_WATERMARK_CANCEL_FALLBACK)
