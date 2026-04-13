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
    Создаёт симлинк для nginx раздачи: /var/www/media/{user_id} → ...
    Возвращает путь к папке пользователя.
    """
    user_dir = os.path.join(MEDIA_ROOT, str(user_id))
    subdirs = ["references", "photos", "videos"]

    for subdir in subdirs:
        path = os.path.join(user_dir, subdir)
        os.makedirs(path, exist_ok=True)

    # Создаём симлинк для nginx: /var/www/media/{user_id} → media/{user_id}/
    nginx_media_root = "/var/www/media"
    os.makedirs(nginx_media_root, exist_ok=True)
    symlink_path = os.path.join(nginx_media_root, str(user_id))
    abs_user_dir = os.path.abspath(user_dir)
    if not os.path.exists(symlink_path) and not os.path.islink(symlink_path):
        try:
            os.symlink(abs_user_dir, symlink_path)
            logger.info("Symlink created: %s → %s", symlink_path, abs_user_dir)
        except OSError as e:
            logger.warning("Symlink creation failed: %s", e)

    logger.info("Media dirs created/verified: %s", user_dir)
    return user_dir


def get_public_media_url(user_id: int, relative_path: str) -> str:
    """
    Возвращает публичный URL для медиафайла на нашем сервере.
    Пример: get_public_media_url(171470918, 'references/400015193_ref_final.png')
      → https://zaliv.ai/media/171470918/references/400015193_ref_final.png
    """
    return f"https://zaliv.ai/media/{user_id}/{relative_path.lstrip('/')}"


def ensure_article_media_dir(user_id: int, marketplace: str, article_code: str) -> str:
    """
    Создаёт папку для артикула: media/{user_id}/{marketplace}/{article_code}/
    Возвращает путь к папке.
    """
    article_dir = os.path.join(MEDIA_ROOT, str(user_id), marketplace.upper(), article_code)
    os.makedirs(article_dir, exist_ok=True)
    logger.info("Article media dir created: %s", article_dir)
    return article_dir


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


async def download_all_images(urls: list[str], dest_dir: str) -> list[str]:
    """
    Скачивает все изображения в папку.
    Возвращает список локальных путей скачанных файлов.
    """
    local_paths = []
    for i, url in enumerate(urls, 1):
        ext = url.rsplit(".", 1)[-1] if "." in url else "webp"
        dest_path = os.path.join(dest_dir, f"{i}.{ext}")
        ok = await download_image(url, dest_path)
        if ok:
            local_paths.append(dest_path)
    return local_paths
