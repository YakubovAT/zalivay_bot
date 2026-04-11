"""
handlers/keyboards/__init__.py

Inline-клавиатуры для всех экранов бота.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ---------------------------------------------------------------------------
# Шаг 1: Приветствие
# ---------------------------------------------------------------------------

def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Начать ➜", callback_data="start_begin")],
    ])


# ---------------------------------------------------------------------------
# Шаг 2: Профиль / Главное меню
# ---------------------------------------------------------------------------

def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Новый артикул", callback_data="menu_new_article"),
        ],
        [
            InlineKeyboardButton("📸 Генерировать фото", callback_data="menu_gen_photo"),
            InlineKeyboardButton("🎥 Генерировать видео", callback_data="menu_gen_video"),
        ],
        [
            InlineKeyboardButton("📂 Мои эталоны", callback_data="menu_my_refs"),
            InlineKeyboardButton("💰 Пополнить баланс", callback_data="menu_topup"),
        ],
    ])


# ---------------------------------------------------------------------------
# Шаг 3: Выбор маркетплейса
# ---------------------------------------------------------------------------

def kb_marketplace() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ WB", callback_data="mp_wb"),
            InlineKeyboardButton("🔒 Ozon", callback_data="mp_ozon_lock"),
            InlineKeyboardButton("🔒 YM", callback_data="mp_ym_lock"),
        ],
        [InlineKeyboardButton("← Назад", callback_data="back_to_menu")],
    ])


# ---------------------------------------------------------------------------
# Навигация: ввод артикула (без текста, только кнопки)
# ---------------------------------------------------------------------------

def kb_enter_article() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("← К маркетплейсам", callback_data="back_to_mp"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])
