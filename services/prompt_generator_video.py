"""
services/prompt_generator_video.py

Генерация промптов для lifestyle-видео по образу generate_photo_prompts из prompt_generator_cloth.py.

Промпты описывают движение модели в разных локациях.
"""

from __future__ import annotations

import random

# ---------------------------------------------------------------------------
# Локации с описанием движения
# ---------------------------------------------------------------------------

_LOCATIONS_WITH_MOTION = [
    ("a sunny city street", "walking confidently"),
    ("a modern coffee shop", "sitting down gracefully"),
    ("a lush green park", "strolling leisurely"),
    ("a bright minimalist studio", "turning slowly"),
    ("a seaside promenade", "walking along the waterfront"),
    ("a stylish rooftop terrace", "standing and looking into the distance"),
    ("a cozy indoor café", "picking up a cup"),
    ("a vibrant flower market", "walking through the stalls"),
    ("a clean white studio backdrop", "posing and turning"),
    ("an urban pedestrian bridge", "walking toward the camera"),
    ("a forest path in autumn", "walking through falling leaves"),
    ("a luxury hotel lobby", "walking through the entrance"),
]

# ---------------------------------------------------------------------------
# Дополняющие элементы одежды по категории
# ---------------------------------------------------------------------------

_BOTTOM_ITEMS = [
    ("white jeans", "light"),
    ("black slim trousers", "dark"),
    ("beige linen pants", "neutral"),
    ("light blue denim skirt", "blue"),
    ("khaki wide-leg pants", "khaki"),
]

_TOP_ITEMS = [
    ("white fitted t-shirt", "white"),
    ("light beige blouse", "beige"),
    ("soft grey knit", "grey"),
    ("pastel pink turtleneck", "pink"),
    ("navy blue shirt", "navy"),
]

_NEUTRAL_OUTFITS = [
    "neutral beige linen outfit",
    "minimalist white and grey ensemble",
    "simple monochrome look",
]

# ---------------------------------------------------------------------------
# Шаблоны промптов по категории
# ---------------------------------------------------------------------------

PROMPT_TOP = (
    "A fashion lifestyle video. A model wearing {description}, "
    "paired with {item_color} {item}. "
    "Location: {location}. "
    "The model is {motion}. "
    "Smooth cinematic camera movement, natural lighting, "
    "sharp focus on the clothing, professional e-commerce fashion video."
)

PROMPT_BOTTOM = (
    "A fashion lifestyle video. A model wearing {description}, "
    "paired with {item_color} {item}. "
    "Location: {location}. "
    "The model is {motion}. "
    "Smooth cinematic camera movement, natural lighting, "
    "sharp focus on the clothing, professional e-commerce fashion video."
)

PROMPT_SHOES = (
    "A fashion lifestyle video. A model wearing {description}, "
    "styled with a {outfit}. "
    "Location: {location}. "
    "The model is {motion}, with camera focus on the footwear. "
    "Smooth cinematic camera movement, natural lighting, "
    "sharp focus on the shoes, professional e-commerce fashion video."
)

PROMPT_HAT = (
    "A fashion lifestyle video. A model wearing {description}, "
    "styled with a {outfit}. "
    "Location: {location}. "
    "The model is {motion}, with camera focus on the headwear. "
    "Smooth cinematic camera movement, natural lighting, "
    "sharp focus on the hat, professional e-commerce fashion video."
)

_CATEGORY_MAP = {
    "верх":           ("top",  PROMPT_TOP),
    "низ":            ("bottom", PROMPT_BOTTOM),
    "обувь":          ("shoes", PROMPT_SHOES),
    "головной убор":  ("hat", PROMPT_HAT),
}


def generate_video_prompts(description: str, category: str, count: int) -> list[str]:
    """
    Генерирует список уникальных EN-промптов для lifestyle-видео.

    Args:
        description: product_description из article_references (EN)
        category: верх / низ / обувь / головной убор
        count: количество видео

    Returns:
        Список промптов длиной count
    """
    cat_key, template = _CATEGORY_MAP.get(category.lower(), ("top", PROMPT_TOP))

    prompts: list[str] = []
    locations = random.sample(_LOCATIONS_WITH_MOTION, min(count, len(_LOCATIONS_WITH_MOTION)))
    # Если видео больше чем локаций — повторяем
    while len(locations) < count:
        locations += random.sample(_LOCATIONS_WITH_MOTION, min(count - len(locations), len(_LOCATIONS_WITH_MOTION)))

    for i in range(count):
        location, motion = locations[i]

        if cat_key == "top":
            item_color, item = random.choice(_BOTTOM_ITEMS)
            prompt = template.format(
                description=description,
                item=item,
                item_color=item_color,
                location=location,
                motion=motion,
            )
        elif cat_key == "bottom":
            item_color, item = random.choice(_TOP_ITEMS)
            prompt = template.format(
                description=description,
                item=item,
                item_color=item_color,
                location=location,
                motion=motion,
            )
        else:
            outfit = random.choice(_NEUTRAL_OUTFITS)
            prompt = template.format(
                description=description,
                outfit=outfit,
                location=location,
                motion=motion,
            )

        prompts.append(prompt)

    return prompts
