"""
handlers/flows/messages/regen_reference.py

Тексты для Шага 16 (карточка эталона) и Шага 16а (перегенерация эталона).
"""


def msg_ref_card(ref_number: int, total: int, article: str, category: str) -> str:
    """Заголовок карточки эталона (Шаг 16)."""
    return (
        f"📸 Шаг 16: Эталон #{ref_number} из {total}\n"
        f"📦 Артикул: <code>{article}</code>\n"
        f"🏷 Тип товара: {category}"
    )


def msg_regen_wish(article: str, ref_number: int) -> str:
    """Шаг 16а — запрос пожеланий перед перегенерацией."""
    return (
        f"🔄 Шаг 16а: Перегенерация эталона\n\n"
        f"📦 Артикул: <code>{article}</code>\n"
        f"📸 Эталон: #{ref_number}\n\n"
        f"Будут использованы те же 3 фотографии, что и при создании.\n\n"
        f"Если хотите скорректировать результат — опишите, что не так "
        f"(например: <i>убери фон, товар должен быть по центру</i>).\n\n"
        f"Или нажмите <b>Пропустить</b> — эталон перегенерируется с теми же настройками."
    )


def msg_regen_generating(article: str) -> str:
    """Прогресс перегенерации."""
    return (
        f"⏳ Перегенерирую эталон для артикула <code>{article}</code>...\n\n"
        f"Это займёт 1–3 минуты..."
    )


def msg_regen_result(
    article: str,
    ref_number: int,
    category: str,
    cost: int,
    balance: int,
) -> str:
    """Результат перегенерации (Шаг 16а — финал)."""
    return (
        f"✅ Шаг 16а: Новый эталон готов!\n\n"
        f"📦 Артикул: <code>{article}</code>\n"
        f"📸 Эталон #{ref_number}\n"
        f"🏷 Тип товара: {category}\n\n"
        f"💰 Списано: {cost}₽\n"
        f"💳 Ваш баланс: {balance}₽\n\n"
        f"Теперь вы можете генерировать фото и видео!"
    )


def msg_regen_no_source_photos(article: str) -> str:
    """Ошибка — исходные фото не найдены на диске."""
    return (
        f"❌ Исходные фотографии для артикула <code>{article}</code> не найдены.\n\n"
        f"Возможно, файлы были удалены с сервера. "
        f"Создайте новый эталон через «➕ Новый эталон»."
    )
