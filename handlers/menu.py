from telegram import ReplyKeyboardMarkup, KeyboardButton, Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import ensure_user, get_user, get_user_references, get_reference, save_article
from services.marketplace import resolve_marketplace

# ---------------------------------------------------------------------------
# Кнопки меню
# ---------------------------------------------------------------------------

BTN_PROFILE = "Профиль"
BTN_PHOTO   = "Фото"
BTN_VIDEO   = "Видео"
BTN_IDEA    = "Есть идея"
BTN_PRICING = "Прайс"
BTN_HELP    = "Помощь"
BTN_RESTART    = "Перезапуск"

# Состояния ConversationHandler
WAITING_ARTICUL_PHOTO = 1
WAITING_ARTICUL_VIDEO = 2


def main_menu() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(BTN_PROFILE), KeyboardButton(BTN_PHOTO),    KeyboardButton(BTN_VIDEO)],
        [KeyboardButton(BTN_IDEA),    KeyboardButton(BTN_PRICING),   KeyboardButton(BTN_HELP)],
        [KeyboardButton(BTN_RESTART)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await ensure_user(user.id, user.username)
    await update.message.reply_text(
        f"Привет, {user.first_name}!\n\nВыбери действие в меню ниже.",
        reply_markup=main_menu(),
    )


# ---------------------------------------------------------------------------
# Профиль
# ---------------------------------------------------------------------------

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await ensure_user(user.id, user.username)

    db_user = await get_user(user.id)
    refs = await get_user_references(user.id)

    photo_count = sum(1 for r in refs if r["ref_type"] == "photo")
    video_count = sum(1 for r in refs if r["ref_type"] == "video")
    balance = db_user["balance"] if db_user else 0

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"Эталонов для фото: <b>{photo_count}</b>\n"
        f"Эталонов для видео: <b>{video_count}</b>\n"
        f"Баланс: <b>{balance}</b> руб."
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Фото — запрос артикула
# ---------------------------------------------------------------------------

async def photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите артикул товара Wildberries для создания фото:"
    )
    return WAITING_ARTICUL_PHOTO


async def photo_articul_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw = update.message.text

    # Прогресс — показываем пока идёт запрос к WB API
    status_msg = await update.message.reply_text("🔍 Определяю маркетплейс...")

    session = context.bot_data.get("http_session")
    result = await resolve_marketplace(raw, user_id, session)

    await status_msg.delete()

    # --- Ошибки ---
    if "error" in result:
        err = result["error"]
        if err == "invalid_format":
            await update.message.reply_text(
                f"❌ {result['message']}\n\nВведите артикул ещё раз:"
            )
            return WAITING_ARTICUL_PHOTO
        if err == "api_unavailable":
            await update.message.reply_text(
                f"⏳ {result['message']}\n\nПопробуйте через несколько секунд:"
            )
            return WAITING_ARTICUL_PHOTO
        # not_found или неизвестная ошибка
        await update.message.reply_text(
            "❌ Товар не найден ни на WB, ни на OZON.\n"
            "Проверьте артикул и попробуйте ещё раз:"
        )
        return WAITING_ARTICUL_PHOTO

    # --- Маркетплейс определён ---
    marketplace = result["marketplace"]
    meta        = result.get("meta", {})
    articul     = raw.strip()

    mp_label = "Wildberries 🟣" if marketplace == "WB" else "OZON 🔵"
    confidence_note = (
        "\n\n⚠️ <i>Товар не найден на WB — предполагаем OZON. "
        "Если это неверно, проверьте артикул.</i>"
        if result.get("confidence", 1.0) < 1.0 else ""
    )

    meta_lines = []
    if meta.get("name"):
        meta_lines.append(f"📦 <b>{meta['name']}</b>")
    if meta.get("brand"):
        meta_lines.append(f"🏷 {meta['brand']}")
    if meta.get("color"):
        meta_lines.append(f"🎨 {meta['color']}")
    if meta.get("material"):
        meta_lines.append(f"🧵 {meta['material']}")
    meta_block = "\n".join(meta_lines)
    if meta_block:
        meta_block = f"\n\n{meta_block}"

    await update.message.reply_text(
        f"✅ Артикул <code>{articul}</code> найден на {mp_label}"
        f"{meta_block}"
        f"{confidence_note}\n\n"
        f"⏳ Начинается сбор информации о товаре...",
        parse_mode="HTML",
    )

    # Сохраняем артикул в БД
    await save_article(
        user_id=user_id,
        article_code=articul,
        marketplace=marketplace,
        name=meta.get("name", ""),
        color=meta.get("color", ""),
        material=meta.get("material", ""),
    )

    # Сохраняем в user_data для следующих шагов
    context.user_data["current_article"]     = articul
    context.user_data["current_marketplace"] = marketplace

    ref = await get_reference(user_id, articul, "photo")
    if ref:
        await update.message.reply_photo(
            photo=ref["file_id"],
            caption=f"Готовый эталон для артикула {articul}",
        )
    else:
        await update.message.reply_text(
            "📋 Эталон ещё не создан. Запускаем генерацию...\n"
            "# TODO: запустить workflow создания эталона"
        )

    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Видео — запрос артикула
# ---------------------------------------------------------------------------

async def video_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите артикул товара Wildberries для получения видео-эталона:"
    )
    return WAITING_ARTICUL_VIDEO


async def video_articul_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw = update.message.text

    status_msg = await update.message.reply_text("🔍 Определяю маркетплейс...")

    session = context.bot_data.get("http_session")
    result = await resolve_marketplace(raw, user_id, session)

    await status_msg.delete()

    if "error" in result:
        err = result["error"]
        if err == "invalid_format":
            await update.message.reply_text(
                f"❌ {result['message']}\n\nВведите артикул ещё раз:"
            )
            return WAITING_ARTICUL_VIDEO
        if err == "api_unavailable":
            await update.message.reply_text(
                f"⏳ {result['message']}\n\nПопробуйте через несколько секунд:"
            )
            return WAITING_ARTICUL_VIDEO
        await update.message.reply_text(
            "❌ Товар не найден ни на WB, ни на OZON.\n"
            "Проверьте артикул и попробуйте ещё раз:"
        )
        return WAITING_ARTICUL_VIDEO

    marketplace = result["marketplace"]
    meta        = result.get("meta", {})
    articul     = raw.strip()

    mp_label = "Wildberries 🟣" if marketplace == "WB" else "OZON 🔵"
    confidence_note = (
        "\n\n⚠️ <i>Товар не найден на WB — предполагаем OZON. "
        "Если это неверно, проверьте артикул.</i>"
        if result.get("confidence", 1.0) < 1.0 else ""
    )

    meta_lines = []
    if meta.get("name"):
        meta_lines.append(f"📦 <b>{meta['name']}</b>")
    if meta.get("brand"):
        meta_lines.append(f"🏷 {meta['brand']}")
    if meta.get("color"):
        meta_lines.append(f"🎨 {meta['color']}")
    if meta.get("material"):
        meta_lines.append(f"🧵 {meta['material']}")
    meta_block = "\n".join(meta_lines)
    if meta_block:
        meta_block = f"\n\n{meta_block}"

    await update.message.reply_text(
        f"✅ Артикул <code>{articul}</code> найден на {mp_label}"
        f"{meta_block}"
        f"{confidence_note}\n\n"
        f"⏳ Начинается сбор информации о товаре...",
        parse_mode="HTML",
    )

    # Сохраняем артикул в БД
    await save_article(
        user_id=user_id,
        article_code=articul,
        marketplace=marketplace,
        name=meta.get("name", ""),
        color=meta.get("color", ""),
        material=meta.get("material", ""),
    )

    context.user_data["current_article"]     = articul
    context.user_data["current_marketplace"] = marketplace

    ref = await get_reference(user_id, articul, "video")
    if ref:
        await update.message.reply_video(
            video=ref["file_id"],
            caption=f"Готовый видео-эталон для артикула {articul}",
        )
    else:
        await update.message.reply_text(
            "📋 Видео-эталон ещё не создан. Запускаем генерацию...\n"
            "# TODO: запустить workflow создания видео-эталона"
        )

    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Есть идея
# ---------------------------------------------------------------------------

async def idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Напишите вашу идею напрямую: @work_wb01\n\nМы рассмотрим каждое предложение!"
    )


# ---------------------------------------------------------------------------
# Прайс
# ---------------------------------------------------------------------------

async def pricing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💰 <b>Прайс</b>\n\n"
        "🖼 Создание фото-эталона — <b>XX руб.</b>\n"
        "🎬 Создание видео-эталона — <b>XX руб.</b>\n\n"
        "По вопросам тарифов: @work_wb01"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Помощь
# ---------------------------------------------------------------------------

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Если у вас возникли вопросы или нужна помощь — напишите нам: @work_wb01"
    )


# ---------------------------------------------------------------------------
# ConversationHandler (Фото + Видео)
# ---------------------------------------------------------------------------

async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END


def build_conversation_handler() -> ConversationHandler:
    any_menu_button = filters.Regex(
        f"^({BTN_PROFILE}|{BTN_PHOTO}|{BTN_VIDEO}|{BTN_IDEA}|{BTN_PRICING}|{BTN_HELP})$"
    )

    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{BTN_PHOTO}$"), photo_start),
            MessageHandler(filters.Regex(f"^{BTN_VIDEO}$"), video_start),
        ],
        states={
            WAITING_ARTICUL_PHOTO: [
                MessageHandler(filters.TEXT & ~any_menu_button, photo_articul_received)
            ],
            WAITING_ARTICUL_VIDEO: [
                MessageHandler(filters.TEXT & ~any_menu_button, video_articul_received)
            ],
        },
        fallbacks=[
            MessageHandler(any_menu_button, _cancel),
        ],
    )
