import logging
from io import BytesIO

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import asyncio
import subprocess

from database import ensure_user, is_registered, save_registration, reset_registration, delete_user, save_article, save_reference, get_user
from handlers.menu import main_menu, BTN_RESTART
from config import REFERENCE_COST
from wb_parser import get_product_info
from services.media_storage import ensure_user_media_dirs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Состояния
# ---------------------------------------------------------------------------

ONBOARD_STEP1      = 10  # Что такое эталон
ONBOARD_STEP2      = 11  # Бюджет
ONBOARD_STEP3      = 12  # Количество артикулов
ONBOARD_STEP4      = 13  # Переход к вводу артикула
ONBOARD_SELECT_MP  = 14  # Выбор МП
ONBOARD_ARTICLE    = 15  # Ввод артикула
ONBOARD_REF_CHOICE = 16  # Выбор: создать эталон / другой артикул
ONBOARD_REF_FEEDBACK = 17 # ✅ Подходит / 🔄 Переделать

# ---------------------------------------------------------------------------
# Перезапуск онбординга
# ---------------------------------------------------------------------------

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user(update.effective_user.id)
    context.user_data.clear()
    await update.message.reply_text("🔄 Обновление и перезапуск бота...")
    await asyncio.sleep(1)
    subprocess.Popen(
        "sleep 2 && cd /var/www/bots/Zalivai_bot && git pull && systemctl restart zalivai-bot",
        shell=True,
        start_new_session=True,
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Шаг 0 — /start
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await ensure_user(user.id, user.username)
    ensure_user_media_dirs(user.id)  # Создаём папку пользователя

    if await is_registered(user.id):
        await update.message.reply_text(
            f"С возвращением, {user.first_name}! Выберите действие:",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Дальше →", callback_data="onboard_step1")]]
    )
    await update.message.reply_text(
        "Снижаем затраты на рекламу\nчерез AI-контент 🚀",
        reply_markup=keyboard,
    )
    return ONBOARD_STEP1


# ---------------------------------------------------------------------------
# Шаг 1 → Шаг 2: бюджет на рекламу
# ---------------------------------------------------------------------------

async def step1_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("А: до 100к",    callback_data="budget_a"),
            InlineKeyboardButton("Б: 100–500к",   callback_data="budget_b"),
        ],
        [
            InlineKeyboardButton("В: 500к–1млн",  callback_data="budget_c"),
            InlineKeyboardButton("Г: 1млн+",      callback_data="budget_d"),
        ],
    ])
    await query.edit_message_text(
        "Затраты на рекламу в месяц?",
        reply_markup=keyboard,
    )
    return ONBOARD_STEP2


# ---------------------------------------------------------------------------
# Шаг 2 → Шаг 3: количество артикулов
# ---------------------------------------------------------------------------

BUDGET_MAP = {
    "budget_a": "до 100к",
    "budget_b": "100–500к",
    "budget_c": "500к–1млн",
    "budget_d": "1млн+",
}

async def step2_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["ad_budget"] = BUDGET_MAP[query.data]

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("А: 1–20",  callback_data="articles_a"),
            InlineKeyboardButton("Б: 20–50", callback_data="articles_b"),
            InlineKeyboardButton("В: 50+",   callback_data="articles_c"),
        ]
    ])
    await query.edit_message_text(
        "Количество артикулов?",
        reply_markup=keyboard,
    )
    return ONBOARD_STEP3


# ---------------------------------------------------------------------------
# Шаг 3 → Шаг 4: благодарность
# ---------------------------------------------------------------------------

ARTICLES_MAP = {
    "articles_a": "1–20",
    "articles_b": "20–50",
    "articles_c": "50+",
}

async def step3_articles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["articles_count"] = ARTICLES_MAP[query.data]

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Двигаемся дальше →", callback_data="onboard_finish")]]
    )
    await query.edit_message_text(
        "Большое спасибо. Двигаемся дальше?",
        reply_markup=keyboard,
    )
    return ONBOARD_STEP4


# ---------------------------------------------------------------------------
# Шаг 4 → сохранение + главное меню
# ---------------------------------------------------------------------------

async def step4_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    ad_budget      = context.user_data.get("ad_budget", "")
    articles_count = context.user_data.get("articles_count", "")

    await save_registration(user_id, ad_budget, articles_count)

    await query.edit_message_text(
        "✅ Отлично! Теперь давайте начнём создавать контент.\n\n"
        "Для создания фото и видеоконтента и продвижения "
        "в социальных сетях, нам необходимо для каждого артикула "
        "создать <b>эталон</b>.\n\n"
        "Эталон — это чистое фото товара без фона. "
        "Создаётся один раз для каждого артикула и "
        "используется для всех будущих фото и видео.\n\n"
        "Выберите маркетплейс и введите артикул:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🟣 Wildberries", callback_data="onboard_mp_wb"),
            InlineKeyboardButton("🔵 OZON",        callback_data="onboard_mp_ozon"),
        ]]),
    )
    return ONBOARD_SELECT_MP


# ---------------------------------------------------------------------------
# Выбор маркетплейса → запрос артикула
# ---------------------------------------------------------------------------

async def onboard_select_mp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mp = "WB" if query.data == "onboard_mp_wb" else "OZON"
    context.user_data["onboard_marketplace"] = mp

    label = "Wildberries" if mp == "WB" else "OZON"
    await query.edit_message_text(
        f"Введите артикул товара {label}:",
    )
    return ONBOARD_ARTICLE


# ---------------------------------------------------------------------------
# Ввод артикула → карточка товара → выбор: создать эталон / другой артикул
# ---------------------------------------------------------------------------

async def onboard_article(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw = update.message.text.strip()
    marketplace = context.user_data.get("onboard_marketplace", "WB")

    status_msg = await update.message.reply_text("🔍 Загружаю информацию о товаре...")

    name = color = material = ""
    info = {}

    if marketplace == "WB":
        try:
            info = await get_product_info(raw)
        except Exception:
            info = {}

        if not info:
            await status_msg.delete()
            await update.message.reply_text(
                "❌ Товар не найден на Wildberries. Проверьте артикул и введите ещё раз:"
            )
            return ONBOARD_ARTICLE

        color    = info["colors"][0] if info.get("colors") else ""
        name     = info.get("name", "")
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

        await status_msg.delete()
        await update.message.reply_text(
            f"✅ Артикул <code>{raw}</code> найден на Wildberries 🟣\n\n"
            + "\n".join(meta_lines),
            parse_mode="HTML",
        )
    else:
        await status_msg.delete()
        await update.message.reply_text(
            f"✅ Артикул <code>{raw}</code> сохранён для OZON 🔵",
            parse_mode="HTML",
        )

    await save_article(
        user_id=user_id,
        article_code=raw,
        marketplace=marketplace,
        name=name,
        color=color,
        material=material,
    )

    context.user_data["onboard_article"] = raw
    context.user_data["product_info"] = {
        "name": name,
        "color": color,
        "material": material,
    }
    context.user_data["wb_images"] = info.get("images", [])[:5]

    # Кнопки: создать эталон или другой артикул
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Создать эталон — 100 руб.", callback_data="create_ref")],
        [InlineKeyboardButton("🔄 Ввести другой артикул", callback_data="new_article")],
    ])
    await update.message.reply_text(
        "Что делаем дальше?",
        reply_markup=keyboard,
    )

    return ONBOARD_REF_CHOICE


# ---------------------------------------------------------------------------
# Онбординг: выбор — создать эталон или другой артикул
# ---------------------------------------------------------------------------

async def onboard_ref_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "new_article":
        # Возвращаемся к выбору МП
        await query.edit_message_text(
            "Выберите маркетплейс и введите артикул:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🟣 Wildberries", callback_data="onboard_mp_wb"),
                InlineKeyboardButton("🔵 OZON",        callback_data="onboard_mp_ozon"),
            ]]),
        )
        return ONBOARD_SELECT_MP

    if query.data == "create_ref":
        articul = context.user_data.get("onboard_article", "")
        product = context.user_data.get("product_info", {})
        db_user = await get_user(update.effective_user.id)
        balance = db_user["balance"] if db_user else 0

        if balance < REFERENCE_COST:
            await query.edit_message_text(
                f"❌ Недостаточно средств.\n\n"
                f"Стоимость: <b>{REFERENCE_COST} руб.</b>\n"
                f"Баланс: <b>{balance} руб.</b>\n\n"
                f"Пополните баланс и попробуйте снова.",
                parse_mode="HTML",
            )
            return ConversationHandler.END

        # T2T AI → генерация промпта
        await query.edit_message_text("⚙️ Генерирую промпт...")

        session = context.bot_data.get("http_session")
        if not session:
            await query.message.reply_text("⚠️ Техническая ошибка.")
            return ConversationHandler.END

        from config import AI_API_KEY, AI_API_BASE, AI_MODEL
        from services.reference_generator import generate_reference_prompt
        from services.i2i_generator import generate_reference_image

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
            await query.message.reply_text("❌ Ошибка генерации промпта.")
            return ConversationHandler.END

        context.user_data["reference_prompt"] = prompt

        # I2I AI → генерация изображения
        wb_images = context.user_data.get("wb_images", [])
        if not wb_images:
            await query.message.reply_text("❌ Не удалось найти фото товара.")
            return ConversationHandler.END

        await query.message.reply_text("📥 Отправляю фото в I2I AI...")

        image_url = await generate_reference_image(
            session=session,
            api_base=AI_API_BASE,
            api_key=AI_API_KEY,
            image_urls=wb_images[:3],
            prompt=prompt,
        )

        if not image_url:
            await query.message.reply_text("❌ Ошибка генерации изображения.")
            return ConversationHandler.END

        # Скачиваем и отправляем фото с кнопками
        try:
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=15)) as img_resp:
                image_data = await img_resp.read()
        except Exception as e:
            logger.error("Failed to download image: %s", e)
            await query.message.reply_text("❌ Ошибка загрузки изображения.")
            return ConversationHandler.END

        from io import BytesIO
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Подходит", callback_data="ref_ok")],
            [InlineKeyboardButton("🔄 Переделать", callback_data="ref_redo")],
        ])
        await query.message.reply_photo(
            photo=BytesIO(image_data),
            caption="🎨 Эталон готов!\n\nОн должен быть <i>похож</i>, а не 100% копией.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        return ONBOARD_REF_FEEDBACK


# ---------------------------------------------------------------------------
# Онбординг: обратная связь — ✅ Подходит / 🔄 Переделать
# ---------------------------------------------------------------------------

async def onboard_ref_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    articul = context.user_data.get("onboard_article", "")

    if query.data == "ref_ok":
        await save_reference(
            user_id=update.effective_user.id,
            articul=articul,
            file_id=f"ref_{articul}",
        )
        await query.edit_message_text(
            f"✅ Эталон для артикула <code>{articul}</code> сохранён!\n\n"
            f"Теперь вы можете создавать фото и видео.",
            parse_mode="HTML",
        )
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Выберите действие:",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    if query.data == "ref_redo":
        await query.edit_message_text(
            "✍️ Напишите что нужно изменить в эталоне:"
        )
        return ConversationHandler.END


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_registration_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.Regex(f"^{BTN_RESTART}$"), restart),
        ],
        states={
            ONBOARD_STEP1:     [CallbackQueryHandler(step1_next,       pattern="^onboard_step1$")],
            ONBOARD_STEP2:     [CallbackQueryHandler(step2_budget,     pattern="^budget_[abcd]$")],
            ONBOARD_STEP3:     [CallbackQueryHandler(step3_articles,   pattern="^articles_[abc]$")],
            ONBOARD_STEP4:     [CallbackQueryHandler(step4_finish,     pattern="^onboard_finish$")],
            ONBOARD_SELECT_MP: [CallbackQueryHandler(onboard_select_mp, pattern="^onboard_mp_(wb|ozon)$")],
            ONBOARD_ARTICLE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_article)],
            ONBOARD_REF_CHOICE: [CallbackQueryHandler(onboard_ref_choice, pattern="^(create_ref|new_article)$")],
            ONBOARD_REF_FEEDBACK: [CallbackQueryHandler(onboard_ref_feedback, pattern="^(ref_ok|ref_redo)$")],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        per_message=False,
    )
