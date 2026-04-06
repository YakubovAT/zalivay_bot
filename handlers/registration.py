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

from database import ensure_user, is_registered, save_registration, reset_registration, delete_user, save_article
from handlers.menu import main_menu, BTN_RESTART
from wb_parser import get_product_info
from services.media_storage import ensure_user_media_dirs

# ---------------------------------------------------------------------------
# Состояния
# ---------------------------------------------------------------------------

ONBOARD_STEP1      = 10
ONBOARD_STEP2      = 11
ONBOARD_STEP3      = 12
ONBOARD_STEP4      = 13
ONBOARD_SELECT_MP  = 14
ONBOARD_ARTICLE    = 15

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
# Шаг 4 → сохранение + выбор маркетплейса
# ---------------------------------------------------------------------------

async def step4_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    ad_budget      = context.user_data.get("ad_budget", "")
    articles_count = context.user_data.get("articles_count", "")

    await save_registration(user_id, ad_budget, articles_count)

    await query.edit_message_text("Отлично! Добро пожаловать 🎉")

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🟣 Wildberries", callback_data="onboard_mp_wb"),
        InlineKeyboardButton("🔵 OZON",        callback_data="onboard_mp_ozon"),
    ]])
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            "Чтобы начать создавать фото и видео контент, сначала нужно создать "
            "<b>эталонное изображение</b> товара — это базовый снимок, на основе "
            "которого AI будет генерировать все материалы.\n\n"
            "Выберите маркетплейс вашего товара:"
        ),
        parse_mode="HTML",
        reply_markup=keyboard,
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
# Ввод артикула → сохранение + главное меню
# ---------------------------------------------------------------------------

async def onboard_article(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id    = update.effective_user.id
    raw        = update.message.text.strip()
    marketplace = context.user_data.get("onboard_marketplace", "WB")

    status_msg = await update.message.reply_text("🔍 Загружаю информацию о товаре...")

    name = color = material = ""

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

    await update.message.reply_text(
        "Отлично! Артикул сохранён.\n\n"
        "Теперь выберите действие в меню:",
        reply_markup=main_menu(),
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
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        per_message=False,
    )
