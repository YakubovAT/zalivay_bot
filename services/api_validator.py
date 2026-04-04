"""
services/api_validator.py

Валидация API-ключей WB и OZON.

WB Seller API:
    Ключ передаётся в заголовке Authorization.
    Проверяем через минимальный запрос к content-api.wildberries.ru.

OZON Seller API:
    Требует два реквизита: Client-Id + Api-Key.
    Проверяем через минимальный запрос к api-seller.ozon.ru.

Возвращаемые значения:
    {"valid": True}
    {"valid": False, "reason": "invalid_key" | "no_rights" | "unavailable" | "network_error"}

Использует глобальный aiohttp.ClientSession, переданный снаружи.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

_WB_VALIDATE_URL = "https://content-api.wildberries.ru/content/v2/get/cards/list"
_WB_VALIDATE_PAYLOAD = {
    "settings": {
        "cursor": {"limit": 1},
        "filter": {"withPhoto": -1},
    }
}

_OZON_VALIDATE_URL = "https://api-seller.ozon.ru/v3/product/list"
_OZON_VALIDATE_PAYLOAD = {
    "filter": {},
    "last_id": "",
    "limit": 1,
}

_TIMEOUT = aiohttp.ClientTimeout(connect=3, total=8)


# ---------------------------------------------------------------------------
# WB
# ---------------------------------------------------------------------------

async def validate_wb_key(
    api_key: str,
    session: aiohttp.ClientSession,
) -> dict[str, Any]:
    """
    Проверяет валидность WB Seller API ключа.

    Args:
        api_key: токен из личного кабинета WB → Настройки → Доступ к API.
        session: глобальный aiohttp.ClientSession.

    Returns:
        {"valid": True}
        {"valid": False, "reason": "invalid_key"}    — 401
        {"valid": False, "reason": "no_rights"}      — 403 (ключ есть, прав нет)
        {"valid": False, "reason": "unavailable"}    — 5xx / timeout
        {"valid": False, "reason": "network_error"}  — сетевая ошибка
    """
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with session.post(
            _WB_VALIDATE_URL,
            json=_WB_VALIDATE_PAYLOAD,
            headers=headers,
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status == 200:
                return {"valid": True}
            if resp.status == 401:
                logger.info("WB key validation: 401 Unauthorized")
                return {"valid": False, "reason": "invalid_key"}
            if resp.status == 403:
                logger.info("WB key validation: 403 Forbidden (no rights)")
                return {"valid": False, "reason": "no_rights"}
            if resp.status >= 500:
                logger.warning("WB key validation: server error %s", resp.status)
                return {"valid": False, "reason": "unavailable"}

            # Неожиданный статус — считаем ключ невалидным
            logger.warning("WB key validation: unexpected status %s", resp.status)
            return {"valid": False, "reason": "invalid_key"}

    except TimeoutError:
        logger.warning("WB key validation: timeout")
        return {"valid": False, "reason": "unavailable"}
    except aiohttp.ClientError as e:
        logger.warning("WB key validation: network error: %s", e)
        return {"valid": False, "reason": "network_error"}


# ---------------------------------------------------------------------------
# OZON
# ---------------------------------------------------------------------------

async def validate_ozon_keys(
    client_id: str,
    api_key: str,
    session: aiohttp.ClientSession,
) -> dict[str, Any]:
    """
    Проверяет валидность пары ключей OZON Seller API.

    Args:
        client_id: числовой ID продавца (Client-Id).
        api_key:   токен из личного кабинета OZON → API → Ключи.
        session:   глобальный aiohttp.ClientSession.

    Returns:
        {"valid": True}
        {"valid": False, "reason": "invalid_key"}    — 401
        {"valid": False, "reason": "no_rights"}      — 403
        {"valid": False, "reason": "unavailable"}    — 5xx / timeout
        {"valid": False, "reason": "network_error"}  — сетевая ошибка
    """
    headers = {
        "Client-Id": str(client_id),
        "Api-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with session.post(
            _OZON_VALIDATE_URL,
            json=_OZON_VALIDATE_PAYLOAD,
            headers=headers,
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status == 200:
                return {"valid": True}
            if resp.status == 401:
                logger.info("OZON key validation: 401 Unauthorized")
                return {"valid": False, "reason": "invalid_key"}
            if resp.status == 403:
                logger.info("OZON key validation: 403 Forbidden (no rights)")
                return {"valid": False, "reason": "no_rights"}
            if resp.status >= 500:
                logger.warning("OZON key validation: server error %s", resp.status)
                return {"valid": False, "reason": "unavailable"}

            logger.warning("OZON key validation: unexpected status %s", resp.status)
            return {"valid": False, "reason": "invalid_key"}

    except TimeoutError:
        logger.warning("OZON key validation: timeout")
        return {"valid": False, "reason": "unavailable"}
    except aiohttp.ClientError as e:
        logger.warning("OZON key validation: network error: %s", e)
        return {"valid": False, "reason": "network_error"}


# ---------------------------------------------------------------------------
# Человекочитаемые сообщения об ошибках
# ---------------------------------------------------------------------------

_WB_ERROR_MESSAGES: dict[str, str] = {
    "invalid_key": (
        "❌ Ключ WB недействителен.\n"
        "Проверьте, что скопировали токен полностью из\n"
        "<b>Личный кабинет WB → Настройки → Доступ к API</b>."
    ),
    "no_rights": (
        "⚠️ Ключ WB действителен, но у него нет прав на работу с контентом.\n"
        "Убедитесь, что при создании токена выбрали раздел <b>«Контент»</b>."
    ),
    "unavailable": (
        "⏳ Сервис WB временно недоступен. Попробуйте позже."
    ),
    "network_error": (
        "🔌 Не удалось подключиться к WB. Проверьте соединение и попробуйте снова."
    ),
}

_OZON_ERROR_MESSAGES: dict[str, str] = {
    "invalid_key": (
        "❌ Ключи OZON недействительны.\n"
        "Проверьте <b>Client-Id</b> и <b>Api-Key</b> из\n"
        "<b>Личный кабинет OZON → Настройки → API → Ключи</b>."
    ),
    "no_rights": (
        "⚠️ Ключи OZON действительны, но прав на товары нет.\n"
        "Убедитесь, что токен имеет доступ к разделу <b>«Товары»</b>."
    ),
    "unavailable": (
        "⏳ Сервис OZON временно недоступен. Попробуйте позже."
    ),
    "network_error": (
        "🔌 Не удалось подключиться к OZON. Проверьте соединение и попробуйте снова."
    ),
}


def wb_error_message(reason: str) -> str:
    return _WB_ERROR_MESSAGES.get(reason, "❌ Неизвестная ошибка при проверке ключа WB.")


def ozon_error_message(reason: str) -> str:
    return _OZON_ERROR_MESSAGES.get(reason, "❌ Неизвестная ошибка при проверке ключей OZON.")
