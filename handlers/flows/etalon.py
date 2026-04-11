# TODO: переписать с нуля
from telegram.ext import ConversationHandler


def build_etalon_handler() -> ConversationHandler:
    return ConversationHandler(entry_points=[], states={}, fallbacks=[])
