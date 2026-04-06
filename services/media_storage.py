"""
services/media_storage.py

Управление медиа-файлами пользователей.
Создаёт структуру папок при регистрации/старте.
"""

import os
import logging

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
