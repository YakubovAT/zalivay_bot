"""
handlers/flows/messages/pinterest.py

Тексты flow /pinterest (генерация CSV для Pinterest).
"""

from services.prompt_store import get_template

_MSG_PINTEREST_NO_FILES_FALLBACK = (
    "У вас нет медиафайлов для экспорта в Pinterest.\n"
    "Сначала создайте фото или видео для ваших товаров."
)


async def msg_pinterest_no_files() -> str:
    return await get_template("msg_pinterest_no_files", fallback=_MSG_PINTEREST_NO_FILES_FALLBACK)


_MSG_PINTEREST_ASK_COUNT_FALLBACK = (
    "Сколько строк сгенерировать для Pinterest CSV?\n"
    "Введите число от 10 до 200.\n\n"
    "Доступно файлов: {available}\n"
    "Баланс: {balance} руб. (до {max_rows} строк)\n"
    "Стоимость: {cost_per_row} руб./строка"
)


async def msg_pinterest_ask_count(available: int, balance: int, max_rows: int, cost_per_row: int) -> str:
    template = await get_template("msg_pinterest_ask_count", fallback=_MSG_PINTEREST_ASK_COUNT_FALLBACK)
    return template.format(available=available, balance=balance, max_rows=max_rows, cost_per_row=cost_per_row)


_MSG_PINTEREST_INVALID_INPUT_FALLBACK = "Пожалуйста, введите число от 10 до 200."


async def msg_pinterest_invalid_input() -> str:
    return await get_template("msg_pinterest_invalid_input", fallback=_MSG_PINTEREST_INVALID_INPUT_FALLBACK)


_MSG_PINTEREST_OUT_OF_RANGE_FALLBACK = "Число должно быть от 10 до 200. Попробуйте ещё раз."


async def msg_pinterest_out_of_range() -> str:
    return await get_template("msg_pinterest_out_of_range", fallback=_MSG_PINTEREST_OUT_OF_RANGE_FALLBACK)


_MSG_PINTEREST_INSUFFICIENT_FUNDS_FALLBACK = (
    "Недостаточно средств.\n"
    "Ваш баланс: {balance} руб. — хватает на {affordable} строк (минимум 10).\n"
    "Пополните баланс и попробуйте снова."
)


async def msg_pinterest_insufficient_funds(balance: int, affordable: int) -> str:
    template = await get_template("msg_pinterest_insufficient_funds", fallback=_MSG_PINTEREST_INSUFFICIENT_FUNDS_FALLBACK)
    return template.format(balance=balance, affordable=affordable)


_MSG_PINTEREST_BALANCE_LOW_FALLBACK = (
    "Баланс: {balance} руб. — не хватает на {count} строк ({cost} руб.).\n"
    "Можно создать {affordable} строк за {affordable_cost} руб."
)


async def msg_pinterest_balance_low(balance: int, count: int, cost: int, affordable: int, affordable_cost: int) -> str:
    template = await get_template("msg_pinterest_balance_low", fallback=_MSG_PINTEREST_BALANCE_LOW_FALLBACK)
    return template.format(balance=balance, count=count, cost=cost, affordable=affordable, affordable_cost=affordable_cost)


_MSG_PINTEREST_FEWER_FILES_FALLBACK = (
    "У вас {available} файлов, а вы запросили {requested}.\n"
    "Создать CSV с {available} строками за {cost} руб.?"
)


async def msg_pinterest_fewer_files(available: int, requested: int, cost: int) -> str:
    template = await get_template("msg_pinterest_fewer_files", fallback=_MSG_PINTEREST_FEWER_FILES_FALLBACK)
    return template.format(available=available, requested=requested, cost=cost)


_MSG_PINTEREST_CONFIRM_FALLBACK = (
    "Баланс: {balance} руб.\n"
    "Будет списано: {cost} руб. за {count} строк.\n"
    "Остаток после: {after} руб."
)


async def msg_pinterest_confirm(balance: int, cost: int, count: int, after: int) -> str:
    template = await get_template("msg_pinterest_confirm", fallback=_MSG_PINTEREST_CONFIRM_FALLBACK)
    return template.format(balance=balance, cost=cost, count=count, after=after)


_MSG_PINTEREST_CANCEL_FALLBACK = "Генерация отменена."


async def msg_pinterest_cancel() -> str:
    return await get_template("msg_pinterest_cancel", fallback=_MSG_PINTEREST_CANCEL_FALLBACK)


_MSG_PINTEREST_GENERATING_FALLBACK = "Генерирую Pinterest CSV ({count} строк)…"


async def msg_pinterest_generating(count: int) -> str:
    template = await get_template("msg_pinterest_generating", fallback=_MSG_PINTEREST_GENERATING_FALLBACK)
    return template.format(count=count)


_MSG_PINTEREST_NO_RESULT_FALLBACK = "Не удалось сгенерировать строки."


async def msg_pinterest_no_result() -> str:
    return await get_template("msg_pinterest_no_result", fallback=_MSG_PINTEREST_NO_RESULT_FALLBACK)


_MSG_PINTEREST_DONE_FALLBACK = (
    "Pinterest CSV готов — {count} строк\n"
    "Списано: {cost} руб. | Баланс: {balance} руб."
)


async def msg_pinterest_done(count: int, cost: int, balance: int) -> str:
    template = await get_template("msg_pinterest_done", fallback=_MSG_PINTEREST_DONE_FALLBACK)
    return template.format(count=count, cost=cost, balance=balance)


_MSG_PINTEREST_ERRORS_LINE_FALLBACK = "Ошибок: {errors_count}"


async def msg_pinterest_errors_line(errors_count: int) -> str:
    template = await get_template("msg_pinterest_errors_line", fallback=_MSG_PINTEREST_ERRORS_LINE_FALLBACK)
    return template.format(errors_count=errors_count)
