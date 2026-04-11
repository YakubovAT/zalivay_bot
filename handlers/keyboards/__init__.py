"""
keyboard_builder.py

Единый источник всех клавиатур бота.
ReplyKeyboardMarkup — главное меню (внизу экрана).
InlineKeyboardMarkup — интерактивные кнопки внутри сообщений.
"""

from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup

# ---------------------------------------------------------------------------
# Кнопки главного меню (Reply)
# ---------------------------------------------------------------------------

BTN_PROFILE = "Профиль"
BTN_PHOTO = "Фото"
BTN_VIDEO = "Видео"
BTN_ETALON = "Эталон товара"
BTN_PRICING = "Прайс"
BTN_HELP = "Помощь"
BTN_RESTART = "Перезапуск"


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню — 3 колонки + перезапуск."""
    keyboard = [
        [KeyboardButton(BTN_ETALON), KeyboardButton(BTN_PHOTO), KeyboardButton(BTN_VIDEO)],
        [KeyboardButton(BTN_PROFILE), KeyboardButton(BTN_PRICING), KeyboardButton(BTN_HELP)],
        [KeyboardButton(BTN_RESTART)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def main_menu_inline() -> InlineKeyboardMarkup:
    """Главное меню в inline-формате (для edit_message_reply_markup)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(BTN_ETALON, callback_data=f"menu_{BTN_ETALON}"),
            InlineKeyboardButton(BTN_PHOTO, callback_data=f"menu_{BTN_PHOTO}"),
            InlineKeyboardButton(BTN_VIDEO, callback_data=f"menu_{BTN_VIDEO}"),
        ],
        [
            InlineKeyboardButton(BTN_PROFILE, callback_data=f"menu_{BTN_PROFILE}"),
            InlineKeyboardButton(BTN_PRICING, callback_data=f"menu_{BTN_PRICING}"),
            InlineKeyboardButton(BTN_HELP, callback_data=f"menu_{BTN_HELP}"),
        ],
    ])


def back_button(label: str = "↩️ Назад", callback_data: str = "back") -> InlineKeyboardMarkup:
    """Универсальная кнопка «Назад»."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=callback_data)]])


def back_to_menu_button() -> InlineKeyboardMarkup:
    """Кнопка «В главное меню»."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_menu")]])


def mp_select_keyboard() -> InlineKeyboardMarkup:
    """Выбор маркетплейса."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟣 Wildberries", callback_data="mp_wb"),
            InlineKeyboardButton("🔵 OZON", callback_data="mp_ozon"),
        ]
    ])


def etalon_create_keyboard() -> InlineKeyboardMarkup:
    """Создать эталон / другой артикул."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Создать эталон", callback_data="create_ref")],
        [InlineKeyboardButton("🔄 Ввести другой артикул", callback_data="new_article")],
    ])


def etalon_feedback_keyboard() -> InlineKeyboardMarkup:
    """✅ Подходит / 🔄 Переделать."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подходит", callback_data="ref_ok")],
        [InlineKeyboardButton("🔄 Переделать", callback_data="ref_redo")],
    ])


def etalon_feedback_with_continue_keyboard() -> InlineKeyboardMarkup:
    """✅ Подходит, создать фото / 🔄 Переделать."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подходит, создать фото", callback_data="ref_ok_continue")],
        [InlineKeyboardButton("🔄 Переделать эталон", callback_data="ref_redo")],
    ])


def photo_count_keyboard() -> InlineKeyboardMarkup:
    """Выбор количества фото."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Одно фото", callback_data="photo_one")],
        [InlineKeyboardButton("📸 Несколько фото", callback_data="photo_multi")],
        [InlineKeyboardButton("↩️ Назад", callback_data="photo_back")],
    ])


def etalon_existing_keyboard() -> InlineKeyboardMarkup:
    """Эталон уже есть — переделать или в меню."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Переделать эталон", callback_data="redo_ref")],
        [InlineKeyboardButton("✅ Готово, перейти в меню", callback_data="go_menu")],
    ])


def etalon_done_keyboard() -> InlineKeyboardMarkup:
    """После эталона — фото или видео."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Создать фото", callback_data="go_photo")],
        [InlineKeyboardButton("🎬 Создать видео", callback_data="go_video")],
    ])


MENU_BUTTONS = {BTN_PROFILE, BTN_PHOTO, BTN_VIDEO, BTN_ETALON, BTN_PRICING, BTN_HELP, BTN_RESTART}

__all__ = [
    "BTN_PROFILE",
    "BTN_PHOTO",
    "BTN_VIDEO",
    "BTN_ETALON",
    "BTN_PRICING",
    "BTN_HELP",
    "BTN_RESTART",
    "MENU_BUTTONS",
    "main_menu",
    "main_menu_inline",
    "back_button",
    "back_to_menu_button",
    "mp_select_keyboard",
    "etalon_create_keyboard",
    "etalon_feedback_keyboard",
    "etalon_feedback_with_continue_keyboard",
    "photo_count_keyboard",
    "etalon_existing_keyboard",
    "etalon_done_keyboard",
]
