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


def _escape_md_v2(text: str) -> str:
    """Экранирует спецсимволы MarkdownV2."""
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, f'\\{ch}')
    return text


async def msg_profile(user_id: int, full_name: str | None, stats: dict) -> str:
    """Шаг 2: профиль пользователя (MarkdownV2)."""
    template = await get_template("msg_profile")
    return template.format(
        user_id=_escape_md_v2(str(user_id)),
        full_name=_escape_md_v2(full_name or "—"),
        articles=_escape_md_v2(str(stats.get("articles", 0))),
        references=_escape_md_v2(str(stats.get("references", 0))),
        photos=_escape_md_v2(str(stats.get("photos", 0))),
        videos=_escape_md_v2(str(stats.get("videos", 0))),
        balance=_escape_md_v2(str(stats.get("balance", 0))),
    )


async def msg_generation_done(
    article: str,
    ref_number: int,
    total: int,
    actual_cost: int,
    new_balance: int,
    elapsed_str: str,
    job_id: int,
    failed: int = 0,
) -> str:
    """Результат создания фото — 1 фото из N."""
    template = await get_template("msg_generation_done")
    lines = [template.format(
        article=article,
        ref_number=ref_number,
        total=total,
        actual_cost=actual_cost,
        new_balance=new_balance,
        elapsed_str=elapsed_str,
        job_id=job_id,
        web_viewer_url=WEB_VIEWER_URL,
    )]
    if failed:
        failed_line = await get_template("msg_generation_done_failed_line")
        lines.append(failed_line.format(failed=failed, requested=failed + total))
    return "\n".join(lines)


async def msg_generation_failed(job_id: int) -> str:
    """Ошибка создания — ни одного фото не вышло."""
    template = await get_template("msg_generation_failed")
    return template.format(job_id=job_id)


async def msg_video_generation_done(
    article: str,
    ref_number: int,
    total: int,
    actual_cost: int,
    new_balance: int,
    elapsed_str: str,
    job_id: int,
    failed: int = 0,
) -> str:
    """Результат создания видео."""
    template = await get_template("msg_video_generation_done")
    lines = [template.format(
        article=article,
        ref_number=ref_number,
        total=total,
        actual_cost=actual_cost,
        new_balance=new_balance,
        elapsed_str=elapsed_str,
        job_id=job_id,
        web_viewer_url=WEB_VIEWER_URL,
    )]
    if failed:
        failed_line = await get_template("msg_video_generation_done_failed_line")
        lines.append(failed_line.format(failed=failed, requested=failed + total))
    return "\n".join(lines)


async def msg_video_generation_failed(job_id: int) -> str:
    """Ошибка создания видео — ни одного не вышло."""
    template = await get_template("msg_video_generation_failed")
    return template.format(job_id=job_id)


async def msg_insufficient_funds(needed: int, balance: int, purpose: str = "") -> str:
    """Недостаточно средств."""
    if purpose:
        template = await get_template("msg_insufficient_funds_with_purpose")
        return template.format(needed=needed, balance=balance, purpose=purpose)
    template = await get_template("msg_insufficient_funds")
    return template.format(needed=needed, balance=balance)
