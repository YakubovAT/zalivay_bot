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
        "Fashion lifestyle editorial photograph. "
        "A stylish young woman wearing {description}, paired with {item_color} {bottom_item}. "
        "Setting: {location}. "
        "Confident, natural relaxed pose. "
        "Soft diffused natural light, warm tones, shallow depth of field with blurred bokeh background. "
        "Sharp focus on the top garment — fabric texture, fit, and drape clearly visible. "
        "Photorealistic commercial photography, high resolution, no distortion."
    ),
    "photo_bottom": (
        "Fashion lifestyle editorial photograph. "
        "A stylish young woman wearing {description}, paired with {item_color} {top_item}. "
        "Setting: {location}. "
        "Natural relaxed stance, elongated silhouette. "
        "Soft diffused natural light, warm tones, shallow depth of field with blurred bokeh background. "
        "Sharp focus on the bottom garment — fabric texture, fit, and leg line clearly visible. "
        "Photorealistic commercial photography, high resolution, no distortion."
    ),
    "photo_shoes": (
        "Fashion lifestyle editorial photograph. "
        "A stylish young woman wearing {description}. "
        "Outfit: {neutral_outfit}. "
        "Setting: {location}. "
        "Natural pose with footwear prominent in frame, slight low-angle view to feature the shoes. "
        "Soft side natural lighting, shallow depth of field. "
        "Sharp focus on the footwear — material texture, construction, and sole detail clearly visible. "
        "Photorealistic commercial photography, high resolution, no distortion."
    ),
    "photo_hat": (
        "Fashion lifestyle editorial photograph. "
        "A stylish young woman wearing {description}. "
        "Outfit: {neutral_outfit}. "
        "Setting: {location}. "
        "Natural confident pose, upper body and headwear in clean frame. "
        "Soft diffused natural light, warm tones. "
        "Sharp focus on the headwear — fabric, structure, and brim detail clearly visible. "
        "Photorealistic commercial photography, high resolution, no distortion."
    ),
    "video_top": (
        "Smooth cinematic fashion lifestyle video. "
        "A stylish young woman wearing {description}, paired with {item_color} {item}. "
        "Location: {location}. "
        "The model is {motion}. "
        "Slow gliding camera captures the fabric drape and flow of the garment. "
        "Warm soft natural lighting, cinematic color grading, shallow depth of field. "
        "The top garment stays in sharp focus throughout the motion. "
        "Professional e-commerce fashion footage, no camera shake, fluid movement."
    ),
    "video_bottom": (
        "Smooth cinematic fashion lifestyle video. "
        "A stylish young woman wearing {description}, paired with {item_color} {item}. "
        "Location: {location}. "
        "The model is {motion}. "
        "Slow tracking camera at mid-height captures the drape and movement of the bottom garment. "
        "Warm soft natural lighting, cinematic color grading, shallow depth of field. "
        "The garment stays in sharp focus throughout the motion. "
        "Professional e-commerce fashion footage, no camera shake, fluid movement."
    ),
    "video_shoes": (
        "Smooth cinematic fashion lifestyle video. "
        "A stylish young woman wearing {description}, styled with a {outfit}. "
        "Location: {location}. "
        "The model is {motion}. "
        "Camera alternates between full-body and waist-down close-up angles, highlighting the footwear in motion. "
        "Warm directional natural lighting, cinematic color grading. "
        "Material texture and movement of the shoes clearly visible throughout. "
        "Professional e-commerce fashion footage, no camera shake, fluid movement."
    ),
    "video_hat": (
        "Smooth cinematic fashion lifestyle video. "
        "A stylish young woman wearing {description}, styled with a {outfit}. "
        "Location: {location}. "
        "The model is {motion}. "
        "Camera frames from shoulders up, with the headwear prominently featured. "
        "Soft golden-hour or studio lighting, cinematic color grading. "
        "Fabric texture, structure, and movement of the headwear clearly visible. "
        "Professional e-commerce fashion footage, no camera shake, fluid movement."
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
        "simple all-black monochrome look",
        "soft cream knit and wide-leg ivory trousers",
        "light denim jacket over a white linen shirt and straight trousers",
        "camel turtleneck and tailored sand-colored trousers",
        "pastel lavender blouse and white straight-leg pants",
    ],
}

# Списки пар: [(value, value2), ...]
_FALLBACK_PAIRS: dict[str, list[tuple[str, str]]] = {
    "video_locations": [
        ("a sunny city street", "walking confidently forward, hair gently moving"),
        ("a modern coffee shop", "sitting gracefully and glancing up at the camera"),
        ("a lush green park", "strolling leisurely, light breeze in the air"),
        ("a bright minimalist studio", "rotating slowly with arms slightly extended"),
        ("a seaside promenade", "walking along the waterfront with a relaxed stride"),
        ("a stylish rooftop terrace with city skyline", "standing and gazing into the distance"),
        ("a cozy warmly lit café interior", "reaching for a cup and smiling slightly"),
        ("a vibrant outdoor flower market", "walking through the stalls, glancing at flowers"),
        ("a clean white studio with soft fill light", "posing and turning to show all angles"),
        ("an urban pedestrian bridge", "walking toward the camera with a confident gait"),
        ("a forest path with autumn foliage", "walking through softly falling leaves"),
        ("an elegant marble hotel lobby", "walking through the entrance with a graceful stride"),
        ("a sunlit courtyard with stone architecture", "stepping forward and pausing naturally"),
        ("a glass-front boutique street", "walking past storefronts, window reflection visible"),
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

async def get_template(key: str, fallback: str | None = None) -> str:
    """Возвращает шаблон по ключу.
    Приоритет: БД → аргумент fallback → _FALLBACK_TEMPLATES → пустая строка.
    """
    await _ensure()
    result = _cache.get("templates", {}).get(key)
    if result:
        return result
    logger.warning("prompt_store: шаблон '%s' не найден в БД, используем fallback", key)
    if fallback is not None:
        return fallback
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
