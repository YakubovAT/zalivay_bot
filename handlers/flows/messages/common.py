"""
handlers/flows/messages/common.py

Типовые сообщения для всех flow бота.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from services.prompt_store import get_template


def kb_alert_close() -> InlineKeyboardMarkup:
    """Клавиатура для алерт-сообщений с кнопкой закрытия."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Закрыть", callback_data="alert_close")],
    ])


WEB_VIEWER_URL = "https://media.zaliv.ai"

_PROFILE_TEXT_FALLBACK = (
    "Шаг 2: Профиль\n\n"
    "👤 *Профиль:*\n"
    "> • ID: `{user_id}`\n"
    "> • Имя: {full_name}\n\n"
    "📊 *Статистика:*\n"
    "> • Товаров: {articles}\n"
    "> • Эталонов: {references}\n"
    "> • Фото: {photos}\n"
    "> • Видео: {videos}\n"
    "> • Баланс: {balance}₽"
)


def _escape_md_v2(text: str) -> str:
    """Экранирует спецсимволы MarkdownV2."""
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, f'\\{ch}')
    return text


async def msg_profile(user_id: int, full_name: str | None, stats: dict) -> str:
    """Шаг 2: профиль пользователя (MarkdownV2)."""
    template = await get_template("msg_profile", fallback=_PROFILE_TEXT_FALLBACK)
    return template.format(
        user_id=_escape_md_v2(str(user_id)),
        full_name=_escape_md_v2(full_name or "—"),
        articles=_escape_md_v2(str(stats.get("articles", 0))),
        references=_escape_md_v2(str(stats.get("references", 0))),
        photos=_escape_md_v2(str(stats.get("photos", 0))),
        videos=_escape_md_v2(str(stats.get("videos", 0))),
        balance=_escape_md_v2(str(stats.get("balance", 0))),
    )


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


def msg_video_generation_done(
    article: str,
    ref_number: int,
    total: int,
    actual_cost: int,
    new_balance: int,
    elapsed_str: str,
    job_id: int,
    failed: int = 0,
) -> str:
    """Результат генерации видео."""
    lines = [
        f"🎥 <b>{total} из {total}</b> видео готовы для <code>{article}</code>",
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


def msg_video_generation_failed(job_id: int) -> str:
    """Ошибка генерации видео — ни одного не вышло."""
    return (
        "❌ Не удалось сгенерировать видео.\n\n"
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
