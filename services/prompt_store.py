"""
services/prompt_store.py

Кэшируемый доступ к шаблонам промптов и спискам элементов из БД.
Создатели промптов никогда не ходят в БД напрямую — только через этот модуль.

Механика:
  - In-memory кэш с TTL (по умолчанию 60 сек).
  - При промахе кэша — запрос к БД.
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
# Внутренняя загрузка
# ---------------------------------------------------------------------------

async def _load() -> None:
    """Загружает все данные из БД в _cache."""
    global _cache, _loaded_at
    from database.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        template_rows = await conn.fetch(
            "SELECT key, template, banner FROM prompt_templates"
        )
        item_rows = await conn.fetch(
            "SELECT list_key, value, value2 FROM prompt_list_items "
            "WHERE is_active = TRUE ORDER BY list_key, sort_order, id"
        )

    templates: dict[str, str] = {r["key"]: r["template"] for r in template_rows}
    banners:   dict[str, str] = {r["key"]: r["banner"]   for r in template_rows if r["banner"]}

    lists: dict[str, list[str]] = {}
    pairs: dict[str, list[tuple[str, str]]] = {}
    for row in item_rows:
        lk = row["list_key"]
        lists.setdefault(lk, []).append(row["value"])
        pairs.setdefault(lk, []).append((row["value"], row["value2"]))

    _cache = {"templates": templates, "lists": lists, "pairs": pairs, "banners": banners}
    _loaded_at = time.monotonic()
    logger.debug(
        "prompt_store: cache refreshed — %d templates, %d list keys",
        len(templates), len(lists),
    )


async def _ensure() -> None:
    """Обновляет кэш если TTL истёк или кэш пуст. При ошибке — логирует."""
    if time.monotonic() - _loaded_at > _TTL or not _cache:
        try:
            await _load()
        except Exception as exc:
            logger.error("prompt_store: не удалось загрузить из БД: %s", exc)


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

async def get_template(key: str, fallback: str | None = None) -> str:
    """Возвращает шаблон по ключу. Приоритет: БД → fallback → пустая строка."""
    await _ensure()
    result = _cache.get("templates", {}).get(key)
    if result:
        return result
    if fallback is not None:
        return fallback
    logger.error("prompt_store: шаблон '%s' не найден в БД", key)
    return ""


async def get_list(list_key: str) -> list[str]:
    """Возвращает список строк (только value) для list_key из БД."""
    await _ensure()
    result = _cache.get("lists", {}).get(list_key)
    if result:
        return result
    logger.error("prompt_store: список '%s' не найден в БД", list_key)
    return []


async def get_pairs(list_key: str) -> list[tuple[str, str]]:
    """Возвращает список пар (value, value2) для list_key из БД."""
    await _ensure()
    result = _cache.get("pairs", {}).get(list_key)
    if result:
        return result
    logger.error("prompt_store: пары '%s' не найдены в БД", list_key)
    return []


async def get_banner(key: str) -> str:
    """Возвращает имя файла баннера для шаблона (без пути assets/).
    По умолчанию — 'banner_default.png' если в БД не задан.
    """
    await _ensure()
    return _cache.get("banners", {}).get(key) or "banner_default.png"


async def invalidate() -> None:
    """Принудительно сбрасывает кэш. Можно вызвать из admin-панели после сохранения."""
    global _loaded_at
    _loaded_at = 0.0
    logger.info("prompt_store: кэш инвалидирован")
