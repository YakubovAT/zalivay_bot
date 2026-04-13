"""
services/image_merger.py

Склейка нескольких изображений в одно (коллаж).
Используется для показа выбранных фото на Шаге 7.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


def merge_photos_horizontal(
    image_paths: list[str],
    output_path: str,
    target_height: int = 400,
    spacing: int = 10,
    bg_color: tuple = (240, 240, 240),
) -> bool:
    """
    Горизонтально склеивает изображения в одно.
    Все фото приводятся к одинаковой высоте target_height.
    """
    if not image_paths:
        return False

    try:
        # Открываем и ресайзим
        resized = []
        for p in image_paths:
            img = Image.open(p).convert("RGB")
            ratio = target_height / img.height
            new_w = int(img.width * ratio)
            img = img.resize((new_w, target_height), Image.Resampling.LANCZOS)
            resized.append(img)

        # Считаем итоговую ширину
        total_width = sum(img.width for img in resized) + spacing * (len(resized) - 1)
        
        # Создаём холст
        canvas = Image.new("RGB", (total_width, target_height), bg_color)

        # Вставляем фото
        x_offset = 0
        for img in resized:
            canvas.paste(img, (x_offset, 0))
            x_offset += img.width + spacing

        # Сохраняем
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, "PNG", quality=95)
        logger.info("Merged %d photos → %s (%dx%d)", len(resized), output_path, total_width, target_height)
        return True

    except Exception as e:
        logger.error("Failed to merge photos: %s", e)
        return False
