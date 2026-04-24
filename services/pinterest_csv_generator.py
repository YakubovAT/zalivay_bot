"""
services/pinterest_csv_generator.py

Генератор CSV для загрузки медиаконтента в Pinterest.
Универсальный: вызывается из Telegram-бота и веб-панели.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone

from database.db import (
    get_article_info,
    get_all_unexported_media_files,
    get_pinterest_settings,
    mark_pinterest_exported,
)
from services.media_storage import get_public_media_url

logger = logging.getLogger(__name__)

_TITLE_PREFIXES = ["Новинка", "Тренд", "Хит", "Must have", "Стиль"]

_STYLE_PHRASES = [
    "Элегантный образ на каждый день.",
    "Стильное решение для любого случая.",
    "Комфорт и красота в одном.",
    "Подчеркни свою индивидуальность.",
    "Модный акцент вашего гардероба.",
]

_THUMBNAILS = ["0:01", "0:02", "0:03", "0:04", ""]
_THUMBNAIL_WEIGHTS = [20, 20, 20, 20, 20]

CSV_COLUMNS = [
    "Title", "Media URL", "Pinterest board",
    "Thumbnail", "Description", "Link", "Publish date", "Keywords",
]


def _file_path_to_public_url(user_id: int, file_path: str) -> str:
    """Конвертирует локальный путь в публичный URL на нашем сервере.

    file_path вида "media/171470918/generated/38959282/photo.png"
    → https://zaliv.ai/media/171470918/generated/38959282/photo.png
    """
    prefix = f"media/{user_id}/"
    if file_path.startswith(prefix):
        relative = file_path[len(prefix):]
    else:
        relative = file_path.lstrip("/")
    return get_public_media_url(user_id, relative)


def _first_word(text: str) -> str:
    return text.split()[0] if text else ""


def _first_color(color: str) -> str:
    return color.split(";")[0].strip() if color else ""


def _build_title(color: str, name: str, prefix: str, article: str, index: int) -> str:
    return f"{_first_color(color)} {_first_word(name)} {prefix} {article} {index:04d}".strip()


def _build_description(name: str, color: str, hashtags: list[str]) -> str:
    phrase = random.choice(_STYLE_PHRASES)
    tags = random.sample(hashtags, min(5, len(hashtags))) if hashtags else []
    hashtag_str = " ".join(f"#{t}" for t in tags)
    return f"{name} {_first_color(color)}. {phrase} {hashtag_str}".strip()


def _build_link(template: str | None, article: str, index: int) -> str:
    if not template:
        return ""
    try:
        return template.format(article=article, index=index)
    except (KeyError, ValueError):
        return template


async def generate_pinterest_csv(
    user_id: int,
    rows_count: int,
    output_format: str = "csv",
) -> dict:
    """
    Генерирует CSV для Pinterest.

    rows_count — желаемое количество строк (1-200).
    Файлы выбираются рандомно из всех необработанных медиафайлов пользователя.

    Возвращает dict:
        batch_id        — uuid[:8]
        content         — CSV-строка | JSON-строка | list[dict]
        processed_files — list[int] id из media_files
        total_available — int, сколько файлов было доступно до генерации
        stats           — {count, errors}
    """
    batch_id = uuid.uuid4().hex[:8]
    rows: list[dict] = []
    exported_ids: list[int] = []
    errors: list[str] = []
    used_titles: set[str] = set()

    all_files = await get_all_unexported_media_files(user_id)
    total_available = len(all_files)

    selected = random.sample(all_files, min(rows_count, len(all_files)))

    publish_dt = datetime.now(timezone.utc) + timedelta(days=1)

    for index, mf in enumerate(selected, start=1):
        article_code = mf["article_code"]
        try:
            article = await get_article_info(user_id, article_code)
            if not article:
                errors.append(f"Артикул {article_code} не найден")
                logger.warning("PINTEREST | артикул не найден: %s", article_code)
                continue

            settings = await get_pinterest_settings(user_id, article_code)
            name = article["name"] or ""
            color = article["color"] or ""

            prefix = random.choice(_TITLE_PREFIXES)
            title = _build_title(color, name, prefix, article_code, index)

            suffix = 1
            base_title = title
            while title in used_titles:
                title = f"{base_title} {suffix}"
                suffix += 1
            used_titles.add(title)
            title = title[:100]

            # Thumbnail только для видео
            is_video = mf["file_type"] == "video"
            thumbnail = random.choices(_THUMBNAILS[:-1], weights=_THUMBNAIL_WEIGHTS[:-1], k=1)[0] if is_video else ""
            description = _build_description(name, color, settings.get("hashtags") or [])[:500]
            link = _build_link(settings.get("link_template"), article_code, index)
            # Board обязателен для Pinterest; fallback — название товара
            board = settings.get("board") or name or article_code

            step_minutes = random.randint(30, 120)
            publish_dt += timedelta(minutes=step_minutes)

            media_url = _file_path_to_public_url(user_id, mf["file_path"]) if mf["file_path"] else mf["result_url"] or ""

            rows.append({
                "Title": title,
                "Media URL": media_url,
                "Pinterest board": board,
                "Thumbnail": thumbnail,
                "Description": description,
                "Link": link,
                "Publish date": publish_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "Keywords": "",
            })
            exported_ids.append(mf["id"])

        except Exception as e:
            logger.error("PINTEREST | ошибка для файла id=%d: %s", mf["id"], e)
            errors.append(f"Файл {mf['id']}: {e}")

    if exported_ids:
        await mark_pinterest_exported(exported_ids)

    if output_format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
        content: str | list = "﻿" + buf.getvalue()
    elif output_format == "json":
        content = json.dumps(rows, ensure_ascii=False, indent=2)
    else:
        content = rows

    return {
        "batch_id": batch_id,
        "content": content,
        "processed_files": exported_ids,
        "total_available": total_available,
        "stats": {"count": len(rows), "errors": errors},
    }
