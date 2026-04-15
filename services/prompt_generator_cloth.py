"""
services/prompt_generator_cloth.py

Локальный генератор lifestyle-промптов для I2I на основе категории товара.

Логика:
  - Описание товара (description) берётся из article_references.product_description
  - Категория берётся из article_references.category (верх/низ/обувь/головной убор)
  - N промптов генерируются случайно: location × item × color
  - Никаких T2T запросов — всё на английском прямо в коде
"""

from __future__ import annotations

import random
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Переменные
# ---------------------------------------------------------------------------

LOCATIONS = [
    "city park with green trees",
    "minimalist photo studio with soft light",
    "city street with urban background",
    "cozy cafe interior",
    "sandy beach at sunset",
    "forest path in autumn",
    "river embankment promenade",
    "modern office lobby",
    "rooftop terrace with city view",
    "shopping street with storefronts",
    "botanical garden with flowers",
    "loft interior with brick walls",
]

# Предметы низа (для категории "верх")
BOTTOM_ITEMS = [
    "jeans",
    "trousers",
    "skirt",
    "shorts",
    "leggings",
    "palazzo pants",
    "straight-leg pants",
    "midi skirt",
]

# Предметы верха (для категории "низ")
TOP_ITEMS = [
    "t-shirt",
    "shirt",
    "sweater",
    "blouse",
    "hoodie",
    "top",
    "cardigan",
    "turtleneck",
]

# Нейтральный аутфит (для обуви и головных уборов)
NEUTRAL_OUTFITS = [
    "white t-shirt and blue jeans",
    "beige sweater and black trousers",
    "black blouse and white skirt",
    "grey hoodie and dark jeans",
    "striped shirt and beige trousers",
]

COLORS = [
    "white",
    "black",
    "navy blue",
    "beige",
    "light grey",
    "dark brown",
    "olive green",
    "pastel pink",
    "cream",
    "charcoal",
]

# ---------------------------------------------------------------------------
# Шаблоны промптов
# ---------------------------------------------------------------------------

PROMPT_TOP = (
    "Professional lifestyle fashion photograph. "
    "A model wearing {description}, "
    "paired with {item_color} {bottom_item}. "
    "Location: {location}. "
    "Natural relaxed pose, high-quality e-commerce photography, "
    "realistic lighting, sharp focus on the clothing."
)

PROMPT_BOTTOM = (
    "Professional lifestyle fashion photograph. "
    "A model wearing {description}, "
    "paired with {item_color} {top_item}. "
    "Location: {location}. "
    "Natural relaxed pose, high-quality e-commerce photography, "
    "realistic lighting, sharp focus on the clothing."
)

PROMPT_SHOES = (
    "Professional lifestyle fashion photograph. "
    "A model wearing {description}. "
    "Outfit: {neutral_outfit}. "
    "Location: {location}. "
    "Natural relaxed pose, high-quality e-commerce photography, "
    "realistic lighting, focus on the footwear."
)

PROMPT_HAT = (
    "Professional lifestyle fashion photograph. "
    "A model wearing {description}. "
    "Outfit: {neutral_outfit}. "
    "Location: {location}. "
    "Natural relaxed pose, high-quality e-commerce photography, "
    "realistic lighting, focus on the headwear."
)

# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def generate_photo_prompts(
    description: str,
    category: str,
    count: int,
) -> list[str]:
    """
    Генерирует список из `count` уникальных lifestyle-промптов для I2I.

    Args:
        description: готовое EN-описание товара из article_references.product_description
        category: верх / низ / обувь / головной убор
        count: количество фото

    Returns:
        Список EN промптов длиной count.
    """
    prompts = []
    category = category.lower().strip()

    for i in range(count):
        location = random.choice(LOCATIONS)

        if category == "верх":
            prompt = PROMPT_TOP.format(
                description=description,
                bottom_item=random.choice(BOTTOM_ITEMS),
                item_color=random.choice(COLORS),
                location=location,
            )

        elif category == "низ":
            prompt = PROMPT_BOTTOM.format(
                description=description,
                top_item=random.choice(TOP_ITEMS),
                item_color=random.choice(COLORS),
                location=location,
            )

        elif category == "обувь":
            prompt = PROMPT_SHOES.format(
                description=description,
                neutral_outfit=random.choice(NEUTRAL_OUTFITS),
                location=location,
            )

        elif category == "головной убор":
            prompt = PROMPT_HAT.format(
                description=description,
                neutral_outfit=random.choice(NEUTRAL_OUTFITS),
                location=location,
            )

        else:
            # Неизвестная категория — используем нейтральный шаблон
            logger.warning("Unknown category %r, using neutral template", category)
            prompt = PROMPT_SHOES.format(
                description=description,
                neutral_outfit=random.choice(NEUTRAL_OUTFITS),
                location=location,
            )

        prompts.append(prompt)
        logger.debug("PROMPT #%d | category=%s | %s", i + 1, category, prompt[:80])

    logger.info(
        "PROMPT_GENERATOR | category=%s | count=%d | generated=%d",
        category, count, len(prompts),
    )
    return prompts
