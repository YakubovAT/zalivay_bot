import logging
import os
from io import BytesIO
from urllib.parse import quote

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

from database import ensure_user, is_registered, save_registration, reset_registration, save_article, save_reference, get_user, get_reference, deduct_balance, get_user_stats
from handlers.menu import main_menu, BTN_RESTART, BTN_PROFILE, BTN_PRICING, BTN_HELP, BTN_ETALON, BTN_PHOTO, BTN_VIDEO
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
PHOTO_MULTI_COUNT = 21     # Ввод количества для мульти-генерации

# ---------------------------------------------------------------------------
# Перезапуск онбординга
# ---------------------------------------------------------------------------

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("RESTART | user_id=%s | username=%s", user.id, user.username)
    # НЕ удаляем данные из БД — баланс, эталоны и артикулы сохраняются
    # Только перезапускаем код и обновляем репозиторий
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

    # Статистика пользователя
    stats = await get_user_stats(user.id)

    # Сначала — приветствие + нижнее меню
    await update.message.reply_text(
        f"Привет, {user.first_name}!",
        reply_markup=main_menu(),
    )

    # Затем — описание + кнопка "Дальше →"
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
        f"Сейчас у Вас <b>{stats['references']}</b> эталон(ов) товаров, "
        f"<b>{stats['photos']}</b> изготовленных фото и "
        f"<b>{stats['videos']}</b> изготовленных видео в базе, "
        f"баланс: <b>{stats['balance']}</b> руб.\n\n"
        "🚀 Давайте начнём!",
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    logger.info("START | sent onboarding welcome to user %s", user.id)
    return ONBOARD_STEP1


# ---------------------------------------------------------------------------
# Шаг 1 → сразу к сохранению + главное меню (шаги с бюджетом/артикулами временно отключены)
# ---------------------------------------------------------------------------

async def step1_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info("ONBOARD_STEP1 | user_id=%s | callback=%s | skipping to finish", query.from_user.id, query.data)
    await query.answer()

    # Шаги с бюджетом и количеством артикулов временно отключены — сразу переходим к завершению
    user_id = update.effective_user.id
    ad_budget = ""
    articles_count = ""

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
            meta_lines.append(f'📦 <a href="https://www.wildberries.ru/catalog/{raw}/detail.aspx">{name}</a>')
        if info.get("brand"):
            meta_lines.append(f'👤 <a href="https://www.wildberries.ru/catalog?search={quote(info["brand"])}">{info["brand"]}</a>')
        if color:
            meta_lines.append(f"🎨 {color[:1].upper() + color[1:]}")
        if material:
            meta_lines.append(f"🧵 {material}")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Создать эталон — 100 руб.", callback_data="create_ref")],
            [InlineKeyboardButton("🔄 Ввести другой артикул", callback_data="new_article")],
        ])

        # Удаляем "загружаю" → отправляем карточку + кнопки
        await status_msg.delete()
        _card_text = (
            f"✅ Артикул <code>{raw}</code> найден на Wildberries 🟣\n\n"
            + "\n".join(meta_lines)
        )
        _images = info.get("images", [])
        if _images:
            await update.message.reply_photo(
                photo=_images[0],
                caption=_card_text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                _card_text,
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
        chat_id = query.message.chat.id
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(chat_id=chat_id, text=f"Введите артикул товара {label}:")
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
        from services.reference_t2t import generate_reference_prompt
        from services.reference_i2i import generate_reference_image

        t2t_result = await generate_reference_prompt(
            session=session,
            name=product.get("name", ""),
            color=product.get("color", ""),
            material=product.get("material", ""),
            api_key=AI_API_KEY,
            api_base_url=AI_API_BASE,
            model=AI_MODEL,
        )

        if not t2t_result:
            await query.message.reply_text("❌ Ошибка генерации промпта.")
            return ConversationHandler.END

        context.user_data["reference_prompt"] = t2t_result["prompt"]
        context.user_data["product_category"] = t2t_result["category"]

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
            prompt=t2t_result["prompt"],
        )

        if not image_url:
            await query.message.reply_text("❌ Ошибка генерации изображения.")
            return ConversationHandler.END

        context.user_data["reference_image_url"] = image_url

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
                reference_image_url=context.user_data.get("reference_image_url", ""),
                category=context.user_data.get("product_category", ""),
                reference_prompt=context.user_data.get("reference_prompt", ""),
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

        # Добавляем кнопки под фото для действий после эталона
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 Создать фото", callback_data="go_photo")],
            [InlineKeyboardButton("🎬 Создать видео", callback_data="go_video")],
        ])
        await context.bot.edit_message_reply_markup(
            chat_id=query.message.chat.id,
            message_id=msg_id,
            reply_markup=keyboard,
        )
        return ONBOARD_REF_FEEDBACK

    if query.data == "go_photo":
        context.user_data["_onboard_user_id"] = query.from_user.id
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
        await query.edit_message_text("Отмена. Выберите действие в меню.")
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text="Выберите действие:",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    if query.data == "photo_one":
        context.user_data["photo_count"] = 1
        # Сразу переходим к генерации — критерии не нужны, промпты генерируются локально
        return await _generate_photos_onboard(query.message.chat.id, context, 1)

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
    return await _generate_photos_onboard(update.message.chat.id, context, n)


# ---------------------------------------------------------------------------
# Фото: генерация — запись тасков в очередь (онбординг)
# ---------------------------------------------------------------------------

async def _generate_photos_onboard(chat_id, context, count):
    """Аналог _generate_photos из menu.py, но для онбординг-пути."""
    articul = context.user_data.get("onboard_article", "")
    product = context.user_data.get("product_info", {})
    category = context.user_data.get("product_category", "верх")
    user_id = context.user_data.get("_onboard_user_id")

    if not user_id:
        logger.error("PHOTO_GEN_ONBOARD | user_id not set in context!")
        return ConversationHandler.END

    from database import get_user, deduct_balance, create_task
    from services.prompt_generator_cloth import generate_photo_prompts

    # Проверка баланса
    cost = PHOTO_COST * count
    db_user = await get_user(user_id)
    balance = db_user["balance"] if db_user else 0

    if balance < cost:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно средств.\n\n"
                 f"Стоимость: <b>{cost} руб.</b> ({count} × {PHOTO_COST} руб.)\n"
                 f"Баланс: <b>{balance} руб.</b>\n\n"
                 f"Пополните баланс и попробуйте снова.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # Генерируем N промптов локально
    prompts = generate_photo_prompts(
        name=product.get("name", ""),
        color=product.get("color", ""),
        material=product.get("material", ""),
        category=category,
        count=count,
    )

    # Списываем баланс
    new_balance = await deduct_balance(user_id, cost)

    # Записываем N тасков в очередь
    for prompt in prompts:
        await create_task(
            user_id=user_id,
            chat_id=chat_id,
            task_type="photo",
            articul=articul,
            prompt=prompt,
        )

    logger.info("PHOTO_GEN_ONBOARD | user_id=%d | articul=%s | tasks=%d | cost=%d",
                user_id, articul, count, cost)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ <b>{count} фото</b> поставлено в очередь!\n\n"
             f"Артикул: <code>{articul}</code>\n"
             f"Категория: <b>{category}</b>\n\n"
             f"Списано <b>{cost} руб.</b> Баланс: <b>{new_balance} руб.</b>\n\n"
             f"Фото будут отправляться по мере готовности 🔄",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Видео — выбор маркетплейса (TODO)
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
    from services.reference_t2t import generate_reference_prompt
    from services.reference_i2i import generate_reference_image

    # T2T AI — генерируем новый промпт с пожеланиями
    t2t_result = await generate_reference_prompt(
        session=session,
        name=product.get("name", ""),
        color=product.get("color", ""),
        material=product.get("material", ""),
        api_key=AI_API_KEY,
        api_base_url=AI_API_BASE,
        model=AI_MODEL,
        additional_requirements=feedback,
    )

    if not t2t_result:
        await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка генерации промпта.")
        return ConversationHandler.END

    context.user_data["reference_prompt"] = t2t_result["prompt"]
    context.user_data["product_category"] = t2t_result["category"]

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
        prompt=t2t_result["prompt"],
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
# Fallbacks: обработка кнопок меню из любого состояния
# ---------------------------------------------------------------------------

async def _menu_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """При нажатии кнопки меню — отменяем текущий разговор и показываем главное меню."""
    text = update.message.text
    logger.info("REGISTRATION_FALLBACK | user_id=%s | button=%s", update.effective_user.id, text)

    # Кнопки потока — отмена и показ меню
    if text in (BTN_ETALON, BTN_PHOTO, BTN_VIDEO):
        await update.message.reply_text("Выберите действие:", reply_markup=main_menu())

    # Действия с прямым ответом
    elif text == BTN_PROFILE:
        from handlers.menu import profile
        return await profile(update, context)
    elif text == BTN_PRICING:
        from handlers.menu import pricing
        return await pricing(update, context)
    elif text == BTN_HELP:
        from handlers.menu import help_cmd
        return await help_cmd(update, context)

    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

def build_registration_handler() -> ConversationHandler:
    # Все кнопки главного меню — fallback из любого состояния
    menu_buttons = filters.Regex(
        f"^({BTN_PROFILE}|{BTN_PRICING}|{BTN_HELP}|{BTN_ETALON}|{BTN_PHOTO}|{BTN_VIDEO}|{BTN_RESTART})$"
    )

    return ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.Regex(f"^{BTN_RESTART}$"), restart),
        ],
        states={
            ONBOARD_STEP1:     [CallbackQueryHandler(step1_next,       pattern="^onboard_step1$")],
            # ONBOARD_STEP2, ONBOARD_STEP3, ONBOARD_STEP4 — временно отключены
            ONBOARD_SELECT_MP: [CallbackQueryHandler(onboard_select_mp, pattern="^onboard_mp_(wb|ozon)$")],
            ONBOARD_ARTICLE:   [MessageHandler(filters.TEXT & ~menu_buttons & ~filters.COMMAND, onboard_article)],
            ONBOARD_REF_CHOICE: [CallbackQueryHandler(onboard_ref_choice, pattern="^(create_ref|redo_ref|new_article|go_menu)$")],
            ONBOARD_REF_FEEDBACK: [CallbackQueryHandler(onboard_ref_feedback, pattern="^(ref_ok|ref_redo|go_photo|go_video)$")],
            ONBOARD_REDO_FEEDBACK: [MessageHandler(filters.TEXT & ~menu_buttons & ~filters.COMMAND, onboard_redo_feedback)],
            PHOTO_COUNT_CHOICE: [CallbackQueryHandler(photo_count_choice, pattern="^(photo_one|photo_multi|photo_back)$")],
            PHOTO_MULTI_COUNT: [MessageHandler(filters.TEXT & ~menu_buttons & ~filters.COMMAND, photo_multi_count)],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            MessageHandler(menu_buttons, _menu_fallback),
        ],
        per_message=False,
    )
