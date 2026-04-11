"""
onboarding.py

Поток регистрации / онбординга пользователя.
Паттерн «одно окно»: баннер 620×50 + текст + кнопки.
"""

import logging
import os
from io import BytesIO

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters as tg_filters,
)

from database import (
    ensure_user, is_registered, save_registration, reset_registration,
    save_article, save_reference, get_user, get_reference, get_user_stats,
    deduct_balance,
)
from handlers.keyboards import (
    BTN_PROFILE, BTN_PHOTO, BTN_VIDEO, BTN_ETALON, BTN_PRICING, BTN_HELP, BTN_RESTART,
    MENU_BUTTONS, mp_select_keyboard, etalon_create_keyboard,
    etalon_existing_keyboard, etalon_feedback_keyboard, etalon_done_keyboard, back_button,
)
from handlers.flows import (
    clean_user_message, clean_bot_message, store_msg_id, pop_msg_id,
    send_screen, edit_screen, replace_screen, safe_delete,
)
from config import REFERENCE_COST, AI_API_KEY, AI_API_BASE, AI_MODEL, I2I_API_KEY, I2I_API_BASE
from services.wb_parser import get_product_info
from services.reference_t2t import generate_reference_prompt
from services.reference_i2i import generate_reference_image
from services.media_storage import ensure_user_media_dirs, MEDIA_ROOT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Состояния
# ---------------------------------------------------------------------------

ONBOARD_SELECT_MP = 14
ONBOARD_ARTICLE = 15
ONBOARD_REF_CHOICE = 16
ONBOARD_REF_FEEDBACK = 17
ONBOARD_REDO_FEEDBACK = 18
PHOTO_COUNT_CHOICE = 19
PHOTO_MULTI_COUNT = 21


# ---------------------------------------------------------------------------
# Перезапуск
# ---------------------------------------------------------------------------

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("RESTART | user_id=%s", user.id)
    await update.message.reply_text("🔄 Обновление и перезапуск бота...")

    import asyncio
    import subprocess
    await asyncio.sleep(1)
    subprocess.Popen(
        "sleep 2 && cd /var/www/bots/Zalivai_bot && git pull && systemctl restart zalivai-bot",
        shell=True, start_new_session=True,
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("START | user_id=%s", user.id)
    await ensure_user(user.id, user.username)
    await save_registration(user.id, "", "")
    ensure_user_media_dirs(user.id)

    stats = await get_user_stats(user.id)

    text = (
        f"Привет, <b>{user.first_name}</b>! 👋\n\n"
        "🤖 <b>AI-ассистент для селлеров маркетплейсов</b>\n\n"
        "Автоматизированный бот, который создаёт фото и видео для социальных сетей на основе ваших товаров.\n\n"
        "📌 <b>Какие задачи решает:</b>\n"
        "• Создание эталонных фото товаров без фотографа\n"
        "• Генерация lifestyle-контента для рекламы в соцсетях\n"
        "• Снижение затрат на продакшн в 5–10 раз\n\n"
        "⚡ <b>Как это работает:</b>\n"
        "Вы вводите артикул товара — AI создаёт эталон, "
        "на основе которого генерируются фото и видео.\n\n"
        f"Сейчас у Вас <b>{stats['references']}</b> эталон(ов), "
        f"<b>{stats['photos']}</b> фото и "
        f"<b>{stats['videos']}</b> видео в базе, "
        f"баланс: <b>{stats['balance']}</b> руб.\n\n"
        "🚀 Давайте начнём! Выберите маркетплейс:"
    )

    await send_screen(
        chat_id=user.id,
        context=context,
        text=text,
        reply_markup=mp_select_keyboard(),
        parse_mode="HTML",
    )

    return ONBOARD_SELECT_MP


# ---------------------------------------------------------------------------
# Выбор МП
# ---------------------------------------------------------------------------

async def onboard_select_mp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mp = "WB" if query.data == "mp_wb" else "OZON"
    context.user_data["onboard_marketplace"] = mp
    logger.info("ONBOARD_MP | user=%s mp=%s", query.from_user.id, mp)

    label = "Wildberries" if mp == "WB" else "OZON"
    await query.message.delete()
    msg = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"Введите артикул товара {label}:",
    )
    store_msg_id(context, "mp_prompt_msg_id", msg.message_id)
    return ONBOARD_ARTICLE


# ---------------------------------------------------------------------------
# Ввод артикула
# ---------------------------------------------------------------------------

async def onboard_article(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message
    chat_id = user_msg.chat.id
    user_id = update.effective_user.id
    raw = user_msg.text.strip()
    marketplace = context.user_data.get("onboard_marketplace", "WB")

    logger.info("ONBOARD_ARTICLE | user=%s art=%s mp=%s", user_id, raw, marketplace)

    await clean_user_message(update, context)
    prompt_id = pop_msg_id(context, "mp_prompt_msg_id")
    if prompt_id:
        await safe_delete(chat_id, prompt_id, context)

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔍 Загружаю информацию о товаре...")

    info = {}
    if marketplace == "WB":
        try:
            info = await get_product_info(raw)
        except Exception:
            info = {}

    await safe_delete(chat_id, status_msg.message_id, context)

    if not info and marketplace == "WB":
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Товар не найден. Проверьте артикул:",
        )
        return ONBOARD_ARTICLE

    name = info.get("name", "") if info else ""
    color = info["colors"][0] if info and info.get("colors") else ""
    material = info.get("material", "") if info else ""

    meta_lines = []
    if name:
        meta_lines.append(f'📦 <a href="https://www.wildberries.ru/catalog/{raw}/detail.aspx">{name}</a>')
    if info and info.get("brand"):
        meta_lines.append(f'👤 {info["brand"]}')
    if color:
        meta_lines.append(f"🎨 {color[:1].upper() + color[1:]}")
    if material:
        meta_lines.append(f"🧵 {material}")

    await save_article(
        user_id=user_id, article_code=raw, marketplace=marketplace,
        name=name, color=color, material=material,
    )

    context.user_data["onboard_article"] = raw
    context.user_data["product_info"] = {"name": name, "color": color, "material": material}
    context.user_data["wb_images"] = info.get("images", [])[:5] if info else []

    existing_ref = await get_reference(user_id, raw)

    card_text = (
        f"✅ Артикул <code>{raw}</code> найден на Wildberries 🟣\n\n"
        + "\n".join(meta_lines)
    )

    if existing_ref:
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text=card_text + "\n\nЭталон уже есть. Переделать?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Переделать эталон", callback_data="redo_ref")],
                [InlineKeyboardButton("↩️ Выбрать другой МП", callback_data="back_to_mp")],
            ]),
            parse_mode="HTML",
        )
    else:
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text=card_text + "\n\nСоздать эталон?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Создать эталон", callback_data="create_ref")],
                [InlineKeyboardButton("🔄 Другой артикул", callback_data="new_article")],
                [InlineKeyboardButton("↩️ Выбрать другой МП", callback_data="back_to_mp")],
            ]),
            parse_mode="HTML",
        )

    return ONBOARD_REF_CHOICE


# ---------------------------------------------------------------------------
# Выбор: создать / другой / в меню
# ---------------------------------------------------------------------------

async def onboard_ref_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    if query.data == "new_article":
        mp = context.user_data.get("onboard_marketplace", "WB")
        label = "Wildberries" if mp == "WB" else "OZON"
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(chat_id=chat_id, text=f"Введите артикул ({label}):")
        return ONBOARD_ARTICLE

    if query.data == "go_menu":
        await query.edit_message_text("✅ Готово! Используйте кнопки inline-меню для навигации.")
        return ConversationHandler.END

    if query.data == "back_to_mp":
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text="Выберите маркетплейс:",
            reply_markup=mp_select_keyboard(),
        )
        return ONBOARD_SELECT_MP

    if query.data in ("create_ref", "redo_ref"):
        try:
            await query.message.delete()
        except Exception:
            pass
        return await _generate_onboard_ref(query, context)

    return ONBOARD_REF_CHOICE


async def _generate_onboard_ref(query, context: ContextTypes.DEFAULT_TYPE):
    """Фоновая генерация эталона в онбординге."""
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    articul = context.user_data.get("onboard_article", "")
    product = context.user_data.get("product_info", {})
    wb_images = context.user_data.get("wb_images", [])

    db_user = await get_user(user_id)
    balance = db_user["balance"] if db_user else 0

    if balance < REFERENCE_COST:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"❌ Недостаточно средств.\n\n"
                f"Стоимость: <b>{REFERENCE_COST} руб.</b>\n"
                f"Баланс: <b>{balance} руб.</b>"
            ),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ <b>Генерация эталона...</b>\n\nАртикул: <code>{articul}</code>",
        parse_mode="HTML",
    )

    async def _background():
        session = context.bot_data.get("http_session")
        if not session:
            await context.bot.edit_message_text(
                chat_id=user_id, message_id=status_msg.message_id,
                text="⚠️ Техническая ошибка.",
            )
            return

        try:
            await context.bot.edit_message_text(
                chat_id=user_id, message_id=status_msg.message_id,
                text=f"⏳ <b>Генерация эталона...</b>\n\n📝 Создаю промпт...",
                parse_mode="HTML",
            )

            t2t_result = await generate_reference_prompt(
                session=session, name=product.get("name", ""),
                color=product.get("color", ""), material=product.get("material", ""),
                api_key=AI_API_KEY, api_base_url=AI_API_BASE, model=AI_MODEL,
            )
            if not t2t_result:
                await context.bot.edit_message_text(
                    chat_id=user_id, message_id=status_msg.message_id,
                    text="❌ Ошибка промпта.",
                )
                return

            context.user_data["reference_prompt"] = t2t_result["prompt"]
            context.user_data["product_category"] = t2t_result["category"]

            await context.bot.edit_message_text(
                chat_id=user_id, message_id=status_msg.message_id,
                text=f"⏳ <b>Генерация...</b>\n\n🎨 Создаю изображение ИИ...\n\n⏱ 1–2 мин",
                parse_mode="HTML",
            )

            new_balance = await deduct_balance(user_id, REFERENCE_COST)

            image_url = await generate_reference_image(
                session=session, api_base=I2I_API_BASE, api_key=I2I_API_KEY,
                image_urls=wb_images[:3], prompt=t2t_result["prompt"],
            )
            if not image_url:
                await context.bot.edit_message_text(
                    chat_id=user_id, message_id=status_msg.message_id,
                    text="❌ Ошибка генерации.",
                )
                return

            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as img_resp:
                image_data = await img_resp.read()
                ct = img_resp.headers.get("Content-Type", "image/png")
                ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(ct, "png")

            user_ref_dir = os.path.join(MEDIA_ROOT, str(user_id), "references")
            os.makedirs(user_ref_dir, exist_ok=True)
            file_path = os.path.join(user_ref_dir, f"{articul}.{ext}")
            with open(file_path, "wb") as f:
                f.write(image_data)

            sent = await context.bot.send_photo(chat_id=user_id, photo=BytesIO(image_data))
            file_id = sent.photo[-1].file_id

            await save_reference(
                user_id=user_id, articul=articul, file_id=file_id, file_path=file_path,
                reference_image_url=image_url,
                category=context.user_data.get("product_category", ""),
                reference_prompt=context.user_data.get("reference_prompt", ""),
            )

            try:
                await context.bot.delete_message(chat_id=user_id, message_id=status_msg.message_id)
            except Exception:
                pass

            ref_msg = await context.bot.send_photo(
                chat_id=user_id, photo=BytesIO(image_data),
                caption=(
                    f"🎨 <b>Эталон для {articul} готов!</b>\n\n"
                    f"Списано <b>{REFERENCE_COST} руб.</b> Баланс: <b>{new_balance} руб.</b>"
                ),
                reply_markup=etalon_feedback_keyboard(),
                parse_mode="HTML",
            )
            store_msg_id(context, "ref_photo_msg_id", ref_msg.message_id)
            store_msg_id(context, "ref_file_id", file_id)

        except Exception as e:
            logger.error("ONBOARD_REF_GEN_FAILED: %s", e)

    import asyncio
    task = asyncio.create_task(_background())
    context.bot_data.setdefault("bg_tasks", set()).add(task)
    task.add_done_callback(context.bot_data["bg_tasks"].discard)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Фидбек
# ---------------------------------------------------------------------------

async def onboard_ref_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    articul = context.user_data.get("onboard_article", "")

    if query.data == "ref_ok":
        msg_id = context.user_data.get("ref_photo_msg_id")
        if msg_id:
            await context.bot.edit_message_caption(
                chat_id=chat_id, message_id=msg_id,
                caption=f"✅ Эталон для <code>{articul}</code> сохранён!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📸 Создать фото", callback_data="go_photo")],
                    [InlineKeyboardButton("🎬 Создать видео", callback_data="go_video")],
                ]),
                parse_mode="HTML",
            )
        return ONBOARD_REF_FEEDBACK

    if query.data == "go_photo":
        # TODO: переход к фото
        await context.bot.send_message(chat_id=chat_id, text="📸 Переход к фото...")
        return ConversationHandler.END

    if query.data == "go_video":
        await context.bot.send_message(chat_id=chat_id, text="🎬 Переход к видео...")
        return ConversationHandler.END

    if query.data == "ref_redo":
        msg = await context.bot.send_message(chat_id=chat_id, text="✍️ Напишите что изменить:")
        store_msg_id(context, "redo_prompt_msg_id", msg.message_id)
        return ONBOARD_REDO_FEEDBACK

    return ONBOARD_REF_FEEDBACK


# ---------------------------------------------------------------------------
# Фидбек — переделка
# ---------------------------------------------------------------------------

async def onboard_redo_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feedback = update.message.text.strip()
    user_id = update.effective_user.id
    chat_id = update.message.chat.id
    articul = context.user_data.get("onboard_article", "")

    logger.info("ONBOARD_REDO | user=%s art=%s feedback=%s", user_id, articul, feedback)

    await clean_user_message(update, context)
    prompt_id = pop_msg_id(context, "redo_prompt_msg_id")
    if prompt_id:
        await safe_delete(chat_id, prompt_id, context)

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔄 Перегенерирую...")
    context.user_data["redo_status_msg_id"] = status_msg.message_id

    session = context.bot_data.get("http_session")
    if not session:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Ошибка.")
        return ConversationHandler.END

    product = context.user_data.get("product_info", {})

    t2t_result = await generate_reference_prompt(
        session=session, name=product.get("name", ""),
        color=product.get("color", ""), material=product.get("material", ""),
        api_key=AI_API_KEY, api_base_url=AI_API_BASE, model=AI_MODEL,
        additional_requirements=feedback,
    )
    if not t2t_result:
        await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка промпта.")
        return ConversationHandler.END

    context.user_data["reference_prompt"] = t2t_result["prompt"]
    context.user_data["product_category"] = t2t_result["category"]

    wb_images = context.user_data.get("wb_images", [])
    image_url = await generate_reference_image(
        session=session, api_base=I2I_API_BASE, api_key=I2I_API_KEY,
        image_urls=wb_images[:3], prompt=t2t_result["prompt"],
    )
    if not image_url:
        await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка генерации.")
        return ConversationHandler.END

    async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as img_resp:
        image_data = await img_resp.read()

    status_id = pop_msg_id(context, "redo_status_msg_id")
    if status_id:
        await safe_delete(chat_id, status_id, context)

    old_id = pop_msg_id(context, "ref_photo_msg_id")
    if old_id:
        await safe_delete(chat_id, old_id, context)

    new_balance = await deduct_balance(user_id, REFERENCE_COST)

    sent = await context.bot.send_photo(
        chat_id=chat_id, photo=BytesIO(image_data),
        caption=f"🎨 Новый вариант!\n\nСписано <b>{REFERENCE_COST} руб.</b> Баланс: <b>{new_balance} руб.</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Подходит", callback_data="ref_ok")],
            [InlineKeyboardButton("🔄 Ещё раз", callback_data="ref_redo")],
        ]),
        parse_mode="HTML",
    )
    store_msg_id(context, "ref_photo_msg_id", sent.message_id)
    store_msg_id(context, "ref_file_id", sent.photo[-1].file_id)

    return ONBOARD_REF_FEEDBACK


# ---------------------------------------------------------------------------
# Выбор количества фото
# ---------------------------------------------------------------------------

async def photo_count_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    if query.data == "go_photo":
        context.user_data["_onboard_user_id"] = query.from_user.id
        # Показать выбор количества фото
        await context.bot.send_message(
            chat_id=chat_id,
            text="Сколько фото создать?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📸 Одно фото", callback_data="photo_one")],
                [InlineKeyboardButton("📸 Несколько фото", callback_data="photo_multi")],
            ]),
        )
        return PHOTO_COUNT_CHOICE

    if query.data == "go_video":
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎬 Генерация видео пока в разработке.",
        )
        return ConversationHandler.END

    if query.data == "photo_one":
        context.user_data["photo_count"] = 1
        context.user_data["_onboard_user_id"] = query.from_user.id
        return await _generate_photos_onboard(chat_id, context, 1)

    if query.data == "photo_multi":
        await context.bot.send_message(chat_id=chat_id, text="Сколько фото? (1–20)")
        return PHOTO_MULTI_COUNT

    return PHOTO_COUNT_CHOICE


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
    context.user_data["_onboard_user_id"] = update.effective_user.id
    return await _generate_photos_onboard(update.message.chat.id, context, n)


async def _generate_photos_onboard(chat_id, context: ContextTypes.DEFAULT_TYPE, count: int):
    articul = context.user_data.get("onboard_article", "")
    product = context.user_data.get("product_info", {})
    category = context.user_data.get("product_category", "верх")
    user_id = context.user_data.get("_onboard_user_id")

    if not user_id:
        logger.error("PHOTO_ONBOARD | no user_id")
        return ConversationHandler.END

    from config import PHOTO_COST
    cost = PHOTO_COST * count
    db_user = await get_user(user_id)
    balance = db_user["balance"] if db_user else 0

    if balance < cost:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно средств.\n\nСтоимость: <b>{cost} руб.</b>\nБаланс: <b>{balance} руб.</b>",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    from services.prompt_generator_cloth import generate_photo_prompts
    prompts = generate_photo_prompts(
        name=product.get("name", ""), color=product.get("color", ""),
        material=product.get("material", ""), category=category, count=count,
    )

    new_balance = await deduct_balance(user_id, cost)

    from database import create_task
    for prompt in prompts:
        await create_task(
            user_id=user_id, chat_id=chat_id,
            task_type="photo", articul=articul, prompt=prompt,
        )

    logger.info("PHOTO_ONBOARD | user=%d art=%s count=%d cost=%d", user_id, articul, count, cost)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ <b>{count} фото</b> в очереди!\n\n"
            f"Артикул: <code>{articul}</code>\n"
            f"Категория: <b>{category}</b>\n\n"
            f"Списано <b>{cost} руб.</b> Баланс: <b>{new_balance} руб.</b>"
        ),
        parse_mode="HTML",
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

async def _menu_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("ONBOARD_FALLBACK | btn=%s", update.message.text)
    if update.message.text == BTN_PROFILE:
        from handlers.flows.profile import profile
        return await profile(update, context)
    if update.message.text == BTN_PRICING:
        from handlers.flows.pricing import pricing
        return await pricing(update, context)
    if update.message.text == BTN_HELP:
        from handlers.flows.help_cmd import help_cmd
        return await help_cmd(update, context)

    await update.message.reply_text("Выберите действие:")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------

def build_onboarding_handler() -> ConversationHandler:
    any_menu = tg_filters.Regex(f"^({'|'.join(MENU_BUTTONS)})$")

    return ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(tg_filters.Regex(f"^{BTN_RESTART}$"), restart),
        ],
        states={
            ONBOARD_SELECT_MP: [CallbackQueryHandler(onboard_select_mp, pattern="^mp_(wb|ozon)$")],
            ONBOARD_ARTICLE: [MessageHandler(tg_filters.TEXT & ~any_menu, onboard_article)],
            ONBOARD_REF_CHOICE: [CallbackQueryHandler(onboard_ref_choice, pattern="^(create_ref|redo_ref|new_article|go_menu|back_to_mp)$")],
            ONBOARD_REF_FEEDBACK: [CallbackQueryHandler(onboard_ref_feedback, pattern="^(ref_ok|ref_redo|go_photo|go_video)$")],
            ONBOARD_REDO_FEEDBACK: [MessageHandler(tg_filters.TEXT & ~any_menu, onboard_redo_feedback)],
            PHOTO_COUNT_CHOICE: [CallbackQueryHandler(photo_count_choice, pattern="^(go_photo|go_video)$")],
            PHOTO_MULTI_COUNT: [MessageHandler(tg_filters.TEXT & ~any_menu, photo_multi_count)],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            MessageHandler(any_menu, _menu_fallback),
        ],
        per_message=False,
    )
