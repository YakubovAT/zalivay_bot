"""
services/prompt_generator_cloth.py

Создатель lifestyle-промптов для I2I (фото) на основе категории товара.

Данные (шаблоны, локации, одежда, цвета) хранятся в БД и читаются
через services.prompt_store с TTL-кэшем 60 сек.
При недоступности БД — автоматический fallback на значения из prompt_store.
"""

from __future__ import annotations

import random
import logging

logger = logging.getLogger(__name__)


async def generate_photo_prompts(
    description: str,
    category: str,
    count: int,
) -> list[str]:
    """
    Создает список из `count` уникальных lifestyle-промптов для I2I.

    Args:
        description: EN-описание товара из article_references.product_description
        category:    верх / низ / обувь / головной убор
        count:       количество фото

    Returns:
        Список EN-промптов длиной count.
    """
    from services.prompt_store import get_template, get_list

    locations      = await get_list("photo_locations")
    bottom_items   = await get_list("photo_bottom_items")
    top_items      = await get_list("photo_top_items")
    neutral_outfits = await get_list("photo_neutral_outfits")
    colors         = await get_list("photo_colors")

    prompts: list[str] = []
    category = category.lower().strip()

    for i in range(count):
        location = random.choice(locations)

        if category == "верх":
            template = await get_template("photo_top")
            prompt = template.format(
                description=description,
                bottom_item=random.choice(bottom_items),
                item_color=random.choice(colors),
                location=location,
            )

        elif category == "низ":
            template = await get_template("photo_bottom")
            prompt = template.format(
                description=description,
                top_item=random.choice(top_items),
                item_color=random.choice(colors),
                location=location,
            )

        elif category == "обувь":
            template = await get_template("photo_shoes")
            prompt = template.format(
                description=description,
                neutral_outfit=random.choice(neutral_outfits),
                location=location,
            )

        elif category == "головной убор":
            template = await get_template("photo_hat")
            prompt = template.format(
                description=description,
                neutral_outfit=random.choice(neutral_outfits),
                location=location,
            )

        elif category == "комплект":
            template = await get_template("photo_komplekt")
            prompt = template.format(
                description=description,
                neutral_outfit=random.choice(neutral_outfits),
                location=location,
            )

        else:
            logger.warning("generate_photo_prompts: неизвестная категория %r, используем photo_komplekt", category)
            template = await get_template("photo_komplekt")
            prompt = template.format(
                description=description,
                neutral_outfit=random.choice(neutral_outfits),
                location=location,
            )

        prompts.append(prompt)
        logger.debug("PROMPT #%d | category=%s | %s", i + 1, category, prompt[:80])

    logger.info(
        "PROMPT_GENERATOR | category=%s | count=%d | generated=%d",
        category, count, len(prompts),
    )
    return prompts
