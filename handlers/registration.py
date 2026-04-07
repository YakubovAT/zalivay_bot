import logging
import os
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

from database import ensure_user, is_registered, save_registration, reset_registration, delete_user, save_article, save_reference, get_user, get_reference, deduct_balance
from handlers.menu import main_menu, BTN_RESTART
from config import REFERENCE_COST, PHOTO_COST
from wb_parser import get_product_info
from services.media_storage import ensure_user_media_dirs, MEDIA_ROOT

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
ONBOARD_REDO_FEEDBACK = 18 # Ввод текста для переделки
PHOTO_COUNT_CHOICE = 19    # Выбор: одно или несколько фото
PHOTO_CRITERIA_INPUT = 20  # Ввод критериев для фото
PHOTO_MULTI_COUNT = 21     # Ввод количества для мульти-генерации

# ---------------------------------------------------------------------------
# Перезапуск онбординга
# ---------------------------------------------------------------------------

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("RESTART | user_id=%s | username=%s", user.id, user.username)
    await delete_user(user.id)
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
    logger.info("START | user_id=%s | username=%s", user.id, user.username)
    await ensure_user(user.id, user.username)
    ensure_user_media_dirs(user.id)  # Создаём папку пользователя

    if await is_registered(user.id):
        logger.info("START | existing user %s returning", user.id)
        await update.message.reply_text(
            f"С возвращением, {user.first_name}! Выберите действие:",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Дальше →", callback_data="onboard_step1")]]
    )
    await update.message.reply_text(
        "🤖 <b>AI-ассистент для селлеров маркетплейсов</b>\n\n"
        "Автоматизировированный бот, который создаёт фото и видео для социальных сетей на основе ваших товаров.\n\n"
        "📌 <b>Какие задачи решает:</b>\n"
        "• Создание эталонных фото товаров без фотографа\n"
        "• Генерация lifestyle-контента для рекламы в соцсетях\n"
        "• Снижение затрат на продакшн в 5–10 раз\n\n"
        "⚡ <b>Как это работает:</b>\n"
        "Вы вводите артикул товара — AI создаёт эталон, "
        "на основе которого генерируются фото и видео.\n\n"
        "🚀 Давайте начнём!",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    logger.info("START | sent onboarding welcome to user %s", user.id)
    return ONBOARD_STEP1


# ---------------------------------------------------------------------------
# Шаг 1 → Шаг 2: бюджет на рекламу
# ---------------------------------------------------------------------------

async def step1_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info("ONBOARD_STEP1 | user_id=%s | callback=%s", query.from_user.id, query.data)
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
    logger.info("ONBOARD_STEP2 | user_id=%s | budget=%s", query.from_user.id, query.data)
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
    logger.info("ONBOARD_STEP3 | user_id=%s | articles=%s", query.from_user.id, query.data)
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
    logger.info("ONBOARD_STEP4 | user_id=%s | onboarding complete", query.from_user.id)
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
    mp = "WB" if query.data == "onboard_mp_wb" else "OZON"
    logger.info("ONBOARD_MP_SELECT | user_id=%s | marketplace=%s", query.from_user.id, mp)
    await query.answer()
    context.user_data["onboard_marketplace"] = mp

    label = "Wildberries" if mp == "WB" else "OZON"
    
    # Удаляем старое сообщение с кнопками и отправляем новый запрос
    await query.message.delete()
    msg = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"Введите артикул товара {label}:",
    )
    context.user_data["mp_prompt_msg_id"] = msg.message_id
    return ONBOARD_ARTICLE


# ---------------------------------------------------------------------------
# Ввод артикула → карточка товара → выбор: создать эталон / другой артикул
# ---------------------------------------------------------------------------

async def onboard_article(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message
    chat_id = user_msg.chat.id
    user_id = update.effective_user.id
    raw = user_msg.text.strip()
    marketplace = context.user_data.get("onboard_marketplace", "WB")

    logger.info("ONBOARD_ARTICLE_INPUT | user_id=%s | article=%s | mp=%s", user_id, raw, marketplace)

    # Удаляем сообщение пользователя с артикулом
    try:
        await user_msg.delete()
    except Exception:
        pass

    # Удаляем сообщение "Введите артикул..."
    prompt_id = context.user_data.pop("mp_prompt_msg_id", None)
    if prompt_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=prompt_id)
        except Exception:
            pass

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔍 Загружаю информацию о товаре...")

    name = color = material = ""
    info = {}

    if marketplace == "WB":
        try:
            info = await get_product_info(raw)
        except Exception:
            info = {}

        if not info:
            await status_msg.delete()
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Товар не найден на Wildberries. Проверьте артикул и введите ещё раз:"
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

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Создать эталон — 100 руб.", callback_data="create_ref")],
            [InlineKeyboardButton("🔄 Ввести другой артикул", callback_data="new_article")],
        ])

        # Удаляем "загружаю" → отправляем карточку + кнопки
        await status_msg.delete()
        await update.message.reply_text(
            f"✅ Артикул <code>{raw}</code> найден на Wildberries 🟣\n\n"
            + "\n".join(meta_lines),
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    else:
        await status_msg.delete()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Создать эталон — 100 руб.", callback_data="create_ref")],
            [InlineKeyboardButton("🔄 Ввести другой артикул", callback_data="new_article")],
        ])
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Артикул <code>{raw}</code> сохранён для OZON 🔵",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    await save_article(
        user_id=update.effective_user.id,
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

    # Проверяем, есть ли уже эталон
    existing_ref = await get_reference(user_id, raw)

    if existing_ref:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Переделать эталон — 100 руб.", callback_data="redo_ref")],
            [InlineKeyboardButton("✅ Готово, перейти в меню", callback_data="go_menu")],
        ])
        await update.message.reply_text(
            "Эталон для этого артикула уже создан.\n"
            "Хотите переделать?",
            reply_markup=keyboard,
        )
        return ONBOARD_REF_CHOICE

    return ONBOARD_REF_CHOICE


# ---------------------------------------------------------------------------
# Онбординг: выбор — создать эталон или другой артикул
# ---------------------------------------------------------------------------

async def onboard_ref_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info("ONBOARD_REF_CHOICE | user_id=%s | choice=%s", query.from_user.id, query.data)
    await query.answer()

    articul = context.user_data.get("onboard_article", "")
    product = context.user_data.get("product_info", {})

    if query.data == "new_article":
        # Возвращаемся к вводу артикула (МП запоминаем)
        mp = context.user_data.get("onboard_marketplace", "WB")
        label = "Wildberries" if mp == "WB" else "OZON"
        await query.edit_message_text(f"Введите артикул товара {label}:")
        return ONBOARD_ARTICLE

    if query.data == "go_menu":
        await query.edit_message_text("Отлично! Переходим в главное меню.")
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Выберите действие:",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    if query.data in ("create_ref", "redo_ref"):
        # Удаляем сообщение с кнопками для чистоты чата
        try:
            await query.message.delete()
        except Exception:
            pass

        # Проверка баланса
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

        # Сохраняем в context для следующего шага
        context.user_data["reference_image_data"] = image_data

        # Показываем фото с кнопками
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Подходит", callback_data="ref_ok")],
            [InlineKeyboardButton("🔄 Переделать", callback_data="ref_redo")],
        ])
        sent = await query.message.reply_photo(
            photo=BytesIO(image_data),
            caption="🎨 Эталон готов!\n\nОн должен быть <i>похож</i>, а не 100% копией.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        context.user_data["ref_photo_msg_id"] = sent.message_id
        context.user_data["ref_file_id"] = sent.photo[-1].file_id

        return ONBOARD_REF_FEEDBACK


# ---------------------------------------------------------------------------
# Онбординг: обратная связь — ✅ Подходит / 🔄 Переделать
# ---------------------------------------------------------------------------

async def onboard_ref_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info("ONBOARD_REF_FEEDBACK | user_id=%s | action=%s", query.from_user.id, query.data)
    await query.answer()

    articul = context.user_data.get("onboard_article", "")

    if query.data == "ref_ok":
        user_id = update.effective_user.id
        file_id = context.user_data.get("ref_file_id", "")

        # Сохраняем в БД
        if file_id:
            user_ref_dir = os.path.join(MEDIA_ROOT, str(user_id), "references")
            os.makedirs(user_ref_dir, exist_ok=True)
            file_path = os.path.join(user_ref_dir, f"{articul}.png")

            await save_reference(
                user_id=user_id,
                articul=articul,
                file_id=file_id,
                file_path=file_path,
            )

        # Списываем баланс (только если ещё не списали при переделке)
        if not context.user_data.pop("redo_charged", False):
            new_balance = await deduct_balance(user_id, REFERENCE_COST)
            balance_info = f"\n\nСписано <b>{REFERENCE_COST} руб.</b> Баланс: <b>{new_balance} руб.</b>"
        else:
            balance_info = ""

        # Редактируем caption фото-сообщения
        msg_id = context.user_data.get("ref_photo_msg_id")
        if msg_id:
            await context.bot.edit_message_caption(
                chat_id=query.message.chat.id,
                message_id=msg_id,
                caption=(
                    f"✅ Эталон для <code>{articul}</code> сохранён в базу!\n\n"
                    f"Теперь для создания фото и видео мы будем использовать этот эталон. "
                    f"Вы всегда можете переделать его, если что-то не понравится "
                    f"при создании фото или видеоконтента.{balance_info}"
                ),
                reply_markup=None,
                parse_mode="HTML",
            )

        # Добавляем кнопки под фото
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 Создать фото", callback_data="go_photo")],
            [InlineKeyboardButton("🎬 Создать видео", callback_data="go_video")],
        ])
        await context.bot.edit_message_reply_markup(
            chat_id=query.message.chat.id,
            message_id=msg_id,
            reply_markup=keyboard,
        )
        return ConversationHandler.END

    if query.data == "go_photo":
        # Выбор: одно или несколько фото
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 Одно фото", callback_data="photo_one")],
            [InlineKeyboardButton("📸 Несколько фото", callback_data="photo_multi")],
            [InlineKeyboardButton("↩️ Назад", callback_data="photo_back")],
        ])
        await query.message.reply_text(
            "Сколько фото создать?",
            reply_markup=keyboard,
        )
        return PHOTO_COUNT_CHOICE

    if query.data == "go_video":
        # TODO: Запустить воркфлоу создания видео
        await query.message.reply_text("🎬 Воркфлоу создания видео в разработке.")
        return ConversationHandler.END

    if query.data == "ref_redo":
        msg = await query.message.reply_text(
            "✍️ Напишите что нужно изменить в эталоне.\n"
            "Например: «убрать фон» или «изменить цвет»"
        )
        context.user_data["redo_prompt_msg_id"] = msg.message_id
        return ONBOARD_REDO_FEEDBACK


# ---------------------------------------------------------------------------
# Фото: выбор количества
# ---------------------------------------------------------------------------

async def photo_count_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info("PHOTO_COUNT_CHOICE | user_id=%s | choice=%s", query.from_user.id, query.data)
    await query.answer()

    if query.data == "photo_back":
        # Возврат к фото после эталона — просто завершаем
        await query.edit_message_text("Отмена. Выберите действие в меню.")
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text="Выберите действие:",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    if query.data == "photo_one":
        context.user_data["photo_count"] = 1
        await query.edit_message_text(
            "📝 Укажите критерии для генерации:\n\n"
            "Формат: локация, время года, цвет волос, пожелания\n\n"
            "Например: <i>студия, лето, блонд, улыбка</i>\n\n"
            "Можно оставить пустым — AI подберёт автоматически.",
            parse_mode="HTML",
        )
        return PHOTO_CRITERIA_INPUT

    if query.data == "photo_multi":
        await query.edit_message_text("Сколько фото создать? (1–20)")
        return PHOTO_MULTI_COUNT


# ---------------------------------------------------------------------------
# Фото: ввод количества для мульти-генерации
# ---------------------------------------------------------------------------

async def photo_multi_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    try:
        n = int(raw)
        if not 1 <= n <= 20:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введите число от 1 до 20:")
        return PHOTO_MULTI_COUNT

    context.user_data["photo_count"] = n
    await update.message.reply_text(
        f"📝 Укажите критерии для {n} фото:\n\n"
        "Формат: локация, время года, цвет волос, пожелания\n\n"
        "Например: <i>студия, лето, блонд, улыбка</i>\n\n"
        "Можно оставить пустым — AI подберёт автоматически для каждого.",
        parse_mode="HTML",
    )
    return PHOTO_CRITERIA_INPUT


# ---------------------------------------------------------------------------
# Фото: ввод критериев и генерация
# ---------------------------------------------------------------------------

async def photo_criteria_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.message.chat.id
    criteria = update.message.text.strip()
    count = context.user_data.get("photo_count", 1)
    articul = context.user_data.get("onboard_article", "")
    product = context.user_data.get("product_info", {})
    ref_file_id = context.user_data.get("ref_file_id", "")

    logger.info("PHOTO_CRITERIA | user_id=%s | article=%s | count=%d | criteria=%s",
                user.id, articul, count, criteria)

    # Парсим критерии
    parts = [p.strip() for p in criteria.split(",") if p.strip()]
    location = parts[0] if len(parts) > 0 else ""
    season = parts[1] if len(parts) > 1 else ""
    hair_color = parts[2] if len(parts) > 2 else ""
    extra = parts[3] if len(parts) > 3 else ""

    # Проверка баланса
    cost = PHOTO_COST * count
    db_user = await get_user(user.id)
    balance = db_user["balance"] if db_user else 0

    if balance < cost:
        await update.message.reply_text(
            f"❌ Недостаточно средств.\n\n"
            f"Стоимость: <b>{cost} руб.</b> ({count} × {PHOTO_COST} руб.)\n"
            f"Баланс: <b>{balance} руб.</b>",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # Списываем баланс
    new_balance = await deduct_balance(user.id, cost)

    # Получаем URL эталона для I2I AI
    # TODO: загрузить эталон на S3 или получить URL из file_id
    # Пока используем заглушку
    from config import AI_API_KEY, AI_API_BASE, AI_MODEL
    from services.lifestyle_generator import generate_lifestyle_prompt
    from services.i2i_generator import generate_reference_image

    session = context.bot_data.get("http_session")
    if not session:
        await update.message.reply_text("⚠️ Техническая ошибка.")
        return ConversationHandler.END

    # Для мульти-генерации — цикл
    for i in range(count):
        status = await update.message.reply_text(
            f"🔄 Генерация фото {i+1}/{count}..."
        )

        # T2T AI — генерация промпта lifestyle
        prompt = await generate_lifestyle_prompt(
            session=session,
            name=product.get("name", ""),
            color=product.get("color", ""),
            material=product.get("material", ""),
            location=location,
            season=season,
            hair_color=hair_color,
            extra=extra,
            api_key=AI_API_KEY,
            api_base_url=AI_API_BASE,
            model=AI_MODEL,
        )

        if not prompt:
            await status.edit_text(f"❌ Ошибка генерации промпта (фото {i+1}).")
            continue

        # TODO: I2I AI — нужно загрузить эталон и передать URL
        # Пока заглушка — используем тот же механизм
        # image_url = await generate_reference_image(...)

        # TODO: скачать и отправить фото
        # Пока отправляем тот же placeholder
        await status.edit_text(
            f"✅ Фото {i+1}/{count} готово!\n\n"
            f"Списано {cost} руб. Баланс: {new_balance} руб.\n\n"
            "# TODO: показать сгенерированное фото"
        )

    await context.bot.send_message(
        chat_id=chat_id,
        text="Выберите действие:",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Онбординг: ввод фидбека для переделки
# ---------------------------------------------------------------------------

async def onboard_redo_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message
    feedback = user_msg.text.strip()
    user_id = update.effective_user.id
    chat_id = user_msg.chat.id
    articul = context.user_data.get("onboard_article", "")
    product = context.user_data.get("product_info", {})
    logger.info("ONBOARD_REDO_INPUT | user_id=%s | article=%s | feedback=%s", user_id, articul, feedback)

    # Удаляем сообщение пользователя и подсказку
    try:
        await user_msg.delete()
    except Exception:
        pass
    prompt_msg_id = context.user_data.pop("redo_prompt_msg_id", None)
    if prompt_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=prompt_msg_id)
        except Exception:
            pass

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔄 Перегенерирую промпт с учётом ваших пожеланий...")
    context.user_data["redo_status_msg_id"] = status_msg.message_id

    session = context.bot_data.get("http_session")
    if not session:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Техническая ошибка.")
        return ConversationHandler.END

    from config import AI_API_KEY, AI_API_BASE, AI_MODEL
    from services.reference_generator import generate_reference_prompt
    from services.i2i_generator import generate_reference_image

    # T2T AI — генерируем новый промпт с пожеланиями
    prompt = await generate_reference_prompt(
        session=session,
        name=product.get("name", ""),
        color=product.get("color", ""),
        material=product.get("material", ""),
        api_key=AI_API_KEY,
        api_base_url=AI_API_BASE,
        model=AI_MODEL,
        additional_requirements=feedback,
    )

    if not prompt:
        await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка генерации промпта.")
        return ConversationHandler.END

    context.user_data["reference_prompt"] = prompt

    # I2I AI — генерируем изображение с новым промптом
    wb_images = context.user_data.get("wb_images", [])
    if not wb_images:
        await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось найти фото товара.")
        return ConversationHandler.END

    image_url = await generate_reference_image(
        session=session,
        api_base=AI_API_BASE,
        api_key=AI_API_KEY,
        image_urls=wb_images[:3],
        prompt=prompt,
    )

    if not image_url:
        await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка генерации изображения.")
        return ConversationHandler.END

    try:
        async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=15)) as img_resp:
            image_data = await img_resp.read()
    except Exception as e:
        logger.error("Failed to download image: %s", e)
        await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка загрузки изображения.")
        return ConversationHandler.END

    # Удаляем статус "Перегенерирую..."
    status_msg_id = context.user_data.pop("redo_status_msg_id", None)
    if status_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
        except Exception:
            pass

    # Удаляем старое фото
    old_photo_msg_id = context.user_data.pop("ref_photo_msg_id", None)
    if old_photo_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_photo_msg_id)
        except Exception:
            pass

    # Отправляем новое фото
    context.user_data["reference_image_data"] = image_data

    # Списываем за переделку
    new_balance = await deduct_balance(user_id, REFERENCE_COST)
    context.user_data["redo_charged"] = True

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подходит", callback_data="ref_ok")],
        [InlineKeyboardButton("🔄 Ещё раз", callback_data="ref_redo")],
    ])
    sent = await context.bot.send_photo(
        chat_id=chat_id,
        photo=BytesIO(image_data),
        caption=(
            f"🎨 Вот новый вариант!\n\n"
            f"Он должен быть <i>похож</i>, а не 100% копией.\n\n"
            f"Списано <b>{REFERENCE_COST} руб.</b> Баланс: <b>{new_balance} руб.</b>"
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    context.user_data["ref_photo_msg_id"] = sent.message_id
    context.user_data["ref_file_id"] = sent.photo[-1].file_id

    return ONBOARD_REF_FEEDBACK


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
            ONBOARD_REF_CHOICE: [CallbackQueryHandler(onboard_ref_choice, pattern="^(create_ref|redo_ref|new_article|go_menu)$")],
            ONBOARD_REF_FEEDBACK: [CallbackQueryHandler(onboard_ref_feedback, pattern="^(ref_ok|ref_redo|go_photo|go_video)$")],
            ONBOARD_REDO_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_redo_feedback)],
            PHOTO_COUNT_CHOICE: [CallbackQueryHandler(photo_count_choice, pattern="^(photo_one|photo_multi|photo_back)$")],
            PHOTO_MULTI_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, photo_multi_count)],
            PHOTO_CRITERIA_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, photo_criteria_input)],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        per_message=False,
    )
