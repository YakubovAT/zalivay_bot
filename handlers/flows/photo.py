"""
photo.py

Поток создания фото товара.
Паттерн «одно окно»: баннер 620×50 + текст + кнопки, edit вместо send.
"""

import logging
from urllib.parse import quote

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler,
    filters as tg_filters,
)

from database import (
    ensure_user, get_user, get_reference, get_user_articles,
    save_article, save_reference, deduct_balance, get_user_stats, create_task,
)
from handlers.keyboards import (
    BTN_PHOTO, BTN_PROFILE, BTN_VIDEO, BTN_ETALON, BTN_PRICING, BTN_HELP, BTN_RESTART,
    MENU_BUTTONS, main_menu, mp_select_keyboard, photo_count_keyboard, back_to_menu_button,
)
from handlers.flows import (
    clean_user_message, store_msg_id, pop_msg_id, get_msg_id,
    send_screen, edit_screen, replace_screen, safe_delete,
)
from config import REFERENCE_COST, PHOTO_COST
from config import AI_API_KEY, AI_API_BASE, AI_MODEL, I2I_API_KEY, I2I_API_BASE
from services.wb_parser import get_product_info
from services.reference_t2t import generate_reference_prompt
from services.reference_i2i import generate_reference_image
from services.prompt_generator_cloth import generate_photo_prompts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Состояния
# ---------------------------------------------------------------------------

PHOTO_WAITING_ARTICLE = 10
PHOTO_WAITING_MP = 11
PHOTO_WAITING_REF_CHOICE = 12
PHOTO_WAITING_REF_FEEDBACK = 13
PHOTO_WAITING_COUNT = 14
PHOTO_WAITING_MULTI_COUNT = 15


# ---------------------------------------------------------------------------
# Вход: кнопка «Фото»
# ---------------------------------------------------------------------------

async def photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("PHOTO_START | user_id=%s", user.id)

    stats = await get_user_stats(user.id)

    if update.message:
        await clean_user_message(update, context)

    text = (
        f"📸 Сгенерируем <b>1 или более фото</b> в разных локациях и стилях!\n\n"
        f"У вас уже <b>{stats['references']}</b> эталон(ов) в базе.\n\n"
        f"Введите артикул товара. Если эталон уже есть — сразу перейдём к генерации."
    )

    await send_screen(
        chat_id=user.id,
        context=context,
        text=text,
        reply_markup=back_to_menu_button(),
        parse_mode="HTML",
    )
    return PHOTO_WAITING_ARTICLE


# ---------------------------------------------------------------------------
# Ввод артикула
# ---------------------------------------------------------------------------

async def photo_article_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw = update.message.text.strip()
    chat_id = update.message.chat.id

    logger.info("PHOTO_ARTICLE | user_id=%s | article=%s", user.id, raw)
    await clean_user_message(update, context)

    # 1. Ищем эталон в БД
    existing_ref = await get_reference(user.id, raw)

    if existing_ref:
        # Эталон уже есть → сразу к выбору количества
        logger.info("PHOTO_ARTICLE | existing ref found")
        context.user_data["photo_article"] = raw
        context.user_data["ref_file_id"] = existing_ref["file_id"]

        # Загружаем product_info
        articles = await get_user_articles(user.id, raw)
        if articles:
            art = articles[0]
            context.user_data["product_info"] = {
                "name": art["name"] or "",
                "color": art["color"] or "",
                "material": art["material"] or "",
            }
            context.user_data["product_category"] = art.get("category") or existing_ref.get("category", "верх")

        text = (
            f"✅ Эталон для артикула <code>{raw}</code> уже есть в базе!\n\n"
            f"Сколько фото сгенерировать?"
        )
        await send_screen(
            chat_id=chat_id,
            context=context,
            text=text,
            reply_markup=photo_count_keyboard(),
            parse_mode="HTML",
        )
        return PHOTO_WAITING_COUNT

    # 2. Эталона нет → спрашиваем МП для создания
    logger.info("PHOTO_ARTICLE | no ref found, asking marketplace")
    text = (
        f"Артикул <code>{raw}</code> не найден в базе.\n\n"
        f"Для создания фото нужен эталон. Выберите маркетплейс:"
    )
    context.user_data["photo_article_pending"] = raw
    await send_screen(
        chat_id=chat_id,
        context=context,
        text=text,
        reply_markup=mp_select_keyboard(),
        parse_mode="HTML",
    )
    return PHOTO_WAITING_MP


# ---------------------------------------------------------------------------
# Выбор МП → парсинг товара
# ---------------------------------------------------------------------------

async def photo_select_mp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mp = "WB" if query.data.endswith("_wb") else "OZON"
    context.user_data["photo_marketplace"] = mp
    logger.info("PHOTO_MP_SELECT | user_id=%s | mp=%s", query.from_user.id, mp)

    pending = context.user_data.get("photo_article_pending")
    if pending:
        return await _photo_parse_article(query, context, pending, mp)

    label = "Wildberries" if mp == "WB" else "OZON"
    await edit_screen(
        chat_id=query.message.chat.id,
        context=context,
        text=f"Введите артикул товара {label}:",
    )
    return PHOTO_WAITING_ARTICLE


async def _photo_parse_article(query, context: ContextTypes.DEFAULT_TYPE, raw: str, mp: str):
    """Парсинг WB → карточка → выбор: создать эталон."""
    chat_id = query.message.chat.id

    if mp == "OZON":
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text=(
                f"✅ Артикул <code>{raw}</code> сохранён для OZON 🔵\n\n"
                "⚠️ Генерация фото для OZON пока в разработке."
            ),
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # WB → парсер
    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔍 Загружаю информацию о товаре...")

    try:
        info = await get_product_info(raw)
    except Exception:
        info = {}

    await safe_delete(chat_id, status_msg.message_id, context)

    if not info:
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text="❌ Товар не найден на Wildberries. Проверьте артикул и введите ещё раз:",
        )
        context.user_data["photo_article_pending"] = raw
        await send_screen(chat_id, context, "Выберите маркетплейс:", reply_markup=mp_select_keyboard())
        return PHOTO_WAITING_MP

    name = info.get("name", "")
    color = info["colors"][0] if info.get("colors") else ""
    material = info.get("material", "")

    user_id = query.from_user.id
    await save_article(
        user_id=user_id, article_code=raw, marketplace=mp,
        name=name, color=color, material=material,
    )

    context.user_data["photo_article"] = raw
    context.user_data["product_info"] = {"name": name, "color": color, "material": material}
    context.user_data["wb_images"] = info.get("images", [])[:5]
    context.user_data.pop("photo_article_pending", None)

    meta_lines = []
    if name:
        meta_lines.append(f'📦 <a href="https://www.wildberries.ru/catalog/{raw}/detail.aspx">{name}</a>')
    if info.get("brand"):
        meta_lines.append(f'👤 <a href="https://www.wildberries.ru/catalog?search={quote(info["brand"])}">{info["brand"]}</a>')
    if color:
        meta_lines.append(f"🎨 {color[:1].upper() + color[1:]}")
    if material:
        meta_lines.append(f"🧵 {material}")

    card_text = (
        f"✅ Артикул <code>{raw}</code> найден на Wildberries 🟣\n\n"
        + "\n".join(meta_lines)
        + "\n\nЭталон для этого артикула ещё не создан. Создать?"
    )

    await replace_screen(
        chat_id=chat_id,
        context=context,
        text=card_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Создать эталон", callback_data="photo_create_ref")],
            [InlineKeyboardButton("🔄 Ввести другой артикул", callback_data="photo_new_article")],
        ]),
        parse_mode="HTML",
    )
    return PHOTO_WAITING_REF_CHOICE


# ---------------------------------------------------------------------------
# Выбор: создать эталон / новый артикул
# ---------------------------------------------------------------------------

async def photo_ref_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    action = query.data

    logger.info("PHOTO_REF_CHOICE | user_id=%s | action=%s", query.from_user.id, action)

    if action == "photo_new_article":
        context.user_data.pop("photo_article", None)
        context.user_data.pop("photo_article_pending", None)
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text="Введите артикул товара:",
            reply_markup=mp_select_keyboard(),
        )
        return PHOTO_WAITING_MP

    if action == "photo_create_ref":
        return await _generate_photo_reference(query, context)

    return PHOTO_WAITING_REF_CHOICE


async def _generate_photo_reference(query, context: ContextTypes.DEFAULT_TYPE):
    """Фоновая генерация эталона для фото-потока."""
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    articul = context.user_data.get("photo_article", "")
    product = context.user_data.get("product_info", {})
    wb_images = context.user_data.get("wb_images", [])

    db_user = await get_user(user_id)
    balance = db_user["balance"] if db_user else 0

    if balance < REFERENCE_COST:
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text=(
                f"❌ Недостаточно средств.\n\n"
                f"Стоимость эталона: <b>{REFERENCE_COST} руб.</b>\n"
                f"Баланс: <b>{balance} руб.</b>\n\n"
                f"Пополните баланс и попробуйте снова."
            ),
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    try:
        await query.message.delete()
    except Exception:
        pass

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ <b>Генерация эталона...</b>\n\nАртикул: <code>{articul}</code>",
        parse_mode="HTML",
    )
    store_msg_id(context, "photo_status_msg_id", status_msg.message_id)

    async def _background():
        session = context.bot_data.get("http_session")
        if not session:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg.message_id,
                text="⚠️ Техническая ошибка.",
            )
            return

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg.message_id,
                text=f"⏳ <b>Генерация эталона...</b>\n\n"
                     f"Артикул: <code>{articul}</code>\n"
                     f"📝 Создаю промпт...",
                parse_mode="HTML",
            )

            t2t_result = await generate_reference_prompt(
                session=session, name=product.get("name", ""),
                color=product.get("color", ""), material=product.get("material", ""),
                api_key=AI_API_KEY, api_base_url=AI_API_BASE, model=AI_MODEL,
            )
            if not t2t_result:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg.message_id,
                    text="❌ Ошибка генерации промпта.",
                )
                return

            context.user_data["reference_prompt"] = t2t_result["prompt"]
            context.user_data["product_category"] = t2t_result["category"]

            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg.message_id,
                text=f"⏳ <b>Генерация эталона...</b>\n\n"
                     f"Артикул: <code>{articul}</code>\n"
                     f"🎨 Создаю изображение ИИ...",
                parse_mode="HTML",
            )

            new_balance = await deduct_balance(user_id, REFERENCE_COST)

            image_url = await generate_reference_image(
                session=session, api_base=I2I_API_BASE, api_key=I2I_API_KEY,
                image_urls=wb_images[:3], prompt=t2t_result["prompt"],
            )
            if not image_url:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg.message_id,
                    text="❌ Ошибка генерации изображения.",
                )
                return

            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as img_resp:
                image_data = await img_resp.read()

            from services.media_storage import MEDIA_ROOT
            import os
            user_ref_dir = os.path.join(MEDIA_ROOT, str(user_id), "references")
            os.makedirs(user_ref_dir, exist_ok=True)
            file_path = os.path.join(user_ref_dir, f"{articul}.png")

            sent = await context.bot.send_photo(chat_id=user_id, photo=image_data)
            file_id = sent.photo[-1].file_id

            await save_reference(
                user_id=user_id, articul=articul, file_id=file_id, file_path=file_path,
                reference_image_url=image_url,
                category=context.user_data.get("product_category", ""),
                reference_prompt=context.user_data.get("reference_prompt", ""),
            )

            await safe_delete(chat_id, status_msg.message_id, context)

            ref_msg = await context.bot.send_photo(
                chat_id=chat_id, photo=image_data,
                caption=(
                    f"🎨 <b>Эталон для {articul} готов!</b>\n\n"
                    f"Списано <b>{REFERENCE_COST} руб.</b> Баланс: <b>{new_balance} руб.</b>"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Подходит, создать фото", callback_data="photo_ref_ok")],
                    [InlineKeyboardButton("🔄 Переделать", callback_data="photo_ref_redo")],
                ]),
                parse_mode="HTML",
            )
            store_msg_id(context, "photo_ref_msg_id", ref_msg.message_id)
            store_msg_id(context, "ref_file_id", file_id)

        except Exception as e:
            logger.error("PHOTO_REF_GEN_FAILED: %s", e)

    import asyncio
    task = asyncio.create_task(_background())
    context.bot_data.setdefault("bg_tasks", set()).add(task)
    task.add_done_callback(context.bot_data["bg_tasks"].discard)
    return PHOTO_WAITING_REF_FEEDBACK


# ---------------------------------------------------------------------------
# Фидбек эталона
# ---------------------------------------------------------------------------

async def photo_ref_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    articul = context.user_data.get("photo_article", "")

    if query.data == "photo_ref_ok":
        # Сохраняем и переходим к выбору количества
        await context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=get_msg_id(context, "photo_ref_msg_id") or query.message.message_id,
            caption=f"✅ Эталон для <code>{articul}</code> сохранён!",
            reply_markup=None,
            parse_mode="HTML",
        )

        context.user_data["_photo_user_id"] = query.from_user.id
        await context.bot.send_message(
            chat_id=chat_id,
            text="Сколько фото сгенерировать?",
            reply_markup=photo_count_keyboard(),
        )
        return PHOTO_WAITING_COUNT

    if query.data == "photo_ref_redo":
        await replace_screen(
            chat_id=chat_id, context=context,
            text="✍️ Напишите что нужно изменить:",
        )
        # TODO: состояние для фидбека
        return ConversationHandler.END

    return PHOTO_WAITING_REF_FEEDBACK


# ---------------------------------------------------------------------------
# Выбор количества фото
# ---------------------------------------------------------------------------

async def photo_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    if query.data == "photo_back":
        await replace_screen(
            chat_id=chat_id, context=context,
            text="Выберите действие:", reply_markup=main_menu(),
        )
        return ConversationHandler.END

    if query.data == "photo_one":
        context.user_data["photo_count"] = 1
        context.user_data["_photo_user_id"] = query.from_user.id
        return await _generate_photos(chat_id, context, 1)

    if query.data == "photo_multi":
        await edit_screen(
            chat_id=chat_id, context=context,
            text="Сколько фото создать? (1–20)",
        )
        return PHOTO_WAITING_MULTI_COUNT

    return PHOTO_WAITING_COUNT


# ---------------------------------------------------------------------------
# Ввод количества (мульти)
# ---------------------------------------------------------------------------

async def photo_multi_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    try:
        n = int(raw)
        if not 1 <= n <= 20:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введите число от 1 до 20:")
        return PHOTO_WAITING_MULTI_COUNT

    context.user_data["photo_count"] = n
    context.user_data["_photo_user_id"] = update.effective_user.id
    return await _generate_photos(update.message.chat.id, context, n)


# ---------------------------------------------------------------------------
# Генерация фото — запись тасков в очередь
# ---------------------------------------------------------------------------

async def _generate_photos(chat_id, context: ContextTypes.DEFAULT_TYPE, count: int):
    articul = context.user_data.get("photo_article", "")
    product = context.user_data.get("product_info", {})
    user_id = context.user_data.get("_photo_user_id")

    if not user_id:
        logger.error("PHOTO_GEN | user_id not in context!")
        await context.bot.send_message(
            chat_id=chat_id, text="⚠️ Техническая ошибка. Начните заново.",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    db_user = await get_user(user_id)
    balance = db_user["balance"] if db_user else 0
    cost = PHOTO_COST * count

    if balance < cost:
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text=(
                f"❌ Недостаточно средств.\n\n"
                f"Стоимость: <b>{cost} руб.</b> ({count} × {PHOTO_COST} руб.)\n"
                f"Баланс: <b>{balance} руб.</b>\n\n"
                f"Пополните баланс и попробуйте снова."
            ),
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    ref = await get_reference(user_id, articul)
    category = (context.user_data.get("product_category")
                or (ref["category"] if ref and ref["category"] else "верх"))

    prompts = generate_photo_prompts(
        name=product.get("name", ""), color=product.get("color", ""),
        material=product.get("material", ""), category=category, count=count,
    )

    new_balance = await deduct_balance(user_id, cost)

    for prompt in prompts:
        await create_task(
            user_id=user_id, chat_id=chat_id,
            task_type="photo", articul=articul, prompt=prompt,
        )

    logger.info("PHOTO_GEN | user=%d art=%s count=%d cost=%d", user_id, articul, count, cost)

    await replace_screen(
        chat_id=chat_id,
        context=context,
        text=(
            f"✅ <b>{count} фото</b> поставлено в очередь!\n\n"
            f"Артикул: <code>{articul}</code>\n"
            f"Категория: <b>{category}</b>\n\n"
            f"Списано <b>{cost} руб.</b> Баланс: <b>{new_balance} руб.</b>\n\n"
            f"Фото будут отправляться по мере готовности 🔄"
        ),
        reply_markup=main_menu(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

async def _menu_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("PHOTO_FALLBACK | user=%s btn=%s", update.effective_user.id, update.message.text)
    await update.message.reply_text("Выберите действие:", reply_markup=main_menu())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------

def build_photo_handler() -> ConversationHandler:
    any_menu = tg_filters.Regex(f"^({'|'.join(MENU_BUTTONS)})$")

    return ConversationHandler(
        entry_points=[
            MessageHandler(tg_filters.Regex(f"^{BTN_PHOTO}$"), photo_start),
        ],
        states={
            PHOTO_WAITING_ARTICLE: [
                MessageHandler(tg_filters.TEXT & ~any_menu, photo_article_received),
            ],
            PHOTO_WAITING_MP: [
                CallbackQueryHandler(photo_select_mp, pattern="^mp_(wb|ozon)$"),
            ],
            PHOTO_WAITING_REF_CHOICE: [
                CallbackQueryHandler(photo_ref_choice, pattern="^photo_(create_ref|new_article)$"),
            ],
            PHOTO_WAITING_REF_FEEDBACK: [
                CallbackQueryHandler(photo_ref_feedback, pattern="^photo_ref_(ok|redo)$"),
            ],
            PHOTO_WAITING_COUNT: [
                CallbackQueryHandler(photo_count, pattern="^photo_(one|multi|back)$"),
            ],
            PHOTO_WAITING_MULTI_COUNT: [
                MessageHandler(tg_filters.TEXT & ~any_menu, photo_multi_count),
            ],
        },
        fallbacks=[
            MessageHandler(any_menu, _menu_fallback),
        ],
        per_message=False,
    )
