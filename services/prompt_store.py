"""
services/prompt_store.py

Кэшируемый доступ к шаблонам промптов и спискам элементов из БД.
Генераторы промптов никогда не ходят в БД напрямую — только через этот модуль.

Механика:
  - In-memory кэш с TTL (по умолчанию 60 сек).
  - При промахе кэша — запрос к БД.
  - При недоступности БД — fallback на значения из кода (без падения бота).
  - Веб-панель меняет данные в БД → при следующем истечении TTL бот подхватывает изменения.
"""

from __future__ import annotations

import time
import logging

logger = logging.getLogger(__name__)

_TTL: float = 10.0  # секунды (в разработке; перед продом изменить на 30–60)

# Структура кэша:
# {
#   "templates": {"photo_top": "...", ...},
#   "lists":     {"photo_locations": ["...", ...], ...},
#   "pairs":     {"video_locations": [("loc", "motion"), ...], ...},
# }
_cache: dict = {}
_loaded_at: float = 0.0


# ---------------------------------------------------------------------------
# Fallback-значения (используются если БД недоступна)
# Зеркало того что лежит в seed-данных schema.sql
# ---------------------------------------------------------------------------

_FALLBACK_TEMPLATES: dict[str, str] = {
    "photo_top": (
        "Professional lifestyle fashion photograph. "
        "A model wearing {description}, paired with {item_color} {bottom_item}. "
        "Location: {location}. "
        "Natural relaxed pose, high-quality e-commerce photography, "
        "realistic lighting, sharp focus on the clothing."
    ),
    "photo_bottom": (
        "Professional lifestyle fashion photograph. "
        "A model wearing {description}, paired with {item_color} {top_item}. "
        "Location: {location}. "
        "Natural relaxed pose, high-quality e-commerce photography, "
        "realistic lighting, sharp focus on the clothing."
    ),
    "photo_shoes": (
        "Professional lifestyle fashion photograph. "
        "A model wearing {description}. "
        "Outfit: {neutral_outfit}. "
        "Location: {location}. "
        "Natural relaxed pose, high-quality e-commerce photography, "
        "realistic lighting, focus on the footwear."
    ),
    "photo_hat": (
        "Professional lifestyle fashion photograph. "
        "A model wearing {description}. "
        "Outfit: {neutral_outfit}. "
        "Location: {location}. "
        "Natural relaxed pose, high-quality e-commerce photography, "
        "realistic lighting, focus on the headwear."
    ),
    "video_top": (
        "A fashion lifestyle video. A model wearing {description}, "
        "paired with {item_color} {item}. "
        "Location: {location}. "
        "The model is {motion}. "
        "Smooth cinematic camera movement, natural lighting, "
        "sharp focus on the clothing, professional e-commerce fashion video."
    ),
    "video_bottom": (
        "A fashion lifestyle video. A model wearing {description}, "
        "paired with {item_color} {item}. "
        "Location: {location}. "
        "The model is {motion}. "
        "Smooth cinematic camera movement, natural lighting, "
        "sharp focus on the clothing, professional e-commerce fashion video."
    ),
    "video_shoes": (
        "A fashion lifestyle video. A model wearing {description}, "
        "styled with a {outfit}. "
        "Location: {location}. "
        "The model is {motion}, with camera focus on the footwear. "
        "Smooth cinematic camera movement, natural lighting, "
        "sharp focus on the shoes, professional e-commerce fashion video."
    ),
    "video_hat": (
        "A fashion lifestyle video. A model wearing {description}, "
        "styled with a {outfit}. "
        "Location: {location}. "
        "The model is {motion}, with camera focus on the headwear. "
        "Smooth cinematic camera movement, natural lighting, "
        "sharp focus on the hat, professional e-commerce fashion video."
    ),
}

_FALLBACK_LISTS: dict[str, list[str]] = {
    "photo_locations": [
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
    ],
    "photo_bottom_items": [
        "jeans", "trousers", "skirt", "shorts",
        "leggings", "palazzo pants", "straight-leg pants", "midi skirt",
    ],
    "photo_top_items": [
        "t-shirt", "shirt", "sweater", "blouse",
        "hoodie", "top", "cardigan", "turtleneck",
    ],
    "photo_neutral_outfits": [
        "white t-shirt and blue jeans",
        "beige sweater and black trousers",
        "black blouse and white skirt",
        "grey hoodie and dark jeans",
        "striped shirt and beige trousers",
    ],
    "photo_colors": [
        "white", "black", "navy blue", "beige", "light grey",
        "dark brown", "olive green", "pastel pink", "cream", "charcoal",
    ],
    "video_neutral_outfits": [
        "neutral beige linen outfit",
        "minimalist white and grey ensemble",
        "simple monochrome look",
    ],
}

# Списки пар: [(value, value2), ...]
_FALLBACK_PAIRS: dict[str, list[tuple[str, str]]] = {
    "video_locations": [
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
    ],
    # value = название предмета одежды, value2 = цвет (см. комментарии в schema.sql)
    "video_bottom_items": [
        ("white jeans", "light"),
        ("black slim trousers", "dark"),
        ("beige linen pants", "neutral"),
        ("light blue denim skirt", "blue"),
        ("khaki wide-leg pants", "khaki"),
    ],
    "video_top_items": [
        ("white fitted t-shirt", "white"),
        ("light beige blouse", "beige"),
        ("soft grey knit", "grey"),
        ("pastel pink turtleneck", "pink"),
        ("navy blue shirt", "navy"),
    ],
}


# ---------------------------------------------------------------------------
# Внутренняя загрузка
# ---------------------------------------------------------------------------

async def _load() -> None:
    """Загружает все данные из БД в _cache."""
    global _cache, _loaded_at
    from database.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        template_rows = await conn.fetch(
            "SELECT key, template FROM prompt_templates"
        )
        item_rows = await conn.fetch(
            "SELECT list_key, value, value2 FROM prompt_list_items "
            "WHERE is_active = TRUE ORDER BY list_key, sort_order, id"
        )

    templates: dict[str, str] = {r["key"]: r["template"] for r in template_rows}

    lists: dict[str, list[str]] = {}
    pairs: dict[str, list[tuple[str, str]]] = {}
    for row in item_rows:
        lk = row["list_key"]
        lists.setdefault(lk, []).append(row["value"])
        pairs.setdefault(lk, []).append((row["value"], row["value2"]))

    _cache = {"templates": templates, "lists": lists, "pairs": pairs}
    _loaded_at = time.monotonic()
    logger.debug(
        "prompt_store: cache refreshed — %d templates, %d list keys",
        len(templates), len(lists),
    )


async def _ensure() -> None:
    """Обновляет кэш если TTL истёк или кэш пуст. При ошибке — тихо логирует."""
    if time.monotonic() - _loaded_at > _TTL or not _cache:
        try:
            await _load()
        except Exception as exc:
            logger.error("prompt_store: не удалось загрузить из БД, используем fallback: %s", exc)


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

async def get_template(key: str) -> str:
    """Возвращает шаблон промпта по ключу. При отсутствии — fallback из кода."""
    await _ensure()
    result = _cache.get("templates", {}).get(key)
    if result:
        return result
    logger.warning("prompt_store: шаблон '%s' не найден в БД, используем fallback", key)
    return _FALLBACK_TEMPLATES.get(key, "")


async def get_list(list_key: str) -> list[str]:
    """Возвращает список строк (только value) для list_key. При отсутствии — fallback."""
    await _ensure()
    result = _cache.get("lists", {}).get(list_key)
    if result:
        return result
    logger.warning("prompt_store: список '%s' не найден в БД, используем fallback", list_key)
    return _FALLBACK_LISTS.get(list_key, [])


async def get_pairs(list_key: str) -> list[tuple[str, str]]:
    """Возвращает список пар (value, value2) для list_key. При отсутствии — fallback."""
    await _ensure()
    result = _cache.get("pairs", {}).get(list_key)
    if result:
        return result
    logger.warning("prompt_store: пары '%s' не найдены в БД, используем fallback", list_key)
    return _FALLBACK_PAIRS.get(list_key, [])


async def invalidate() -> None:
    """Принудительно сбрасывает кэш. Можно вызвать из admin-панели после сохранения."""
    global _loaded_at
    _loaded_at = 0.0
    logger.info("prompt_store: кэш инвалидирован")
