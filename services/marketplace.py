"""
services/marketplace.py

Определяет маркетплейс (WB / OZON) только по артикулу.

Уровни:
    1. Кэш БД       — мгновенно, 100%
    2. Эвристика    — <1 мс, буквы/дефисы → однозначно OZON
    3. WB public API — 200–500 мс, без токена
    Fallback: если не найден на WB → считаем OZON (с низкой уверенностью)

Исправленные баги:
    - Невидимые символы и пробелы внутри артикула чистятся через re.sub
    - 301/302 не считаются "найдено" — проверяем JSON-ответ
    - brand — строка, не объект; color — из colors[0].name
    - Различаем 429/5xx (API недоступен) от 404 (не найден)
    - Неуверенные результаты (fallback OZON) НЕ кэшируются
    - Один глобальный aiohttp.ClientSession передаётся снаружи
    - Таймаут: connect=2s, total=4s — не блокируем бота
"""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

from database import get_marketplace_cache, save_marketplace_cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Паттерны
# ---------------------------------------------------------------------------

# WB nmID: строго цифры, 6–12 знаков (реальный диапазон; 13-14 — запас)
_WB_DIGITS = re.compile(r"^\d{6,14}$")
# Однозначный OZON: содержит латинские буквы, дефис или подчёркивание
_OZON_ALPHA = re.compile(r"[A-Za-z\-_]")

# Публичный WB API карточек (без токена, используется фронтом wildberries.ru)
_WB_CARD_API = "https://card.wb.ru/cards/v2/detail"

_WB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.wildberries.ru",
}

# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

async def _check_wb_card_api(
    session: aiohttp.ClientSession,
    article: str,
) -> dict[str, Any]:
    """
    Проверяет существование товара через публичный API WB.

    Returns:
        {"found": True,  "meta": {"name": ..., "brand": ..., "color": ...}}
        {"found": False, "meta": {}}
        {"error": "rate_limited" | "unavailable"}   ← API недоступен, не "не найден"
    """
    timeout = aiohttp.ClientTimeout(connect=2, total=4)
    try:
        async with session.get(
            _WB_CARD_API,
            params={"appType": "1", "curr": "rub", "nm": article},
            headers=_WB_HEADERS,
            timeout=timeout,
        ) as resp:
            if resp.status == 429:
                logger.warning("WB card API: rate limited (429) for article %s", article)
                return {"error": "rate_limited"}
            if resp.status >= 500:
                logger.warning("WB card API: server error %s for article %s", resp.status, article)
                return {"error": "unavailable"}
            if resp.status != 200:
                # 404 и прочее — товар не найден
                return {"found": False, "meta": {}}

            data = await resp.json(content_type=None)
            products = data.get("data", {}).get("products", [])

            if not products:
                return {"found": False, "meta": {}}

            p = products[0]

            # brand — строка (не объект)
            brand = p.get("brand") or ""
            # color — список объектов [{name: ...}]
            colors = p.get("colors") or []
            color = colors[0].get("name", "") if colors else ""

            return {
                "found": True,
                "meta": {
                    "name":  p.get("name", ""),
                    "brand": brand,
                    "color": color,
                },
            }

    except TimeoutError:
        logger.warning("WB card API: timeout for article %s", article)
        return {"error": "unavailable"}
    except aiohttp.ClientError as e:
        logger.warning("WB card API: network error for article %s: %s", article, e)
        return {"error": "unavailable"}


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

async def resolve_marketplace(
    article: str,
    user_id: int,
    session: aiohttp.ClientSession,
) -> dict[str, Any]:
    """
    Определяет маркетплейс по артикулу.

    Returns одно из:
        {"marketplace": "WB",   "confidence": 1.0, "method": "...", "meta": {...}}
        {"marketplace": "OZON", "confidence": 1.0, "method": "heuristic"}
        {"marketplace": "OZON", "confidence": 0.7, "method": "fallback", "warning": "..."}
        {"error": "invalid_format", "message": "..."}
        {"error": "not_found",      "message": "..."}
        {"error": "api_unavailable","message": "..."}
    """

    # --- Нормализация ---
    # Убираем все виды пробелов и невидимых символов (включая \u00a0, \u200b и т.д.)
    article = re.sub(r"\s+", "", article.strip())
    # Убираем BOM и невидимые Unicode-символы
    article = re.sub(r"[\u200b-\u200f\ufeff]", "", article)

    if not article:
        return {
            "error": "invalid_format",
            "message": "Артикул не может быть пустым.",
        }

    # --- Уровень 1: кэш БД ---
    cached = await get_marketplace_cache(user_id, article)
    if cached:
        logger.debug("Marketplace cache hit: %s → %s", article, cached)
        return {"marketplace": cached, "confidence": 1.0, "method": "cache", "meta": {}}

    # --- Уровень 2: эвристика ---
    # Содержит буквы, дефис или подчёркивание → однозначно OZON offer_id
    if _OZON_ALPHA.search(article):
        # Не кэшируем: без токена OZON не можем подтвердить существование
        return {
            "marketplace": "OZON",
            "confidence": 1.0,
            "method": "heuristic",
            "meta": {},
        }

    # Невалидный формат для числовых (не цифры или вне диапазона)
    if not _WB_DIGITS.match(article):
        return {
            "error": "invalid_format",
            "message": (
                "Неверный формат артикула.\n"
                "WB: 6–14 цифр. OZON: буквенно-цифровой код."
            ),
        }

    # --- Уровень 3: публичный WB API ---
    # Чистые цифры попадают сюда ВСЕГДА — нет раннего return для WB
    wb = await _check_wb_card_api(session, article)

    if "error" in wb:
        if wb["error"] in ("rate_limited", "unavailable"):
            return {
                "error": "api_unavailable",
                "message": (
                    "Сервис WB временно недоступен. "
                    "Попробуйте через несколько секунд."
                ),
            }

    if wb.get("found"):
        # Подтверждено → кэшируем
        await save_marketplace_cache(user_id, article, "WB")
        return {
            "marketplace": "WB",
            "confidence": 1.0,
            "method": "wb_public_api",
            "meta": wb["meta"],
        }

    # Fallback: числовой артикул не найден на WB → предполагаем OZON.
    # НЕ кэшируем — уверенность 0.7, ошибка всплывёт на этапе генерации.
    return {
        "marketplace": "OZON",
        "confidence": 0.7,
        "method": "fallback",
        "meta": {},
        "warning": (
            "Товар не найден на WB. Возможно, артикул принадлежит OZON "
            "или снят с продажи."
        ),
    }
