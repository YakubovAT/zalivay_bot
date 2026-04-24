"""
handlers/flows/messages/regen_reference.py

Тексты для Шага 16 (карточка эталона) и Шага 16а (пересоздание эталона).
"""

from services.prompt_store import get_template

async def msg_ref_card(ref_number: int, total: int, article: str, category: str) -> str:
    """Заголовок карточки эталона (Шаг 16)."""
    template = await get_template("msg_ref_card")
    return template.format(ref_number=ref_number, total=total, article=article, category=category)


async def msg_regen_wish(article: str, ref_number: int) -> str:
    """Шаг 16а — запрос пожеланий перед созданием."""
    template = await get_template("msg_regen_wish")
    return template.format(article=article, ref_number=ref_number)


async def msg_regen_generating(article: str) -> str:
    """Прогресс пересоздания."""
    template = await get_template("msg_regen_generating")
    return template.format(article=article)


async def msg_regen_result(
    article: str,
    ref_number: int,
    category: str,
    cost: int,
    balance: int,
) -> str:
    """Результат пересоздания (Шаг 16а — финал)."""
    template = await get_template("msg_regen_result")
    return template.format(article=article, ref_number=ref_number, category=category, cost=cost, balance=balance)


async def msg_regen_no_source_photos(article: str) -> str:
    """Ошибка — исходные фото не найдены на диске."""
    template = await get_template("msg_regen_no_source_photos")
    return template.format(article=article)
