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
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from database.db import (
    get_article_info,
    get_all_unexported_media_files,
    get_pinterest_settings,
    get_reference_product_name,
    mark_pinterest_exported,
)
from services.media_storage import get_public_media_url
from services.prompt_store import get_list

logger = logging.getLogger(__name__)

_TITLE_PREFIXES_FALLBACK = ["Новинка", "Тренд", "Хит", "Must have", "Стиль"]

_STYLE_PHRASES_FALLBACK = [
    "Элегантный образ на каждый день.",
    "Стильное решение для любого случая.",
    "Комфорт и красота в одном.",
    "Подчеркни свою индивидуальность.",
    "Модный акцент вашего гардероба.",
]

_THUMBNAILS = ["0:01", "0:02", "0:03", "0:04", ""]
_THUMBNAIL_WEIGHTS = [20, 20, 20, 20, 20]


def _select_files(
    all_files: list,
    count: int,
    distribution_mode: str,
    priority_article_code: str | None,
) -> list:
    """
    Выбирает файлы согласно режиму распределения.

    distribution_mode:
      "random"   — случайная выборка из всех (текущее поведение)
      "equal"    — поровну по артикулам; остаток добирается случайно
      "priority" — половина из priority_article_code, остаток поровну из остальных артикулов
    """
    if distribution_mode == "random" or not all_files:
        return random.sample(all_files, min(count, len(all_files)))

    by_article: dict[str, list] = defaultdict(list)
    for f in all_files:
        by_article[f["article_code"]].append(f)

    if distribution_mode == "priority":
        if not priority_article_code:
            raise ValueError("priority_article_code required for distribution_mode='priority'")
        priority_files = by_article.pop(priority_article_code, [])
        priority_take  = min(len(priority_files), count // 2)
        selected = list(random.sample(priority_files, priority_take))
        remaining_count = count - priority_take
        # Остаток — поровну из оставшихся артикулов
        others_by_article = dict(by_article)
        return selected + _distribute_equal(others_by_article, remaining_count)

    elif distribution_mode == "equal":
        return _distribute_equal(dict(by_article), count)

    else:
        raise ValueError(f"Unknown distribution_mode: {distribution_mode!r}")


def _distribute_equal(by_article: dict[str, list], count: int) -> list:
    """Вспомогательная: поровну по артикулам, остаток случайно из leftover."""
    articles = list(by_article.keys())
    n = len(articles)
    if n == 0 or count == 0:
        return []
    per_article = count // n
    selected: list = []
    leftover: list = []
    for files in by_article.values():
        take = min(per_article, len(files))
        chosen = random.sample(files, take)
        chosen_ids = {f["id"] for f in chosen}
        selected.extend(chosen)
        leftover.extend(f for f in files if f["id"] not in chosen_ids)
    needed = count - len(selected)
    if needed > 0 and leftover:
        selected.extend(random.sample(leftover, min(needed, len(leftover))))
    return selected

CSV_COLUMNS = [
    "Title", "Media URL", "Pinterest board",
    "Thumbnail", "Description", "Link", "Publish date", "Keywords",
]


def _file_path_to_public_url(user_id: int, file_path: str) -> str:
    """Конвертирует локальный путь в публичный URL на нашем сервере.

    Работает с относительными и абсолютными путями:
      "media/171470918/generated/38959282/photo.png"
      "/var/www/bots/.../media/171470918/watermarked/225616209/photo_with_text.png"
    → https://zaliv.ai/media/171470918/...
    """
    prefix = f"media/{user_id}/"
    idx = file_path.find(prefix)
    if idx != -1:
        relative = file_path[idx + len(prefix):]
    else:
        relative = file_path.lstrip("/")
    return get_public_media_url(user_id, relative)


def _first_word(text: str) -> str:
    return text.split()[0] if text else ""


def _first_color(color: str) -> str:
    return color.split(";")[0].strip() if color else ""


def _build_title(color: str, name: str, prefix: str, article: str, index: int) -> str:
    return f"{_first_color(color)} {_first_word(name)} {prefix} {article} {index:04d}".strip()


def _build_description(name: str, color: str, hashtags: list[str], phrases: list[str] | None = None) -> str:
    phrase = random.choice(phrases if phrases else _STYLE_PHRASES_FALLBACK)
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
    article_code_filter: str | None = None,
    distribution_mode: str = "random",
    priority_article_code: str | None = None,
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

    title_prefixes = await get_list("pinterest_title_prefixes") or _TITLE_PREFIXES_FALLBACK
    style_phrases = await get_list("pinterest_style_phrases") or _STYLE_PHRASES_FALLBACK

    all_files = await get_all_unexported_media_files(user_id)
    all_files = [f for f in all_files if f["article_code"] != "00000"]
    if article_code_filter:
        all_files = [f for f in all_files if f["article_code"] == article_code_filter]
    total_available = len(all_files)

    selected = _select_files(all_files, rows_count, distribution_mode, priority_article_code)

    publish_dt = datetime.now(timezone.utc) + timedelta(hours=1)

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
            ref_product_name = await get_reference_product_name(user_id, article_code)

            prefix = random.choice(title_prefixes)
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
            description = _build_description(name, color, settings.get("hashtags") or [], style_phrases)[:500]
            link = _build_link(settings.get("link_template"), article_code, index)
            # Board обязателен для Pinterest; приоритет — имя из эталона.
            board = (ref_product_name or "").strip() or name or settings.get("board") or article_code

            step_minutes = random.randint(40, 48)
            publish_dt += timedelta(minutes=step_minutes)

            media_url = _file_path_to_public_url(user_id, mf["file_path"]) if mf["file_path"] else ""

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
