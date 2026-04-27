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

# Папка со шрифтами — fonts/ в корне проекта рядом с services/
_FONTS_DIR = Path(__file__).parent.parent / "fonts"

# Цвета
_BG_COLOR   = (0, 0, 0, 100)        # тёмный, ~39% opacity
_TEXT_COLOR = (255, 255, 255, 255)  # белый


def _available_fonts() -> list[Path]:
    """Возвращает список подходящих TTF-шрифтов из fonts/."""
    return [
        p for p in _FONTS_DIR.rglob("*.ttf")
        if "Italic" not in p.name and "Variable" not in p.name and "MORF" not in p.name
    ]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    fonts = _available_fonts()
    if fonts:
        path = random.choice(fonts)
        try:
            font = ImageFont.truetype(str(path), size)
            logger.debug("WATERMARK | font=%s", path.stem)
            return font
        except (OSError, IOError):
            pass
    # Fallback — встроенный шрифт Pillow
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    """Разбивает текст на строки, каждая не шире max_width пикселей."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        bb = draw.textbbox((0, 0), candidate, font=font)
        if bb[2] - bb[0] <= max_width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines or [text]


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
    """Рисует закруглённый прямоугольник + белый текст (одна строка)."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    rx1, ry1 = x - pad_x, y - pad_y
    rx2, ry2 = x + tw + pad_x, y + th + pad_y

    draw.rounded_rectangle([rx1, ry1, rx2, ry2], radius=radius, fill=_BG_COLOR)
    draw.text((x, y), text, font=font, fill=_TEXT_COLOR)


def _draw_label_multiline(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    pad_x: int = 14,
    pad_y: int = 9,
    radius: int = 10,
    line_spacing: int = 6,
) -> None:
    """Рисует многострочный блок с фоном."""
    bboxes      = [draw.textbbox((0, 0), l, font=font) for l in lines]
    line_widths  = [bb[2] - bb[0] for bb in bboxes]
    line_heights = [bb[3] - bb[1] for bb in bboxes]

    max_tw   = max(line_widths)
    total_th = sum(line_heights) + line_spacing * (len(lines) - 1)

    draw.rounded_rectangle(
        [x - pad_x, y - pad_y, x + max_tw + pad_x, y + total_th + pad_y],
        radius=radius,
        fill=_BG_COLOR,
    )
    cy = y
    for line, lh in zip(lines, line_heights):
        draw.text((x, cy), line, font=font, fill=_TEXT_COLOR)
        cy += lh + line_spacing


def apply_watermark(file_path: str, article_code: str, name: str, out_path: str | None = None, article_label: str | None = None) -> str:
    """
    Накладывает текст на изображение и сохраняет копию.

    Позиции по диагонали (рандомно):
      Вариант A: артикул → правый нижний, название → левый верхний
      Вариант B: артикул → левый нижний,  название → правый верхний

    out_path — куда сохранить результат. Если None — рядом с оригиналом.
    Возвращает путь к копии с текстом.
    Оригинальный файл не изменяется.
    """
    p = Path(file_path)
    dest = Path(out_path) if out_path else p.parent / f"{p.stem}_with_text{p.suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)

    img = Image.open(file_path).convert("RGBA")
    w, h = img.size

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    font_size = max(20, int(min(w, h) * 0.045))
    font      = _load_font(font_size)
    margin    = int(min(w, h) * 0.035)

    text_article = article_label if article_label is not None else f"арт. {article_code}"

    pad_x, pad_y = 14, 9

    # Название: перенос слов в пределах своей четверти изображения
    name_max_w  = w // 2 - margin * 2 - pad_x * 2
    name_lines  = _wrap_text(draw, name, font, name_max_w)
    name_bboxes = [draw.textbbox((0, 0), l, font=font) for l in name_lines]
    name_max_lw = max(bb[2] - bb[0] for bb in name_bboxes)

    # Размер артикула (одна строка)
    ab = draw.textbbox((0, 0), text_article, font=font)
    aw, ah = ab[2] - ab[0], ab[3] - ab[1]

    # Артикул поднят выше на margin*2; название опущено ниже на margin*2
    article_raise = margin * 2
    name_drop     = margin * 2

    diagonal = random.choice(("A", "B"))

    if diagonal == "A":
        # артикул → правый нижний (поднят)
        ax = w - aw - pad_x * 2 - margin
        ay = h - ah - pad_y * 2 - margin - article_raise
        # название → левый верхний (опущено)
        nx = margin
        ny = margin + name_drop
    else:
        # артикул → левый нижний (поднят)
        ax = margin
        ay = h - ah - pad_y * 2 - margin - article_raise
        # название → правый верхний (опущено)
        nx = w - name_max_lw - pad_x * 2 - margin
        ny = margin + name_drop

    _draw_label(draw, text_article, ax, ay, font, pad_x, pad_y)
    _draw_label_multiline(draw, name_lines, nx, ny, font, pad_x, pad_y)

    result = Image.alpha_composite(img, overlay).convert("RGB")
    result.save(str(dest), quality=95)

    logger.info(
        "WATERMARK | file=%s → %s | diagonal=%s",
        p.name, dest.name, diagonal,
    )
    return str(dest)


async def apply_watermark_to_media_file(media_file_id: int, user_id: int) -> str | None:
    """
    Async-обёртка: читает media_file из БД, применяет watermark,
    создаёт новую запись media_files для watermark-файла.

    Возвращает путь к файлу с текстом или None при ошибке.
    """
    from database.db import get_media_file_by_id, get_article_info, get_reference, create_watermarked_file
    from services.prompt_store import get_template

    mf = await get_media_file_by_id(media_file_id)
    if not mf:
        logger.warning("WATERMARK | media_file_id=%d не найден", media_file_id)
        return None

    if mf["is_watermark"]:
        logger.warning("WATERMARK | media_file_id=%d уже является watermark-файлом, пропускаем", media_file_id)
        return mf["file_path"]

    article_code = mf["article_code"]
    file_path = mf["file_path"]
    if not file_path:
        logger.warning("WATERMARK | media_file_id=%d не имеет file_path", media_file_id)
        return None

    # Название: приоритет у эталона (product_name), фолбэк — articles.name, затем артикул
    ref = await get_reference(user_id, article_code)
    name = (ref and ref["product_name"]) or None
    if not name:
        article = await get_article_info(user_id, article_code)
        name = (article and article["name"]) or article_code

    try:
        from services.media_storage import MEDIA_ROOT
        p = Path(file_path)
        wm_index = mf["watermark_count"] + 1
        out_dir  = Path(MEDIA_ROOT) / str(user_id) / "watermarked" / article_code
        out_file = out_dir / f"{p.stem}_wm_{wm_index}{p.suffix}"

        label_template = await get_template("watermark_article_label", fallback="арт. {article}")
        article_label = label_template.format(article=article_code)

        out_path = apply_watermark(
            file_path=file_path,
            article_code=article_code,
            name=name,
            out_path=str(out_file),
            article_label=article_label,
        )
        await create_watermarked_file(
            parent_id=media_file_id,
            user_id=user_id,
            article_code=article_code,
            file_path=out_path,
            file_type=mf["file_type"],
        )
        return out_path
    except Exception as e:
        logger.error("WATERMARK | ошибка для media_file_id=%d: %s", media_file_id, e)
        return None
