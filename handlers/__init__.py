# TODO: переписать с нуля
import logging
from telegram import Update
from telegram.ext import ContextTypes
from handlers.flows.onboarding import build_onboarding_handler  # noqa
from handlers.flows.new_article import build_new_article_handler  # noqa
from handlers.flows.create_reference import build_reference_handler  # noqa
from handlers.flows.etalon import build_etalon_handler  # noqa
from handlers.flows.photo import build_photo_handler  # noqa
from handlers.flows.video import build_video_handler  # noqa

logger = logging.getLogger(__name__)


async def log_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        msg_type = update.message.content_type if hasattr(update.message, 'content_type') else 'unknown'
        logger.info("MSG | user=%s type=%s text=%s", update.effective_user.id, msg_type, update.message.text)


async def log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        logger.info("CB | user=%s data=%s", query.from_user.id, query.data)
