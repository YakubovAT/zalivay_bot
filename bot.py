import logging

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
logger = logging.getLogger(__name__)


async def on_startup(application: Application):
    await init_db()
    logger.info("БД инициализирована")


def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
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
