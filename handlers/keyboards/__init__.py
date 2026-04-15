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
# Шаг 2: Профиль / Меню
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
            InlineKeyboardButton("← Назад", callback_data="back_to_mp"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Шаг 6: Подтверждение товара
# ---------------------------------------------------------------------------

def kb_product_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, это он", callback_data="product_yes"),
            InlineKeyboardButton("❌ Нет, другой", callback_data="product_no"),
        ],
        [
            InlineKeyboardButton("← Назад", callback_data="back_to_mp"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Шаг 7: Подтверждение создания эталона
# ---------------------------------------------------------------------------

def kb_confirm_reference() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Создать эталон", callback_data="ref_create_yes"),
        ],
        [
            InlineKeyboardButton("← Назад", callback_data="back_to_photo_select"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Шаг 6: Выбор фото (клавиатура выбора)
# ---------------------------------------------------------------------------

def kb_photo_select(selected: list, current_idx: int, total: int, done: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура для выбора фото (Эмодзи-круги, динамический 2-й ряд)."""
    row1 = []
    selected_slots = [s for s, _ in selected]
    for i in range(1, 4):
        if i in selected_slots:
            row1.append(InlineKeyboardButton(f"🔘 {i}", callback_data=f"sel_{i}"))
        else:
            row1.append(InlineKeyboardButton(f"⚪ {i}", callback_data=f"sel_{i}"))

    # Динамический второй ряд (2-3 кнопки)
    row2 = []
    has_prev = current_idx > 0
    has_next = current_idx < total - 1

    if has_prev:
        row2.append(InlineKeyboardButton("← Пред.", callback_data=f"photo_prev_{current_idx - 1}"))
    
    row2.append(InlineKeyboardButton(f"{current_idx + 1}/{total}", callback_data="noop"))

    if has_next:
        row2.append(InlineKeyboardButton("След. →", callback_data=f"photo_next_{current_idx + 1}"))

    rows = [row1, row2]
    if done:
        rows.append([InlineKeyboardButton("✅ Утвердить выбор", callback_data="photos_confirm")])
    rows.append([
        InlineKeyboardButton("← Назад (к карточке)", callback_data="back_to_product_confirm"),
        InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
    ])

    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Шаг 16: Карточка эталона (динамическая — навигация зависит от кол-ва)
# ---------------------------------------------------------------------------

def kb_ref_card(article: str, idx: int, total: int) -> InlineKeyboardMarkup:
    """Клавиатура карточки эталона с кнопкой перегенерации."""
    buttons = []
    if total > 1:
        nav_row = []
        if idx > 0:
            nav_row.append(InlineKeyboardButton("← Пред.", callback_data=f"ref_prev_{article}"))
        nav_row.append(InlineKeyboardButton(f"{idx + 1}/{total}", callback_data="noop"))
        if idx < total - 1:
            nav_row.append(InlineKeyboardButton("След. →", callback_data=f"ref_next_{article}"))
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton("🔄 Перегенерировать", callback_data=f"ref_regen_{article}")])
    buttons.append([
        InlineKeyboardButton("📸 Генерировать фото", callback_data="menu_gen_photo"),
        InlineKeyboardButton("🎥 Генерировать видео", callback_data="menu_gen_video"),
    ])
    buttons.append([
        InlineKeyboardButton("📂 Мои эталоны", callback_data="menu_my_refs"),
        InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
    ])
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# Шаг 16а: Перегенерация — ввод пожеланий и результат
# ---------------------------------------------------------------------------

def kb_regen_wish() -> InlineKeyboardMarkup:
    """Клавиатура экрана ввода пожеланий перед перегенерацией."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустить", callback_data="regen_skip")],
        [
            InlineKeyboardButton("← Назад к эталону", callback_data="regen_back"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


def kb_regen_result() -> InlineKeyboardMarkup:
    """Клавиатура после успешной перегенерации."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📸 Генерировать фото", callback_data="menu_gen_photo"),
            InlineKeyboardButton("🎥 Генерировать видео", callback_data="menu_gen_video"),
        ],
        [
            InlineKeyboardButton("📂 Мои эталоны", callback_data="menu_my_refs"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Шаг 15: Мои эталоны — пустое состояние
# ---------------------------------------------------------------------------

def kb_my_refs_empty() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить товар", callback_data="menu_new_article")],
        [InlineKeyboardButton("🌐 Перейти на сайт", url="https://media.zaliv.ai/")],
        [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")],
    ])


# ---------------------------------------------------------------------------
# Flow: Генерация фото — Шаг P1 (сколько фото?)
# ---------------------------------------------------------------------------

def kb_gen_photo_count() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data="gen_count_1"),
            InlineKeyboardButton("5", callback_data="gen_count_5"),
            InlineKeyboardButton("10", callback_data="gen_count_10"),
        ],
        [
            InlineKeyboardButton("← Назад", callback_data="back_to_ref_card"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Flow: Генерация фото — Шаг P2 (пожелания)
# ---------------------------------------------------------------------------

def kb_gen_photo_wish() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Нет пожеланий", callback_data="gen_photo_no_wish")],
        [
            InlineKeyboardButton("← Назад", callback_data="back_to_p_count"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Flow: Генерация фото — Шаг P3 (подтверждение)
# ---------------------------------------------------------------------------

def kb_gen_photo_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Сгенерировать", callback_data="gen_photo_yes")],
        [
            InlineKeyboardButton("← Назад", callback_data="back_to_p_wish"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Flow: Генерация фото — Результат
# ---------------------------------------------------------------------------

def kb_gen_photo_result() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📸 Генерировать ещё", callback_data="menu_gen_photo"),
            InlineKeyboardButton("📂 Мои эталоны", callback_data="menu_my_refs"),
        ],
        [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")],
        [InlineKeyboardButton("✕ Закрыть", callback_data="gen_photo_close")],
    ])
