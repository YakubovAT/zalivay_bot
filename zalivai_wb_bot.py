"""
bot.py

Точка входа бота. Инициализация Application, регистрация хендлеров, запуск.
"""

import asyncio
import logging
import sys

import aiohttp
from telegram import BotCommand, MenuButtonCommands, Update
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters, ContextTypes

from config import BOT_TOKEN
from database import init_db
from handlers import (
    build_onboarding_handler,
    build_new_article_handler,
    build_reference_handler,
    build_etalon_handler,
    build_ref_article_handler,
    build_ref_nav_handler,
    build_gen_photo_handler,
    build_gen_video_handler,
    build_noop_handler,
    build_photo_handler,
    build_video_handler,
    log_message,
    log_callback,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("wb_parser").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def on_startup(application: Application) -> None:
    """Инициация при старте: БД, HTTP-сессии, фоновые воркеры."""
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN не задан.")
        sys.exit(1)

    # Глобальная HTTP-сессия (короткие таймауты)
    connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
    application.bot_data["http_session"] = aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(connect=2, total=4),
    )
    logger.info("HTTP-сессия создана")

    await init_db()
    logger.info("БД инициализирована")

    # Настраиваем MenuButton — кнопка «≡» слева от поля ввода
    await application.bot.set_my_commands([
        BotCommand("start", "Запустить бота"),
        BotCommand("help", "Помощь"),
    ])
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("MenuButton настроен")

    # Воркер-сессия (длинные таймауты для I2I)
    worker_session = aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=10, ttl_dns_cache=300),
        timeout=aiohttp.ClientTimeout(connect=10, total=120),
    )
    application.bot_data["worker_session"] = worker_session

    from services.task_worker import run_worker
    asyncio.create_task(run_worker(application.bot, worker_session))
    logger.info("Task worker запущен")


async def on_shutdown(application: Application) -> None:
    """Корректное закрытие ресурсов."""
    for key in ("http_session", "worker_session"):
        session: aiohttp.ClientSession | None = application.bot_data.get(key)
        if session and not session.closed:
            await session.close()
            logger.info("%s закрыта", key)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def main() -> None:
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    # --- Глобальное логирование (group=-1) ---
    application.add_handler(MessageHandler(filters.ALL, log_message), group=-1)
    application.add_handler(CallbackQueryHandler(log_callback), group=-1)

    # --- Генерация фото ---
    application.add_handler(build_gen_photo_handler())

    # --- Генерация видео ---
    application.add_handler(build_gen_video_handler())

    # --- Онбординг /start ---
    application.add_handler(build_onboarding_handler())

    # --- Эталон товара (список) ---
    application.add_handler(build_etalon_handler())

    # --- Шаг 16: Просмотр эталона (фото + навигация) ---
    application.add_handler(build_noop_handler())
    application.add_handler(build_ref_article_handler())
    application.add_handler(build_ref_nav_handler())

    # --- Новый артикул (включает выбор фото и создание эталона) ---
    application.add_handler(build_new_article_handler())

    # --- Создание эталона (T2T + I2I) ---
    application.add_handler(build_reference_handler())

    # --- Фото ---
    application.add_handler(build_photo_handler())

    # --- Видео ---
    application.add_handler(build_video_handler())

    # --- Глобальный обработчик ошибок ---
    async def error_handler(update, context):
        logger.error("Unhandled error: %s", context.error, exc_info=context.error)
        if update and update.effective_user:
            try:
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Закрыть", callback_data="close_error")]
                ])
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
                    text="❌ Произошла ошибка. Попробуйте снова или нажмите /start.",
                    reply_markup=keyboard,
                )
            except Exception:
                pass

    application.add_error_handler(error_handler)
    
    # Обработчик закрытия ошибок
    async def cb_close_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    application.add_handler(CallbackQueryHandler(cb_close_error, pattern="^close_error$"))

    logger.info("Бот запущен")
    application.run_polling()


if __name__ == "__main__":
    main()
