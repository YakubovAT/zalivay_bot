import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN    = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "ZalivaiBot")   # username без @, для Telegram Login Widget
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/zalivai_db")

# ---------------------------------------------------------------------------
# Тарифы (руб.)
# ---------------------------------------------------------------------------

REFERENCE_COST = int(os.getenv("REFERENCE_COST", "5"))       # Создание эталона
PHOTO_COST     = int(os.getenv("PHOTO_COST", "5"))            # Одно фото
VIDEO_COST     = int(os.getenv("VIDEO_COST", "20"))           # Одно видео

# AI провайдер — T2T (текстовая модель)
AI_API_KEY     = os.getenv("AI_API_KEY", "cbc437104f5c302e296b8771ca523030")
AI_API_BASE    = os.getenv("AI_API_BASE", "https://api.kie.ai")
AI_MODEL       = os.getenv("AI_MODEL", "gpt-5-2")

# I2I (генерация изображений) — реальный API KIE.ai
I2I_API_KEY    = os.getenv("I2I_API_KEY", AI_API_KEY)  # тот же ключ что и T2T
I2I_API_BASE   = os.getenv("I2I_API_BASE", "https://api.kie.ai")

# I2V (генерация видео) — модель KIE.ai image-to-video
VIDEO_I2V_MODEL = os.getenv("VIDEO_I2V_MODEL", "sora-2-image-to-video")

# ---------------------------------------------------------------------------
# Баннер — единая ширина сообщений
# ---------------------------------------------------------------------------
BANNER_PATH = os.getenv("BANNER_PATH", "assets/banner_default.png")
