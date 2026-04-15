"""
services/prompt_generator_video.py

Генератор lifestyle-промптов для I2V (видео) на основе категории товара.

Данные (шаблоны, локации с движением, одежда) хранятся в БД и читаются
через services.prompt_store с TTL-кэшем 60 сек.
При недоступности БД — автоматический fallback на значения из prompt_store.
"""

from __future__ import annotations

import random
import logging

logger = logging.getLogger(__name__)


async def generate_video_prompts(
    description: str,
    category: str,
    count: int,
) -> list[str]:
    """
    Генерирует список уникальных EN-промптов для lifestyle-видео.

    Args:
        description: product_description из article_references (EN)
        category:    верх / низ / обувь / головной убор
        count:       количество видео

    Returns:
        Список промптов длиной count.
    """
    from services.prompt_store import get_template, get_pairs, get_list

    locations_pairs  = await get_pairs("video_locations")   # [(location, motion), ...]
    bottom_pairs     = await get_pairs("video_bottom_items") # [(item_name, color), ...]
    top_pairs        = await get_pairs("video_top_items")    # [(item_name, color), ...]
    neutral_outfits  = await get_list("video_neutral_outfits")

    cat = category.lower().strip()

    # Набираем уникальные локации (без повторов пока хватает пула)
    sampled_locations = random.sample(locations_pairs, min(count, len(locations_pairs)))
    while len(sampled_locations) < count:
        sampled_locations += random.sample(
            locations_pairs,
            min(count - len(sampled_locations), len(locations_pairs)),
        )

    prompts: list[str] = []

    for i in range(count):
        location, motion = sampled_locations[i]

        if cat == "верх":
            template = await get_template("video_top")
            item_name, item_color = random.choice(bottom_pairs)
            prompt = template.format(
                description=description,
                item=item_name,
                item_color=item_color,
                location=location,
                motion=motion,
            )

        elif cat == "низ":
            template = await get_template("video_bottom")
            item_name, item_color = random.choice(top_pairs)
            prompt = template.format(
                description=description,
                item=item_name,
                item_color=item_color,
                location=location,
                motion=motion,
            )

        elif cat == "обувь":
            template = await get_template("video_shoes")
            prompt = template.format(
                description=description,
                outfit=random.choice(neutral_outfits),
                location=location,
                motion=motion,
            )

        elif cat == "головной убор":
            template = await get_template("video_hat")
            prompt = template.format(
                description=description,
                outfit=random.choice(neutral_outfits),
                location=location,
                motion=motion,
            )

        else:
            logger.warning("generate_video_prompts: неизвестная категория %r, используем video_shoes", cat)
            template = await get_template("video_shoes")
            prompt = template.format(
                description=description,
                outfit=random.choice(neutral_outfits),
                location=location,
                motion=motion,
            )

        prompts.append(prompt)
        logger.debug("VIDEO PROMPT #%d | category=%s | %s", i + 1, cat, prompt[:80])

    logger.info(
        "VIDEO_PROMPT_GENERATOR | category=%s | count=%d | generated=%d",
        cat, count, len(prompts),
    )
    return prompts
