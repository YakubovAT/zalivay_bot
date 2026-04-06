import logging
import sys

import aiohttp
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from config import BOT_TOKEN
from database import init_db
from handlers import (
    build_registration_handler,
    build_conversation_handler,
    profile,
    idea,
    pricing,
    help_cmd,
)
from handlers.menu import BTN_PROFILE, BTN_IDEA, BTN_PRICING, BTN_HELP, BTN_RESTART
from handlers.action_logger import log_message, log_callback

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("wb_parser").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


async def on_startup(application: Application) -> None:
    # Валидация обязательных переменных окружения при старте
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN не задан. Установите переменную окружения BOT_TOKEN.")
        sys.exit(1)

    # Глобальный HTTP-клиент — один на весь lifecycle бота.
    # Передаётся в handlers через context.bot_data["http_session"].
    # Переиспользует TCP-соединения, не создаёт новый Session на каждый запрос.
    connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
    application.bot_data["http_session"] = aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(connect=2, total=4),
    )
    logger.info("HTTP-сессия создана")

    await init_db()
    logger.info("БД инициализирована")


async def on_shutdown(application: Application) -> None:
    # Корректное закрытие HTTP-сессии при остановке бота
    session: aiohttp.ClientSession | None = application.bot_data.get("http_session")
    if session and not session.closed:
        await session.close()
        logger.info("HTTP-сессия закрыта")


def main() -> None:
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    # Логирование всех действий (group=-1 — запускается раньше всех)
    application.add_handler(MessageHandler(filters.ALL, log_message), group=-1)
    application.add_handler(CallbackQueryHandler(log_callback), group=-1)

    # Регистрация (onboarding) — должна быть первой
    application.add_handler(build_registration_handler())

    # ConversationHandler для Фото и Видео
    application.add_handler(build_conversation_handler())

    # Простые кнопки меню
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_PROFILE}$"), profile))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_IDEA}$"),    idea))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_PRICING}$"), pricing))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_HELP}$"),    help_cmd))

    logger.info("Бот запущен")
    application.run_polling()


if __name__ == "__main__":
    main()
