"""
services/image_watermark.py

Независимый сервис наложения текста на изображение.

Накладывает два текстовых блока по диагонали (рандомно):
  - артикул товара: "арт. 12345678"
  - название товара: "Юбка летняя"

Каждый блок — белый текст на полупрозрачном прямоугольнике
с закруглёнными углами. Читается на любом фоне.

Публичный API:
    apply_watermark(file_path, article_code, name) -> str
        Синхронная функция. Сохраняет копию рядом с оригиналом,
        возвращает путь к новому файлу. Оригинал не изменяется.

    apply_watermark_to_media_file(media_file_id, user_id) -> str | None
        Async-обёртка: читает данные из БД, вызывает apply_watermark,
        сохраняет результат в media_files.watermarked_path.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Пути к шрифтам (перебираем до первого найденного)
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",          # macOS
    "/Library/Fonts/Arial Bold.ttf",                # macOS
]

# Цвета
_BG_COLOR   = (0, 0, 0, 170)        # тёмный, ~67% opacity
_TEXT_COLOR = (255, 255, 255, 255)  # белый


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    # Fallback — встроенный шрифт Pillow (>=10.0 поддерживает size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _draw_label(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    pad_x: int = 14,
    pad_y: int = 9,
    radius: int = 10,
) -> None:
    """Рисует закруглённый прямоугольник + белый текст."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    rx1, ry1 = x - pad_x, y - pad_y
    rx2, ry2 = x + tw + pad_x, y + th + pad_y

    draw.rounded_rectangle([rx1, ry1, rx2, ry2], radius=radius, fill=_BG_COLOR)
    draw.text((x, y), text, font=font, fill=_TEXT_COLOR)


def apply_watermark(file_path: str, article_code: str, name: str) -> str:
    """
    Накладывает текст на изображение и сохраняет копию.

    Позиции по диагонали (рандомно):
      Вариант A: артикул → правый нижний, название → левый верхний
      Вариант B: артикул → левый нижний,  название → правый верхний

    Возвращает путь к копии с текстом.
    Оригинальный файл не изменяется.
    """
    p = Path(file_path)
    out_path = p.parent / f"{p.stem}_with_text{p.suffix}"

    img = Image.open(file_path).convert("RGBA")
    w, h = img.size

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    font_size = max(20, int(min(w, h) * 0.045))
    font      = _load_font(font_size)
    margin    = int(min(w, h) * 0.035)

    text_article = f"арт. {article_code}"
    text_name    = name[:40]  # на случай очень длинного названия

    # Размеры текстов для вычисления позиций
    def text_size(txt: str) -> tuple[int, int]:
        bb = draw.textbbox((0, 0), txt, font=font)
        return bb[2] - bb[0], bb[3] - bb[1]

    pad_x, pad_y = 14, 9
    aw, ah = text_size(text_article)
    nw, nh = text_size(text_name)

    diagonal = random.choice(("A", "B"))

    if diagonal == "A":
        # артикул → правый нижний
        ax = w - aw - pad_x * 2 - margin
        ay = h - ah - pad_y * 2 - margin
        # название → левый верхний
        nx, ny = margin, margin
    else:
        # артикул → левый нижний
        ax = margin
        ay = h - ah - pad_y * 2 - margin
        # название → правый верхний
        nx = w - nw - pad_x * 2 - margin
        ny = margin

    _draw_label(draw, text_article, ax, ay, font, pad_x, pad_y)
    _draw_label(draw, text_name,    nx, ny, font, pad_x, pad_y)

    result = Image.alpha_composite(img, overlay).convert("RGB")
    result.save(str(out_path), quality=95)

    logger.info(
        "WATERMARK | file=%s → %s | diagonal=%s",
        p.name, out_path.name, diagonal,
    )
    return str(out_path)


async def apply_watermark_to_media_file(media_file_id: int, user_id: int) -> str | None:
    """
    Async-обёртка: читает media_file из БД, применяет watermark,
    сохраняет watermarked_path обратно в БД.

    Возвращает путь к файлу с текстом или None при ошибке.
    """
    from database.db import get_media_file_by_id, get_article_info, save_watermarked_path

    mf = await get_media_file_by_id(media_file_id)
    if not mf:
        logger.warning("WATERMARK | media_file_id=%d не найден", media_file_id)
        return None

    # Если копия уже есть — возвращаем её
    if mf["watermarked_path"]:
        return mf["watermarked_path"]

    article = await get_article_info(user_id, mf["article_code"])
    if not article:
        logger.warning("WATERMARK | артикул %s не найден", mf["article_code"])
        return None

    file_path = mf["file_path"]
    if not file_path:
        logger.warning("WATERMARK | media_file_id=%d не имеет file_path", media_file_id)
        return None

    try:
        out_path = apply_watermark(
            file_path=file_path,
            article_code=mf["article_code"],
            name=article["name"] or mf["article_code"],
        )
        await save_watermarked_path(media_file_id, out_path)
        return out_path
    except Exception as e:
        logger.error("WATERMARK | ошибка для media_file_id=%d: %s", media_file_id, e)
        return None
