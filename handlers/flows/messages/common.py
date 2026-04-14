"""
handlers/flows/messages/common.py

Типовые сообщения для всех flow бота.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def kb_alert_close() -> InlineKeyboardMarkup:
    """Клавиатура для алерт-сообщений с кнопкой закрытия."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Закрыть", callback_data="alert_close")],
    ])


WEB_VIEWER_URL = "https://media.zaliv.ai"


def msg_generation_done(
    article: str,
    ref_number: int,
    total: int,
    actual_cost: int,
    new_balance: int,
    elapsed_str: str,
    job_id: int,
    failed: int = 0,
) -> str:
    """Результат генерации фото — 1 фото из N."""
    lines = [
        f"📸 <b>{total} из {total}</b> фото готовы для <code>{article}</code>",
        f"Тут представлен один из вариантов, все ваши генерации хранятся здесь:",
        f"🖼 {WEB_VIEWER_URL}",
        "",
        f"📦 Эталон: #{ref_number}",
        f"💰 Списано: {actual_cost}₽",
        f"💳 Остаток: {new_balance}₽",
        f"⏱ Время: {elapsed_str}",
        f"🆔 Задание #{job_id}",
    ]
    if failed:
        lines.append(f"⚠️ Не удалось: {failed} из {failed + total}")
    return "\n".join(lines)


def msg_generation_failed(job_id: int) -> str:
    """Ошибка генерации — ни одного фото не вышло."""
    return (
        "❌ Не удалось сгенерировать фото.\n\n"
        "С вашего баланса ничего не списано.\n\n"
        f"🆔 Задание #{job_id}\n\n"
        "При обращении в поддержку укажите номер задания."
    )


def msg_insufficient_funds(needed: int, balance: int, purpose: str = "") -> str:
    """Недостаточно средств."""
    if purpose:
        return (
            f"❌ Недостаточно средств.\n\n"
            f"💰 {purpose}: {needed}₽\n"
            f"💳 Ваш баланс: {balance}₽\n\n"
            f"Пополните баланс и попробуйте снова."
        )
    return (
        f"❌ Недостаточно средств.\n\n"
        f"💰 Нужно: {needed}₽\n"
        f"💳 Ваш баланс: {balance}₽\n\n"
        f"Пополните баланс и попробуйте снова."
    )
