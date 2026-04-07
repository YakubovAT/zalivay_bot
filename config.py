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

# AI провайдер — T2T (текстовая модель)
AI_API_KEY     = os.getenv("AI_API_KEY", "cbc437104f5c302e296b8771ca523030")
AI_API_BASE    = os.getenv("AI_API_BASE", "https://api.kie.ai")
AI_MODEL       = os.getenv("AI_MODEL", "gpt-5-2")

# I2I (генерация изображений) — пока mock-сервер
I2I_API_KEY    = os.getenv("I2I_API_KEY", "mock")
I2I_API_BASE   = os.getenv("I2I_API_BASE", "http://localhost:8080")
