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
            InlineKeyboardButton("➕ Новый эталон", callback_data="menu_new_article"),
        ],
        [
            InlineKeyboardButton("📸 Создать фото", callback_data="menu_gen_photo"),
            InlineKeyboardButton("🎥 Создать видео", callback_data="menu_gen_video"),
        ],
        [
            InlineKeyboardButton("📂 Мои эталоны", callback_data="menu_my_refs"),
            InlineKeyboardButton("💰 Пополнить баланс", callback_data="menu_topup"),
        ],
        [
            InlineKeyboardButton("📌 Пинтерест", callback_data="menu_pinterest"),
            InlineKeyboardButton("💧 Watermark", callback_data="menu_watermark"),
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
    """Клавиатура карточки эталона с кнопкой пересоздания."""
    buttons = []
    if total > 1:
        nav_row = []
        if idx > 0:
            nav_row.append(InlineKeyboardButton("← Пред.", callback_data=f"ref_prev_{article}"))
        nav_row.append(InlineKeyboardButton(f"{idx + 1}/{total}", callback_data="noop"))
        if idx < total - 1:
            nav_row.append(InlineKeyboardButton("След. →", callback_data=f"ref_next_{article}"))
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton("🔄 Переделать эталон", callback_data=f"ref_regen_{article}")])
    buttons.append([
        InlineKeyboardButton("📸 Создать фото", callback_data="menu_gen_photo"),
        InlineKeyboardButton("🎥 Создать видео", callback_data="menu_gen_video"),
    ])
    buttons.append([
        InlineKeyboardButton("📂 Мои эталоны", callback_data="menu_my_refs"),
        InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
    ])
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# Шаг 16а: Пересоздание — ввод пожеланий и результат
# ---------------------------------------------------------------------------

def kb_regen_wish() -> InlineKeyboardMarkup:
    """Клавиатура экрана ввода пожеланий перед созданием."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустить", callback_data="regen_skip")],
        [
            InlineKeyboardButton("← Назад к эталону", callback_data="regen_back"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


def kb_regen_result(article: str) -> InlineKeyboardMarkup:
    """Клавиатура после успешного пересоздания."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Переделать эталон", callback_data=f"ref_regen_{article}")],
        [
            InlineKeyboardButton("📸 Создать фото", callback_data="menu_gen_photo"),
            InlineKeyboardButton("🎥 Создать видео", callback_data="menu_gen_video"),
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
# Flow: Создание фото — Шаг P1 (сколько фото?)
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
# Flow: Создание фото — Шаг P2 (пожелания)
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
# Flow: Создание фото — Шаг P3 (подтверждение)
# ---------------------------------------------------------------------------

def kb_gen_photo_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Создать", callback_data="gen_photo_yes")],
        [
            InlineKeyboardButton("← Назад", callback_data="back_to_p_wish"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Flow: Создание фото — Результат
# ---------------------------------------------------------------------------

def kb_gen_photo_result() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📸 Создать ещё", callback_data="menu_gen_photo"),
            InlineKeyboardButton("📂 Мои эталоны", callback_data="menu_my_refs"),
        ],
        [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")],
    ])


# ---------------------------------------------------------------------------
# Flow: Создание видео — Шаг V1 (сколько видео?)
# ---------------------------------------------------------------------------

def kb_gen_video_count() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data="gen_video_count_1"),
            InlineKeyboardButton("2", callback_data="gen_video_count_2"),
            InlineKeyboardButton("3", callback_data="gen_video_count_3"),
        ],
        [
            InlineKeyboardButton("← Назад", callback_data="back_to_ref_card"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Flow: Создание видео — Шаг V2 (пожелания)
# ---------------------------------------------------------------------------

def kb_gen_video_wish() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Нет пожеланий", callback_data="gen_video_no_wish")],
        [
            InlineKeyboardButton("← Назад", callback_data="back_to_v_count"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Flow: Создание видео — Шаг V3 (подтверждение)
# ---------------------------------------------------------------------------

def kb_gen_video_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Создать", callback_data="gen_video_yes")],
        [
            InlineKeyboardButton("← Назад", callback_data="back_to_v_wish"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Flow: Создание видео — Результат
# ---------------------------------------------------------------------------

def kb_gen_video_result() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎥 Создать ещё", callback_data="menu_gen_video"),
            InlineKeyboardButton("📂 Мои эталоны", callback_data="menu_my_refs"),
        ],
        [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")],
    ])


# ---------------------------------------------------------------------------
# Flow: Pinterest меню — Шаг П1 (обзор)
# ---------------------------------------------------------------------------

def kb_pinterest_menu_overview() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Создать CSV", callback_data="pmenu_csv")],
        [InlineKeyboardButton("← Назад", callback_data="back_to_menu")],
    ])


# ---------------------------------------------------------------------------
# Flow: Pinterest меню — Шаг П2 (выбор количества строк)
# ---------------------------------------------------------------------------

def kb_pinterest_menu_count(available: int) -> InlineKeyboardMarkup:
    options = [10, 50, 100]
    row = [
        InlineKeyboardButton(str(n), callback_data=f"pmenu_count_{n}")
        for n in options
    ]
    return InlineKeyboardMarkup([
        row,
        [
            InlineKeyboardButton("← Назад", callback_data="pmenu_back_overview"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Flow: Pinterest меню — Шаг П3 (подтверждение)
# ---------------------------------------------------------------------------

def kb_pinterest_menu_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Создать CSV", callback_data="pmenu_confirm")],
        [
            InlineKeyboardButton("← Назад", callback_data="pmenu_back_dist"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Flow: Pinterest меню — Шаг П2.5 (распределение)
# ---------------------------------------------------------------------------

def kb_pinterest_menu_distribution() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайно из всех",     callback_data="pmenu_dist_random")],
        [InlineKeyboardButton("⚖️ Поровну по артикулам", callback_data="pmenu_dist_equal")],
        [InlineKeyboardButton("🎯 Приоритет артикулу →", callback_data="pmenu_dist_priority")],
        [
            InlineKeyboardButton("← Назад", callback_data="pmenu_back_count"),
            InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
        ],
    ])


# ---------------------------------------------------------------------------
# Flow: Pinterest меню — Шаг П2.6 (выбор артикула)
# ---------------------------------------------------------------------------

def kb_pinterest_menu_articles(articles: list[dict]) -> InlineKeyboardMarkup:
    """Динамический список артикулов.
    articles = [{'article_code': str, 'name': str, 'photo_count': int, 'video_count': int}]
    """
    rows = []
    for a in articles:
        total = a["photo_count"] + a["video_count"]
        label = f"{a['name']} ({total} фото)" if a["name"] != a["article_code"] else f"{a['article_code']} ({total} фото)"
        rows.append([InlineKeyboardButton(label, callback_data=f"pmenu_article_{a['article_code']}")])
    rows.append([
        InlineKeyboardButton("← Назад", callback_data="pmenu_back_dist"),
        InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu"),
    ])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Flow: Watermark — Подтверждение
# ---------------------------------------------------------------------------

def kb_watermark_confirm(count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("← Назад", callback_data="back_to_menu"),
            InlineKeyboardButton("⚙️ Обработка", callback_data="watermark_confirm"),
        ],
    ])


def kb_watermark_result() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← Назад", callback_data="back_to_menu")],
    ])
