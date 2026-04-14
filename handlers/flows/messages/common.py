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
