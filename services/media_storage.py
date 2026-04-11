"""
services/media_storage.py

Управление медиа-файлами пользователей.
Создаёт структуру папок при регистрации/старте.
"""

import os
import logging
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

# Корневая директория для медиа
MEDIA_ROOT = os.path.join(os.path.dirname(__file__), "..", "media")


def ensure_user_media_dirs(user_id: int) -> str:
    """
    Создаёт папку пользователя и подпапки для медиа.
    Возвращает путь к папке пользователя.
    """
    user_dir = os.path.join(MEDIA_ROOT, str(user_id))
    subdirs = ["references", "photos", "videos"]

    for subdir in subdirs:
        path = os.path.join(user_dir, subdir)
        os.makedirs(path, exist_ok=True)

    logger.info("Media dirs created/verified: %s", user_dir)
    return user_dir


async def download_image(url: str, dest_path: str) -> bool:
    """Скачивает изображение с URL в локальный файл. Возвращает True при успехе."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(dest_path).write_bytes(data)
                    logger.info("Downloaded image: %s → %s (%d bytes)", url, dest_path, len(data))
                    return True
                logger.warning("Download failed: %s → status %d", url, resp.status)
                return False
    except Exception as e:
        logger.error("Download error: %s → %s", url, e)
        return False
