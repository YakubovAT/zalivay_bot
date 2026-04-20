"""
handlers/flows/messages/regen_reference.py

Тексты для Шага 16 (карточка эталона) и Шага 16а (пересоздание эталона).
"""

from services.prompt_store import get_template

_MSG_REF_CARD_FALLBACK = (
    "📸 Шаг 16: Эталон #{ref_number} из {total}\n"
    "📦 Артикул: <code>{article}</code>\n"
    "🏷 Тип товара: {category}"
)


async def msg_ref_card(ref_number: int, total: int, article: str, category: str) -> str:
    """Заголовок карточки эталона (Шаг 16)."""
    template = await get_template("msg_ref_card", fallback=_MSG_REF_CARD_FALLBACK)
    return template.format(ref_number=ref_number, total=total, article=article, category=category)


def msg_regen_wish(article: str, ref_number: int) -> str:
    """Шаг 16а — запрос пожеланий перед созданием."""
    return (
        f"🔄 Шаг 16а: Пересоздание эталона\n\n"
        f"📦 Артикул: <code>{article}</code>\n"
        f"📸 Эталон: #{ref_number}\n\n"
        f"Будут использованы те же 3 фотографии, что и при создании.\n\n"
        f"Если хотите скорректировать результат — опишите, что не так "
        f"(например: <i>убери фон, товар должен быть по центру</i>).\n\n"
        f"Или нажмите <b>Пропустить</b> — эталон пересоздастся с теми же настройками."
    )


def msg_regen_generating(article: str) -> str:
    """Прогресс пересоздания."""
    return (
        f"⏳ Пересоздаю эталон для артикула <code>{article}</code>...\n\n"
        f"Это займёт 1–3 минуты..."
    )


def msg_regen_result(
    article: str,
    ref_number: int,
    category: str,
    cost: int,
    balance: int,
) -> str:
    """Результат пересоздания (Шаг 16а — финал)."""
    return (
        f"✅ Шаг 16а: Новый эталон готов!\n\n"
        f"📦 Артикул: <code>{article}</code>\n"
        f"📸 Эталон #{ref_number}\n"
        f"🏷 Тип товара: {category}\n\n"
        f"💰 Списано: {cost}₽\n"
        f"💳 Ваш баланс: {balance}₽\n\n"
        f"Теперь вы можете создавать фото и видео!"
    )


def msg_regen_no_source_photos(article: str) -> str:
    """Ошибка — исходные фото не найдены на диске."""
    return (
        f"❌ Исходные фотографии для артикула <code>{article}</code> не найдены.\n\n"
        f"Возможно, файлы были удалены с сервера. "
        f"Создайте новый эталон через «➕ Новый эталон»."
    )
