import logging
from io import BytesIO

import aiohttp
from telegram import ReplyKeyboardMarkup, KeyboardButton, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from database import ensure_user, get_user, get_user_references, get_reference, save_article, save_reference
from wb_parser import get_product_info
from config import REFERENCE_COST, AI_API_KEY, AI_API_BASE, AI_MODEL
from services.reference_generator import generate_reference_prompt
from services.i2i_generator import generate_reference_image

logger = logging.getLogger(__name__)

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
WAITING_MP_PHOTO         = 1
WAITING_ARTICUL_PHOTO    = 2
WAITING_REF_CHOICE_PHOTO = 3
WAITING_REF_FEEDBACK     = 4
WAITING_MP_VIDEO         = 5
WAITING_ARTICUL_VIDEO    = 6
WAITING_REF_CHOICE_VIDEO = 7
WAITING_REF_FEEDBACK_V   = 8


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
    logger.info("MENU_PROFILE | user_id=%s | username=%s", user.id, user.username)
    await ensure_user(user.id, user.username)

    db_user = await get_user(user.id)
    refs = await get_user_references(user.id)

    ref_count = len(refs)
    balance = db_user["balance"] if db_user else 0

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"У Вас <b>{ref_count}</b> эталон(ов)\n"
        f"Баланс: <b>{balance}</b> руб."
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Фото — выбор маркетплейса
# ---------------------------------------------------------------------------

async def photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("MENU_PHOTO | user_id=%s | username=%s", user.id, user.username)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟣 Wildberries", callback_data="photo_mp_wb"),
            InlineKeyboardButton("🔵 OZON",        callback_data="photo_mp_ozon"),
        ]
    ])
    await update.message.reply_text(
        "Выберите маркетплейс:",
        reply_markup=keyboard,
    )
    return WAITING_MP_PHOTO


async def photo_select_mp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    mp = "WB" if query.data == "photo_mp_wb" else "OZON"
    logger.info("PHOTO_MP_SELECT | user_id=%s | marketplace=%s", query.from_user.id, mp)
    await query.answer()
    context.user_data["photo_marketplace"] = mp

    label = "Wildberries" if mp == "WB" else "OZON"
    await query.edit_message_text(
        f"Введите артикул товара {label} для создания фото:"
    )
    return WAITING_ARTICUL_PHOTO


async def photo_articul_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw = update.message.text.strip()
    marketplace = context.user_data.get("photo_marketplace", "WB")
    logger.info("PHOTO_ARTICLE_INPUT | user_id=%s | article=%s | mp=%s", user.id, raw, marketplace)
    await ensure_user(user.id, user.username)

    # --- OZON: заглушка ---
    if marketplace == "OZON":
        await update.message.reply_text(
            f"✅ Артикул <code>{raw}</code> сохранён для OZON 🔵\n\n"
            "⚠️ Генерация фото для OZON пока в разработке. "
            "Скоро эта функция станет доступна!",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # --- WB: парсер ---
    status_msg = await update.message.reply_text("🔍 Загружаю информацию о товаре...")

    try:
        info = await get_product_info(raw)
    except Exception:
        info = {}

    await status_msg.delete()

    if not info:
        await update.message.reply_text(
            f"❌ Товар не найден на Wildberries. Проверьте артикул и введите ещё раз:"
        )
        return WAITING_ARTICUL_PHOTO

    name     = info.get("name", "")
    color    = info["colors"][0] if info.get("colors") else ""
    material = info.get("material", "")

    meta_lines = []
    if name:
        meta_lines.append(f"📦 <b>{name}</b>")
    if info.get("brand"):
        meta_lines.append(f"🏷 {info['brand']}")
    if color:
        meta_lines.append(f"🎨 {color}")
    if material:
        meta_lines.append(f"🧵 {material}")

    await update.message.reply_text(
        f"✅ Артикул <code>{raw}</code> найден на Wildberries 🟣\n\n"
        + "\n".join(meta_lines),
        parse_mode="HTML",
    )

    await save_article(
        user_id=user.id,
        article_code=raw,
        marketplace=marketplace,
        name=name,
        color=color,
        material=material,
    )

    context.user_data["current_article"] = raw
    context.user_data["product_info"] = {
        "name": name,
        "color": color,
        "material": material,
    }
    context.user_data["wb_images"] = info.get("images", [])[:5]  # Берём первые 5 фото

    # Показываем кнопки выбора
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Создать эталон", callback_data="create_ref")],
        [InlineKeyboardButton("🔄 Ввести артикул", callback_data="new_article")],
    ])
    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=keyboard,
    )

    return WAITING_REF_CHOICE_PHOTO


async def photo_ref_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info("PHOTO_REF_CHOICE | user_id=%s | choice=%s", query.from_user.id, query.data)
    await query.answer()

    if query.data == "new_article":
        await query.edit_message_text("Выберите маркетплейс:")
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🟣 Wildberries", callback_data="photo_mp_wb"),
                InlineKeyboardButton("🔵 OZON",        callback_data="photo_mp_ozon"),
            ]
        ])
        await query.message.reply_text(
            "Выберите маркетплейс:",
            reply_markup=keyboard,
        )
        return WAITING_MP_PHOTO

    if query.data == "create_ref":
        articul = context.user_data.get("current_article", "")
        product = context.user_data.get("product_info", {})
        db_user = await get_user(update.effective_user.id)
        balance = db_user["balance"] if db_user else 0

        if balance < REFERENCE_COST:
            await query.edit_message_text(
                f"❌ Недостаточно средств.\n\n"
                f"Стоимость создания эталона: <b>{REFERENCE_COST} руб.</b>\n"
                f"Ваш баланс: <b>{balance} руб.</b>\n\n"
                f"Пополните баланс и попробуйте снова.",
                parse_mode="HTML",
            )
            return ConversationHandler.END

        session = context.bot_data.get("http_session")
        if not session:
            await query.message.reply_text("⚠️ Техническая ошибка. Попробуйте позже.")
            return ConversationHandler.END

        prompt = await generate_reference_prompt(
            session=session,
            name=product.get("name", ""),
            color=product.get("color", ""),
            material=product.get("material", ""),
            api_key=AI_API_KEY,
            api_base_url=AI_API_BASE,
            model=AI_MODEL,
        )

        if not prompt:
            await query.message.reply_text("❌ Ошибка генерации промпта. Попробуйте снова.")
            return ConversationHandler.END

        context.user_data["reference_prompt"] = prompt

        # I2I AI — генерируем эталон
        wb_images = context.user_data.get("wb_images", [])
        if not wb_images:
            await query.message.reply_text("❌ Не удалось найти фото товара.")
            return ConversationHandler.END

        image_url = await generate_reference_image(
            session=session,
            api_base=AI_API_BASE,
            api_key=AI_API_KEY,
            image_urls=wb_images[:3],  # Берём первые 3 фото
            prompt=prompt,
        )

        if not image_url:
            await query.message.reply_text("❌ Ошибка генерации изображения. Попробуйте снова.")
            return ConversationHandler.END

        # Скачиваем и отправляем фото
        try:
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=15)) as img_resp:
                image_data = await img_resp.read()
        except Exception as e:
            logger.error("Failed to download image: %s", e)
            await query.message.reply_text("❌ Ошибка загрузки изображения.")
            return ConversationHandler.END

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Подходит", callback_data="ref_ok")],
            [InlineKeyboardButton("🔄 Переделать", callback_data="ref_redo")],
        ])
        await query.message.reply_photo(
            photo=BytesIO(image_data),
            caption="🎨 Эталон готов!\n\nЭталон должен быть <i>похож</i>, а не 100% копией. Небольшие расхождения допустимы.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        # TODO: списать баланс
        return WAITING_REF_FEEDBACK


async def ref_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info("REF_FEEDBACK | user_id=%s | action=%s", query.from_user.id, query.data)
    await query.answer()

    articul = context.user_data.get("current_article", "")

    if query.data == "ref_ok":
        # Сохраняем эталон в БД (пока placeholder file_id)
        await save_reference(
            user_id=update.effective_user.id,
            articul=articul,
            file_id="placeholder_ref_225616209",
        )
        await query.edit_message_text(
            f"✅ Эталон для артикула <code>{articul}</code> сохранён!\n\n"
            f"Теперь вы можете создавать фото и видео через меню.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    if query.data == "ref_redo":
        await query.edit_message_text(
            "✍️ Напишите что нужно изменить в эталоне:"
        )
        return ConversationHandler.END  # TODO: добавить state для фидбека


# ---------------------------------------------------------------------------
# Видео — выбор маркетплейса
# ---------------------------------------------------------------------------

async def video_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("MENU_VIDEO | user_id=%s | username=%s", user.id, user.username)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟣 Wildberries", callback_data="video_mp_wb"),
            InlineKeyboardButton("🔵 OZON",        callback_data="video_mp_ozon"),
        ]
    ])
    await update.message.reply_text(
        "Выберите маркетплейс:",
        reply_markup=keyboard,
    )
    return WAITING_MP_VIDEO


async def video_select_mp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    mp = "WB" if query.data == "video_mp_wb" else "OZON"
    logger.info("VIDEO_MP_SELECT | user_id=%s | marketplace=%s", query.from_user.id, mp)
    await query.answer()
    context.user_data["video_marketplace"] = mp

    label = "Wildberries" if mp == "WB" else "OZON"
    await query.edit_message_text(
        f"Введите артикул товара {label} для получения видео-эталона:"
    )
    return WAITING_ARTICUL_VIDEO


async def video_articul_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw = update.message.text.strip()
    marketplace = context.user_data.get("video_marketplace", "WB")
    logger.info("VIDEO_ARTICLE_INPUT | user_id=%s | article=%s | mp=%s", user.id, raw, marketplace)
    await ensure_user(user.id, user.username)

    # --- OZON: заглушка ---
    if marketplace == "OZON":
        await update.message.reply_text(
            f"✅ Артикул <code>{raw}</code> сохранён для OZON 🔵\n\n"
            "⚠️ Генерация видео для OZON пока в разработке. "
            "Скоро эта функция станет доступна!",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # --- WB: парсер ---
    status_msg = await update.message.reply_text("🔍 Загружаю информацию о товаре...")

    try:
        info = await get_product_info(raw)
    except Exception:
        info = {}

    await status_msg.delete()

    if not info:
        await update.message.reply_text(
            f"❌ Товар не найден на Wildberries. Проверьте артикул и введите ещё раз:"
        )
        return WAITING_ARTICUL_VIDEO

    name     = info.get("name", "")
    color    = info["colors"][0] if info.get("colors") else ""
    material = info.get("material", "")

    meta_lines = []
    if name:
        meta_lines.append(f"📦 <b>{name}</b>")
    if info.get("brand"):
        meta_lines.append(f"🏷 {info['brand']}")
    if color:
        meta_lines.append(f"🎨 {color}")
    if material:
        meta_lines.append(f"🧵 {material}")

    await update.message.reply_text(
        f"✅ Артикул <code>{raw}</code> найден на Wildberries 🟣\n\n"
        + "\n".join(meta_lines),
        parse_mode="HTML",
    )

    await save_article(
        user_id=user.id,
        article_code=raw,
        marketplace=marketplace,
        name=name,
        color=color,
        material=material,
    )

    context.user_data["current_article"] = raw
    context.user_data["product_info"] = {
        "name": name,
        "color": color,
        "material": material,
    }
    context.user_data["wb_images"] = info.get("images", [])[:5]  # Берём первые 5 фото

    # Показываем кнопки выбора
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Создать эталон", callback_data="create_ref")],
        [InlineKeyboardButton("🔄 Ввести артикул", callback_data="new_article")],
    ])
    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=keyboard,
    )

    return WAITING_REF_CHOICE_VIDEO


async def video_ref_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info("VIDEO_REF_CHOICE | user_id=%s | choice=%s", query.from_user.id, query.data)
    await query.answer()

    if query.data == "new_article":
        await query.edit_message_text("Выберите маркетплейс:")
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🟣 Wildberries", callback_data="video_mp_wb"),
                InlineKeyboardButton("🔵 OZON",        callback_data="video_mp_ozon"),
            ]
        ])
        await query.message.reply_text(
            "Выберите маркетплейс:",
            reply_markup=keyboard,
        )
        return WAITING_MP_VIDEO

    if query.data == "create_ref":
        articul = context.user_data.get("current_article", "")
        product = context.user_data.get("product_info", {})
        db_user = await get_user(update.effective_user.id)
        balance = db_user["balance"] if db_user else 0

        if balance < REFERENCE_COST:
            await query.edit_message_text(
                f"❌ Недостаточно средств.\n\n"
                f"Стоимость создания эталона: <b>{REFERENCE_COST} руб.</b>\n"
                f"Ваш баланс: <b>{balance} руб.</b>\n\n"
                f"Пополните баланс и попробуйте снова.",
                parse_mode="HTML",
            )
            return ConversationHandler.END

        session = context.bot_data.get("http_session")
        if not session:
            await query.message.reply_text("⚠️ Техническая ошибка. Попробуйте позже.")
            return ConversationHandler.END

        prompt = await generate_reference_prompt(
            session=session,
            name=product.get("name", ""),
            color=product.get("color", ""),
            material=product.get("material", ""),
            api_key=AI_API_KEY,
            api_base_url=AI_API_BASE,
            model=AI_MODEL,
        )

        if not prompt:
            await query.message.reply_text("❌ Ошибка генерации промпта. Попробуйте снова.")
            return ConversationHandler.END

        context.user_data["reference_prompt"] = prompt

        # TODO: I2I AI — создать PNG с прозрачным фоном
        # TODO: списать баланс
        # TODO: скачать и отправить фото
        return ConversationHandler.END


# ---------------------------------------------------------------------------
# Есть идея
# ---------------------------------------------------------------------------

async def idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("MENU_IDEA | user_id=%s | username=%s", user.id, user.username)
    await update.message.reply_text(
        "Напишите вашу идею напрямую: @work_wb01\n\nМы рассмотрим каждое предложение!"
    )


# ---------------------------------------------------------------------------
# Прайс
# ---------------------------------------------------------------------------

async def pricing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("MENU_PRICING | user_id=%s | username=%s", user.id, user.username)
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
    user = update.effective_user
    logger.info("MENU_HELP | user_id=%s | username=%s", user.id, user.username)
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
            WAITING_MP_PHOTO: [
                CallbackQueryHandler(photo_select_mp, pattern="^photo_mp_(wb|ozon)$")
            ],
            WAITING_ARTICUL_PHOTO: [
                MessageHandler(filters.TEXT & ~any_menu_button, photo_articul_received)
            ],
            WAITING_REF_CHOICE_PHOTO: [
                CallbackQueryHandler(photo_ref_choice, pattern="^(create_ref|new_article)$")
            ],
            WAITING_REF_FEEDBACK: [
                CallbackQueryHandler(ref_feedback, pattern="^(ref_ok|ref_redo)$")
            ],
            WAITING_MP_VIDEO: [
                CallbackQueryHandler(video_select_mp, pattern="^video_mp_(wb|ozon)$")
            ],
            WAITING_ARTICUL_VIDEO: [
                MessageHandler(filters.TEXT & ~any_menu_button, video_articul_received)
            ],
            WAITING_REF_CHOICE_VIDEO: [
                CallbackQueryHandler(video_ref_choice, pattern="^(create_ref|new_article)$")
            ],
            WAITING_REF_FEEDBACK_V: [
                CallbackQueryHandler(ref_feedback, pattern="^(ref_ok|ref_redo)$")
            ],
        },
        fallbacks=[
            MessageHandler(any_menu_button, _cancel),
        ],
    )
