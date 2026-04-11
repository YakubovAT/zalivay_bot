"""
video.py

Поток создания видео товара.
Паттерн «одно окно»: баннер 620×50 + текст + кнопки, edit вместо send.

TODO: видео-генерация пока в разработке — поток заглушка.
"""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler,
    filters as tg_filters,
)

from database import get_user_stats, get_reference, get_user_articles
from handlers.keyboards import (
    BTN_VIDEO, BTN_PROFILE, BTN_PHOTO, BTN_ETALON, BTN_PRICING, BTN_HELP, BTN_RESTART,
    MENU_BUTTONS, main_menu, mp_select_keyboard, back_to_menu_button,
)
from handlers.flows import (
    clean_user_message, store_msg_id,
    send_screen, edit_screen, replace_screen, safe_delete,
)
from config import REFERENCE_COST
from services.wb_parser import get_product_info

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Состояния
# ---------------------------------------------------------------------------

VIDEO_WAITING_ARTICLE = 20
VIDEO_WAITING_MP = 21
VIDEO_WAITING_REF_CHOICE = 22


# ---------------------------------------------------------------------------
# Вход: кнопка «Видео»
# ---------------------------------------------------------------------------

async def video_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("VIDEO_START | user_id=%s", user.id)

    stats = await get_user_stats(user.id)

    if update.message:
        await clean_user_message(update, context)

    text = (
        f"🎬 Сгенерируем <b>видео</b> для вашего товара!\n\n"
        f"У вас <b>{stats['references']}</b> эталон(ов) в базе.\n\n"
        f"Введите артикул товара:"
    )

    await send_screen(
        chat_id=user.id,
        context=context,
        text=text,
        reply_markup=back_to_menu_button(),
        parse_mode="HTML",
    )
    return VIDEO_WAITING_ARTICLE


# ---------------------------------------------------------------------------
# Ввод артикула
# ---------------------------------------------------------------------------

async def video_article_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw = update.message.text.strip()
    chat_id = update.message.chat.id

    logger.info("VIDEO_ARTICLE | user_id=%s | article=%s", user.id, raw)
    await clean_user_message(update, context)

    existing_ref = await get_reference(user.id, raw)

    if existing_ref:
        # Эталон есть → TODO: генерация видео
        context.user_data["video_article"] = raw
        await replace_screen(
            chat_id=chat_id,
            context=context,
            text=(
                f"✅ Эталон для <code>{raw}</code> найден!\n\n"
                f"🚧 <b>Генерация видео пока в разработке.</b>\n\n"
                f"Скоро вы сможете создавать видео на основе эталона."
            ),
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # Эталона нет → спрашиваем МП
    text = (
        f"Артикул <code>{raw}</code> не найден в базе.\n\n"
        f"Для создания видео нужен эталон. Выберите маркетплейс:"
    )
    context.user_data["video_article_pending"] = raw
    await send_screen(
        chat_id=chat_id,
        context=context,
        text=text,
        reply_markup=mp_select_keyboard(),
        parse_mode="HTML",
    )
    return VIDEO_WAITING_MP


# ---------------------------------------------------------------------------
# Выбор МП → парсинг
# ---------------------------------------------------------------------------

async def video_select_mp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mp = "WB" if query.data.endswith("_wb") else "OZON"
    context.user_data["video_marketplace"] = mp
    logger.info("VIDEO_MP_SELECT | user_id=%s | mp=%s", query.from_user.id, mp)

    pending = context.user_data.get("video_article_pending")
    if pending:
        return await _video_parse_article(query, context, pending, mp)

    label = "Wildberries" if mp == "WB" else "OZON"
    await edit_screen(
        chat_id=query.message.chat.id,
        context=context,
        text=f"Введите артикул товара {label}:",
    )
    return VIDEO_WAITING_ARTICLE


async def _video_parse_article(query, context: ContextTypes.DEFAULT_TYPE, raw: str, mp: str):
    chat_id = query.message.chat.id

    if mp == "OZON":
        await replace_screen(
            chat_id=chat_id, context=context,
            text=(
                f"✅ Артикул <code>{raw}</code> сохранён для OZON 🔵\n\n"
                "⚠️ Генерация видео для OZON пока в разработке."
            ),
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔍 Загружаю информацию о товаре...")

    try:
        info = await get_product_info(raw)
    except Exception:
        info = {}

    await safe_delete(chat_id, status_msg.message_id, context)

    if not info:
        await replace_screen(
            chat_id=chat_id, context=context,
            text="❌ Товар не найден. Проверьте артикул:",
        )
        context.user_data["video_article_pending"] = raw
        await send_screen(chat_id, context, "Выберите маркетплейс:", reply_markup=mp_select_keyboard())
        return VIDEO_WAITING_MP

    from urllib.parse import quote
    name = info.get("name", "")
    color = info["colors"][0] if info.get("colors") else ""
    material = info.get("material", "")

    user_id = query.from_user.id
    from database import save_article
    await save_article(
        user_id=user_id, article_code=raw, marketplace=mp,
        name=name, color=color, material=material,
    )

    context.user_data["video_article"] = raw
    context.user_data["product_info"] = {"name": name, "color": color, "material": material}
    context.user_data["wb_images"] = info.get("images", [])[:5]
    context.user_data.pop("video_article_pending", None)

    meta_lines = []
    if name:
        meta_lines.append(f'📦 <a href="https://www.wildberries.ru/catalog/{raw}/detail.aspx">{name}</a>')
    if info.get("brand"):
        meta_lines.append(f'👤 {info["brand"]}')
    if color:
        meta_lines.append(f"🎨 {color[:1].upper() + color[1:]}")
    if material:
        meta_lines.append(f"🧵 {material}")

    card_text = (
        f"✅ Артикул <code>{raw}</code> найден на Wildberries 🟣\n\n"
        + "\n".join(meta_lines)
        + "\n\n🚧 <b>Генерация видео пока в разработке.</b>\n"
        f"Эталон сохранён — скоро вы сможете создавать видео."
    )

    await replace_screen(
        chat_id=chat_id,
        context=context,
        text=card_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Ввести другой артикул", callback_data="video_new_article")],
        ]),
        parse_mode="HTML",
    )
    return VIDEO_WAITING_REF_CHOICE


# ---------------------------------------------------------------------------
# Выбор: новый артикул
# ---------------------------------------------------------------------------

async def video_ref_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    if query.data == "video_new_article":
        context.user_data.pop("video_article", None)
        await replace_screen(
            chat_id=chat_id, context=context,
            text="Введите артикул товара:",
            reply_markup=mp_select_keyboard(),
        )
        return VIDEO_WAITING_MP

    return VIDEO_WAITING_REF_CHOICE


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

async def _menu_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("VIDEO_FALLBACK | user=%s btn=%s", update.effective_user.id, update.message.text)
    await update.message.reply_text("Выберите действие:", reply_markup=main_menu())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------

def build_video_handler() -> ConversationHandler:
    any_menu = tg_filters.Regex(f"^({'|'.join(MENU_BUTTONS)})$")

    return ConversationHandler(
        entry_points=[
            MessageHandler(tg_filters.Regex(f"^{BTN_VIDEO}$"), video_start),
        ],
        states={
            VIDEO_WAITING_ARTICLE: [
                MessageHandler(tg_filters.TEXT & ~any_menu, video_article_received),
            ],
            VIDEO_WAITING_MP: [
                CallbackQueryHandler(video_select_mp, pattern="^mp_(wb|ozon)$"),
            ],
            VIDEO_WAITING_REF_CHOICE: [
                CallbackQueryHandler(video_ref_choice, pattern="^video_new_article$"),
            ],
        },
        fallbacks=[
            MessageHandler(any_menu, _menu_fallback),
        ],
        per_message=False,
    )
