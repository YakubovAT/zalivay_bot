"""
services/image_prompt_generator.py

Генератор lifestyle-промпта на основе сцены из БД.

Алгоритм:
  1. По категории товара берём список доступных сцен из prompt_list_items.
  2. Выбираем рандомную сцену.
  3. Загружаем шаблон сцены из prompt_templates.
  4. Находим все {placeholder} в шаблоне.
  5. Для каждого плейсхолдера берём случайное значение из prompt_list_items (list_key = placeholder).
  6. Возвращаем готовый промпт.

Добавить новую сцену = добавить шаблон и списки в БД. Код менять не нужно.
"""

from __future__ import annotations

import logging
import random
import re

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{([^}]+)\}")

_CATEGORY_PREFIX: dict[str, str] = {
    "низ":           "photo_bottom",
    "верх":          "photo_top",
    "обувь":         "photo_shoes",
    "головной убор": "photo_hat",
    "комплект":      "photo_komplekt",
}


async def generate_image_prompt(
    category: str,
    tags: dict | None = None,
) -> str | None:
    """
    Генерирует lifestyle-промпт для заданной категории товара.

    Args:
        category: "низ" | "верх" | "обувь" | "головной убор" | "комплект"
        tags: зарезервировано для будущей фильтрации сцен по сезону/стилю

    Returns:
        Готовый промпт строкой или None при ошибке.
    """
    from services.prompt_store import get_list, get_template

    prefix = _CATEGORY_PREFIX.get(category)
    if not prefix:
        logger.error("image_prompt_generator: неизвестная категория %r", category)
        return None

    scenes = await get_list(f"{prefix}_scenes")
    if not scenes:
        logger.error("image_prompt_generator: нет сцен для %r (key=%s_scenes)", category, prefix)
        return None

    scene = random.choice(scenes)
    template_key = f"{prefix}_{scene}"

    template = await get_template(template_key)
    if not template:
        logger.error("image_prompt_generator: шаблон %r не найден", template_key)
        return None

    placeholders = set(_PLACEHOLDER_RE.findall(template))

    substitutions: dict[str, str] = {}
    for key in placeholders:
        values = await get_list(key)
        if not values:
            logger.error("image_prompt_generator: список %r не найден в БД", key)
            return None
        substitutions[key] = random.choice(values)

    result = template
    for key, value in substitutions.items():
        result = result.replace(f"{{{key}}}", value)

    logger.info(
        "image_prompt_generator: category=%r scene=%s vars=%d prompt_len=%d",
        category, template_key, len(substitutions), len(result),
    )
    return result
