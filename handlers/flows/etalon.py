"""
etalon.py

Поток создания эталона товара.
Паттерн «одно окно»: баннер 620x50 + текст + кнопки, edit вместо send.
"""

import logging
import os
from io import BytesIO
from urllib.parse import quote

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database import (
    ensure_user, get_user, get_reference, save_article, save_reference, deduct_balance, get_user_stats
)
from handlers.keyboards import (
    mp_select_keyboard, etalon_create_keyboard, etalon_feedback_keyboard,
    etalon_existing_keyboard, etalon_done_keyboard, main_menu
)
from handlers.flows import (
    clean_user_message, store_msg_id, get_msg_id, pop_msg_id,
    send_screen, edit_screen, replace_screen, safe_delete
)
from config import REFERENCE_COST, AI_API_KEY, AI_API_BASE, AI_MODEL, I2I_API_KEY, I2I_API_BASE
from services.wb_parser import get_product_info
from services.reference_t2t import generate_reference_prompt
from services.reference_i2i import generate_reference_image, create_i2i_task, poll_task_status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Состояния
# ---------------------------------------------------------------------------

WAITING_MP = 1
WAITING_ARTICLE = 2
WAITING_REF_CHOICE = 3
WAITING_REF_FEEDBACK = 4


# ---------------------------------------------------------------------------
# Вход: кнопка «Эталон товара»
# ---------------------------------------------------------------------------

async def etalon_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("ETALON_START | user_id=%s", user.id)

    stats = await get_user_stats(user.id)
    ref_count = stats["references"]

    text = (
        f"У Вас уже есть <b>{ref_count}</b> эталон(ов) для генерации фото и видео контента.\n\n"
        "Необходимо создать эталон для Вашего товара — введите артикул. "
        "Если ранее вы делали для него эталон, мы перейдём к генерации фото и видео. "
        "Если нет — создадим новый эталон.\n\n"
        "Выберите маркетплейс:"
    )

    if update.message:
        await clean_user_message(update, context)

    await send_screen(
        chat_id=user.id,
        context=context,
        text=text,
        reply_markup=mp_select_keyboard(),
        parse_mode="HTML",
    )
    return WAITING_MP


# ---------------------------------------------------------------------------
# Выбор МП → запрос артикула
# ---------------------------------------------------------------------------

async def select_mp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mp = "WB" if query.data.endswith("_wb") else "OZON"
    context.user_data["etalon_marketplace"] = mp
    logger.info("ETALON_MP_SELECT | user_id=%s | mp=%s", query.from_user.id, mp)

    label = "Wildberries" if mp == "WB" else "OZON"

    await edit_screen(
        chat_id=query.message.chat.id,
        context=context,
        text=f"Введите артикул товара {label}:",
    )
    return WAITING_ARTICLE


# ---------------------------------------------------------------------------
# Ввод артикула → карточка товара
# ---------------------------------------------------------------------------

async def article_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw = update.message.text.strip()
    marketplace = context.user_data.get("etalon_marketplace", "WB")
    chat_id = update.message.chat.id

    logger.info("ETALON_ARTICLE | user_id=%s | article=%s | mp=%s", user.id, raw, marketplace)

    # Удаляем сообщение пользователя
    await clean_user_message(update, context)

    # Статус загрузки
    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔍 Загружаю информацию о товаре...")
    store_msg_id(context, "etalon_status_msg_id", status_msg.message_id)

    # --- OZON: заглушка ---
    if marketplace == "OZON":
        await safe_delete(chat_id, status_msg.message_id, context)
        await send_screen(
            chat_id=chat_id,
            context=context,
            text=(
                f"✅ Артикул <code>{raw}</code> сохранён для OZON 🔵\n\n"
                "⚠️ Генерация эталонов для OZON пока в разработке. "
                "Скоро эта функция станет доступна!"
            ),
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # --- WB: парсер ---
    try:
        info = await get_product_info(raw)
    except Exception:
        info = {}

    await safe_delete(chat_id, status_msg.message_id, context)

    if not info:
        await send_screen(
            chat_id=chat_id,
            context=context,
            text=f"❌ Товар не найден на Wildberries. Проверьте артикул и введите ещё раз:",
        )
        return WAITING_ARTICLE

    name = info.get("name", "")
    color = info["colors"][0] if info.get("colors") else ""
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

    # Сохраняем артикул
    await save_article(
        user_id=user.id,
        article_code=raw,
        marketplace=marketplace,
        name=name,
        color=color,
        material=material,
    )

    context.user_data["etalon_article"] = raw
    context.user_data["product_info"] = {"name": name, "color": color, "material": material}
    context.user_data["wb_images"] = info.get("images", [])[:5]

    # Проверяем, есть ли уже эталон
    existing_ref = await get_reference(user.id, raw)

    card_text = (
        f"✅ Артикул <code>{raw}</code> найден на Wildberries 🟣\n\n"
        + "\n".join(meta_lines)
    )

    if existing_ref:
        # Эталон уже есть
        await send_screen(
            chat_id=chat_id,
            context=context,
            text=card_text + "\n\nЭталон для этого артикула уже создан. Хотите переделать?",
            reply_markup=etalon_existing_keyboard(),
            parse_mode="HTML",
            banner_path=None,  # TODO: можно свой баннер
        )
    else:
        # Создаём эталон
        await send_screen(
            chat_id=chat_id,
            context=context,
            text=card_text + "\n\nЭталон для этого артикула ещё не создан. Создать?",
            reply_markup=etalon_create_keyboard(),
            parse_mode="HTML",
        )

    return WAITING_REF_CHOICE


# ---------------------------------------------------------------------------
# Выбор: создать эталон / другой артикул / в меню
# ---------------------------------------------------------------------------

async def ref_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    action = query.data

    logger.info("ETALON_REF_CHOICE | user_id=%s | action=%s", query.from_user.id, action)

    if action == "go_menu":
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text="Выберите действие:",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    if action == "new_article":
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text="Введите артикул товара:",
            reply_markup=mp_select_keyboard(),
        )
        return WAITING_MP

    if action in ("create_ref", "redo_ref"):
        return await _generate_etalon(query, context, charge=action == "create_ref")

    return WAITING_REF_CHOICE


# ---------------------------------------------------------------------------
# Генерация эталона (T2T → I2I)
# ---------------------------------------------------------------------------

async def _generate_etalon(query, context: ContextTypes.DEFAULT_TYPE, charge: bool = True):
    """Фоновая генерация эталона. charge=True — списать баланс."""
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    articul = context.user_data.get("etalon_article", "")
    product = context.user_data.get("product_info", {})
    wb_images = context.user_data.get("wb_images", [])

    # Проверка баланса
    db_user = await get_user(user_id)
    balance = db_user["balance"] if db_user else 0

    if balance < REFERENCE_COST:
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text=(
                f"❌ Недостаточно средств.\n\n"
                f"Стоимость создания эталона: <b>{REFERENCE_COST} руб.</b>\n"
                f"Ваш баланс: <b>{balance} руб.</b>\n\n"
                f"Пополните баланс и попробуйте снова."
            ),
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # Удаляем старое сообщение, показываем статус
    try:
        await query.message.delete()
    except Exception:
        pass

    status_text = (
        f"⏳ <b>Генерация эталона...</b>\n\n"
        f"Артикул: <code>{articul}</code>\n"
        f"🔄 Генерирую промпт → создаю изображение"
    )
    status_msg = await context.bot.send_message(chat_id=chat_id, text=status_text, parse_mode="HTML")
    store_msg_id(context, "etalon_status_msg_id", status_msg.message_id)

    async def _background():
        session = context.bot_data.get("http_session")
        if not session:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg.message_id,
                text="⚠️ Техническая ошибка. Попробуйте позже.",
            )
            return

        try:
            # Этап 1: T2T
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg.message_id,
                text=f"⏳ <b>Генерация эталона...</b>\n\n"
                     f"Артикул: <code>{articul}</code>\n"
                     f"📝 Анализирую товар, создаю промпт...",
                parse_mode="HTML",
            )

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
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg.message_id,
                    text="❌ Ошибка генерации промпта. Попробуйте снова.",
                )
                return

            context.user_data["reference_prompt"] = t2t_result["prompt"]
            context.user_data["product_category"] = t2t_result["category"]

            # Этап 2: I2I
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg.message_id,
                text=f"⏳ <b>Генерация эталона...</b>\n\n"
                     f"Артикул: <code>{articul}</code>\n"
                     f"🎨 Создаю эталон с помощью ИИ...\n\n"
                     f"Это займёт 1–2 минуты ⏱",
                parse_mode="HTML",
            )

            if charge:
                await deduct_balance(user_id, REFERENCE_COST)

            image_url = await generate_reference_image(
                session=session,
                api_base=I2I_API_BASE,
                api_key=I2I_API_KEY,
                image_urls=wb_images[:3],
                prompt=t2t_result["prompt"],
            )

            if not image_url:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg.message_id,
                    text="❌ Ошибка генерации изображения. Попробуйте снова.",
                )
                return

            # Скачиваем
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as img_resp:
                image_data = await img_resp.read()

            # Сохраняем
            from services.media_storage import MEDIA_ROOT
            user_ref_dir = os.path.join(MEDIA_ROOT, str(user_id), "references")
            os.makedirs(user_ref_dir, exist_ok=True)
            file_path = os.path.join(user_ref_dir, f"{articul}.png")

            sent_photo = await context.bot.send_photo(chat_id=user_id, photo=BytesIO(image_data))
            file_id = sent_photo.photo[-1].file_id

            await save_reference(
                user_id=user_id,
                articul=articul,
                file_id=file_id,
                file_path=file_path,
                reference_image_url=image_url,
                category=context.user_data.get("product_category", ""),
                reference_prompt=context.user_data.get("reference_prompt", ""),
            )

            # Удаляем статус, отправляем фото с кнопками
            await safe_delete(chat_id, status_msg.message_id, context)

            ref_msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=BytesIO(image_data),
                caption=(
                    f"🎨 <b>Эталон для артикула {articul} готов!</b>\n\n"
                    f"Он должен быть <i>похож</i>, а не 100% копией."
                ),
                reply_markup=etalon_feedback_keyboard(),
                parse_mode="HTML",
            )

            store_msg_id(context, "ref_photo_msg_id", ref_msg.message_id)
            store_msg_id(context, "ref_file_id", file_id)

        except Exception as e:
            logger.error("ETALON_GEN_FAILED: %s", e)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg.message_id,
                    text=f"❌ Ошибка генерации: {e}",
                )
            except Exception:
                pass

    task = __import__("asyncio").create_task(_background())
    context.bot_data.setdefault("bg_tasks", set()).add(task)
    task.add_done_callback(context.bot_data["bg_tasks"].discard)
    return WAITING_REF_FEEDBACK


# ---------------------------------------------------------------------------
# Фидбек: ✅ Подходит / 🔄 Переделать
# ---------------------------------------------------------------------------

async def ref_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    articul = context.user_data.get("etalon_article", "")

    logger.info("ETALON_FEEDBACK | user_id=%s | action=%s", query.from_user.id, query.data)

    if query.data == "ref_ok":
        msg_id = get_msg_id(context, "ref_photo_msg_id")
        if msg_id:
            await context.bot.edit_message_caption(
                chat_id=chat_id, message_id=msg_id,
                caption=(
                    f"✅ Эталон для <code>{articul}</code> сохранён в базу!\n\n"
                    f"Теперь для создания фото и видео мы будем использовать этот эталон."
                ),
                reply_markup=etalon_done_keyboard(),
                parse_mode="HTML",
            )
        return WAITING_REF_FEEDBACK

    if query.data == "go_photo":
        # TODO: перейти в фото
        await context.bot.send_message(chat_id=chat_id, text="📸 Переход к созданию фото...")
        return ConversationHandler.END

    if query.data == "go_video":
        await context.bot.send_message(chat_id=chat_id, text="🎬 Переход к созданию видео...")
        return ConversationHandler.END

    if query.data == "ref_redo":
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text="✍️ Напишите что нужно изменить в эталоне:\nНапример: «убрать фон» или «изменить цвет»",
        )
        # TODO: состояние для ввода фидбека
        return ConversationHandler.END

    return WAITING_REF_FEEDBACK


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

async def _menu_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logger.info("ETALON_FALLBACK | user_id=%s | button=%s", update.effective_user.id, text)
    await update.message.reply_text("Выберите действие:", reply_markup=main_menu())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Сборка ConversationHandler
# ---------------------------------------------------------------------------

from telegram.ext import ConversationHandler, CallbackQueryHandler, MessageHandler
from telegram.ext import filters as tg_filters
from handlers.keyboards import BTN_ETALON, MENU_BUTTONS


def build_etalon_handler() -> ConversationHandler:
    any_menu = tg_filters.Regex(f"^({'|'.join(MENU_BUTTONS)})$")

    return ConversationHandler(
        entry_points=[
            MessageHandler(tg_filters.Regex(f"^{BTN_ETALON}$"), etalon_start),
        ],
        states={
            WAITING_MP: [
                CallbackQueryHandler(select_mp, pattern="^mp_(wb|ozon)$"),
            ],
            WAITING_ARTICLE: [
                MessageHandler(tg_filters.TEXT & ~any_menu, article_received),
            ],
            WAITING_REF_CHOICE: [
                CallbackQueryHandler(ref_choice, pattern="^(create_ref|redo_ref|new_article|go_menu)$"),
            ],
            WAITING_REF_FEEDBACK: [
                CallbackQueryHandler(ref_feedback, pattern="^(ref_ok|ref_redo|go_photo|go_video)$"),
            ],
        },
        fallbacks=[
            MessageHandler(any_menu, _menu_fallback),
        ],
        per_message=False,
    )
