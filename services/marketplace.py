"""
services/marketplace.py

Определяет маркетплейс (WB / OZON) по артикулу и возвращает мета-данные товара.

Уровни:
    1. Кэш БД    — мгновенно, 100%
    2. Эвристика — <1 мс, буквы/дефисы → однозначно OZON
    3. wb_parser — прямой доступ к CDN корзины WB (basket-XX.wbbasket.ru),
                   возвращает name, brand, colors, material, description, images
    Fallback: числовой артикул не найден на WB → предполагаем OZON (confidence=0.7)
"""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

from database import get_marketplace_cache, save_marketplace_cache
from wb_parser import get_product_info

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Паттерны
# ---------------------------------------------------------------------------

# WB nmID: строго цифры, 6–12 знаков (реальный диапазон; 13-14 — запас)
_WB_DIGITS = re.compile(r"^\d{6,14}$")
# Однозначный OZON: содержит латинские буквы, дефис или подчёркивание
_OZON_ALPHA = re.compile(r"[A-Za-z\-_]")


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

async def resolve_marketplace(
    article: str,
    user_id: int,
    session: aiohttp.ClientSession,
) -> dict[str, Any]:
    """
    Определяет маркетплейс по артикулу и возвращает мета-данные товара.

    meta для WB содержит: name, brand, color, material, description, images
    meta для OZON: {} (данные получаются на этапе генерации через OZON API)

    Returns одно из:
        {"marketplace": "WB",   "confidence": 1.0, "method": "wb_parser"|"cache", "meta": {...}}
        {"marketplace": "OZON", "confidence": 1.0, "method": "heuristic", "meta": {}}
        {"marketplace": "OZON", "confidence": 0.7, "method": "fallback",  "meta": {}, "warning": "..."}
        {"error": "invalid_format", "message": "..."}
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

    # --- Уровень 3: wb_parser (CDN корзины WB) ---
    try:
        info = await get_product_info(article)
    except Exception as e:
        logger.warning("wb_parser error for article %s: %s", article, e)
        info = {}

    if info:
        color = info["colors"][0] if info.get("colors") else ""
        await save_marketplace_cache(user_id, article, "WB")
        return {
            "marketplace": "WB",
            "confidence": 1.0,
            "method": "wb_parser",
            "meta": {
                "name":        info.get("name", ""),
                "brand":       info.get("brand", ""),
                "color":       color,
                "material":    info.get("material", ""),
                "description": info.get("description", ""),
                "images":      info.get("images", []),
            },
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
