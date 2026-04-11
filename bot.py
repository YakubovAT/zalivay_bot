"""
bot.py

Точка входа бота. Инициализация Application, регистрация хендлеров, запуск.
"""

import asyncio
import logging
import sys

import aiohttp
from telegram import BotCommand, MenuButtonCommands
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from config import BOT_TOKEN
from database import init_db
from handlers import (
    build_onboarding_handler,
    build_new_article_handler,
    build_etalon_handler,
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

    # --- Новый артикул (до онбординга — специфичные callbacks) ---
    application.add_handler(build_new_article_handler())

    # --- Онбординг /start ---
    application.add_handler(build_onboarding_handler())

    # --- Эталон товара ---
    application.add_handler(build_etalon_handler())

    # --- Фото ---
    application.add_handler(build_photo_handler())

    # --- Видео ---
    application.add_handler(build_video_handler())

    logger.info("Бот запущен")
    application.run_polling()


if __name__ == "__main__":
    main()
