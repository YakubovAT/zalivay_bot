import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/zalivai_db")

# ---------------------------------------------------------------------------
# Тарифы (руб.)
# ---------------------------------------------------------------------------

REFERENCE_COST = int(os.getenv("REFERENCE_COST", "100"))       # Создание эталона
PHOTO_COST     = int(os.getenv("PHOTO_COST", "50"))            # Одно фото
VIDEO_COST     = int(os.getenv("VIDEO_COST", "200"))           # Одно видео

# AI провайдер
AI_API_KEY     = os.getenv("AI_API_KEY", "")
AI_API_BASE    = os.getenv("AI_API_BASE", "https://api.kie.ai")
AI_MODEL       = os.getenv("AI_MODEL", "gpt-5-2")
