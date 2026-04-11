"""
handlers/__init__.py

Центральный экспорт всех обработчиков бота.
"""

# ---------------------------------------------------------------------------
# Flows (ConversationHandler'ы)
# ---------------------------------------------------------------------------
from .flows.onboarding import (
    build_onboarding_handler,
    cmd_start,
    ONBOARD_SELECT_MP, ONBOARD_ARTICLE,
    ONBOARD_REF_CHOICE, ONBOARD_REF_FEEDBACK, ONBOARD_REDO_FEEDBACK,
    PHOTO_COUNT_CHOICE, PHOTO_MULTI_COUNT,
)
from .flows.etalon import build_etalon_handler
from .flows.photo import build_photo_handler
from .flows.video import build_video_handler

# ---------------------------------------------------------------------------
# Простые обработчики (без ConversationHandler)
# ---------------------------------------------------------------------------
from .flows.profile import profile
from .flows.pricing import pricing
from .flows.help_cmd import help_cmd

# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------
from .keyboards import (
    BTN_PROFILE, BTN_PHOTO, BTN_VIDEO, BTN_ETALON,
    BTN_PRICING, BTN_HELP, BTN_RESTART, MENU_BUTTONS,
    back_button, back_to_menu_button,
    mp_select_keyboard, etalon_create_keyboard, etalon_feedback_keyboard,
    etalon_feedback_with_continue_keyboard, photo_count_keyboard,
    etalon_existing_keyboard, etalon_done_keyboard,
)

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
from .action_logger import log_message, log_callback

__all__ = [
    # Handlers (factories)
    "build_onboarding_handler",
    "build_etalon_handler",
    "build_photo_handler",
    "build_video_handler",
    # Handlers (simple)
    "cmd_start",
    "profile",
    "pricing",
    "help_cmd",
    # States
    "ONBOARD_SELECT_MP", "ONBOARD_ARTICLE",
    "ONBOARD_REF_CHOICE", "ONBOARD_REF_FEEDBACK", "ONBOARD_REDO_FEEDBACK",
    "PHOTO_COUNT_CHOICE", "PHOTO_MULTI_COUNT",
    # Keyboards
    "BTN_PROFILE", "BTN_PHOTO", "BTN_VIDEO", "BTN_ETALON",
    "BTN_PRICING", "BTN_HELP", "BTN_RESTART", "MENU_BUTTONS",
    "back_button", "back_to_menu_button",
    "mp_select_keyboard", "etalon_create_keyboard", "etalon_feedback_keyboard",
    "etalon_feedback_with_continue_keyboard", "photo_count_keyboard",
    "etalon_existing_keyboard", "etalon_done_keyboard",
    # Logging
    "log_message", "log_callback",
]
