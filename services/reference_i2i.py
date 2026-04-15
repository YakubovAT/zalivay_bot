"""
services/reference_i2i.py

Генерация изображения через Image-to-Image API (Kie.ai).

Flow:
  1. POST /api/v1/jobs/createTask  — создание задачи → taskId
  2. GET  /api/v1/jobs/recordInfo?taskId=... — polling статуса
     - code 249 → задача ещё обрабатывается (waiting/queuing/generating)
     - code 200 + state "success" → готово, URL в resultJson → resultUrls[0]
     - state "fail" → ошибка (failCode / failMsg)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# I2I модель для генерации эталона / lifestyle-фото
I2I_MODEL = "gpt-image/1.5-image-to-image"

# Максимальное количество попыток polling и интервал
MAX_POLL_ATTEMPTS = 60
POLL_INTERVAL     = 5  # секунды

# Состояния задачи на стороне провайдера
_STATES_IN_PROGRESS = {"waiting", "queuing", "generating"}
_STATE_SUCCESS       = "success"
_STATE_FAIL          = "fail"


async def create_i2i_task(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    image_urls: list[str],
    prompt: str,
    aspect_ratio: str = "2:3",
    quality: str = "medium",
) -> str | None:
    """
    Создаёт задачу генерации изображения.
    Возвращает taskId или None при ошибке.

    Поле изображений в теле запроса — 'image_urls' (не 'input_urls').
    """
    payload = {
        "model": I2I_MODEL,
        "input": {
            "input_urls":    image_urls,
            "prompt":        prompt,
            "aspect_ratio":  aspect_ratio,
            "quality":       quality,
        },
    }

    url = f"{api_base}/api/v1/jobs/createTask"
    logger.info(
        "I2I CREATE | model=%s | images=%d | prompt_len=%d",
        I2I_MODEL, len(image_urls), len(prompt),
    )

    try:
        async with session.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
            code = data.get("code")
            logger.info("I2I CREATE RESPONSE | code=%s | data=%s | msg=%s",
                        code, data.get("data"), data.get("msg"))

            if code == 200:
                task_id = data.get("data", {}).get("taskId")
                if task_id:
                    return task_id
                logger.error("I2I create: taskId missing in response: %s", data)
                return None
            else:
                logger.error("I2I create failed | code=%s | msg=%s", code, data.get("msg"))
                return None

    except Exception as e:
        logger.error("I2I create request error: %s", e)
        return None


async def poll_task_status(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    task_id: str,
) -> dict[str, Any] | None:
    """
    Polling статуса задачи через GET /api/v1/jobs/recordInfo?taskId=...

    Kie.ai возвращает:
      - code 249 → задача ещё в очереди / генерируется, продолжаем ждать
      - code 200 + data.state == "success" → готово
      - code 200 + data.state == "fail"    → ошибка

    Возвращает dict data при успехе или None при ошибке / таймауте.
    """
    url    = f"{api_base}/api/v1/jobs/recordInfo"
    params = {"taskId": task_id}

    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        try:
            async with session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data  = await resp.json()
                code  = data.get("code")
                inner = data.get("data", {})
                state = inner.get("state") or "unknown"

                logger.info(
                    "I2I POLL #%d | taskId=%s | code=%s | state=%s",
                    attempt, task_id, code, state,
                )

                # Ещё обрабатывается
                if code == 249 or state in _STATES_IN_PROGRESS:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                # Готово
                if code == 200 and state == _STATE_SUCCESS:
                    return inner

                # Ошибка провайдера
                if state == _STATE_FAIL:
                    logger.error(
                        "I2I task failed | taskId=%s | failCode=%s | failMsg=%s",
                        task_id, inner.get("failCode"), inner.get("failMsg"),
                    )
                    return None

                # Неожиданный ответ — ждём
                logger.warning("I2I POLL unexpected | code=%s state=%s | data=%s", code, state, data)
                await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.warning("I2I poll #%d error: %s", attempt, e)
            await asyncio.sleep(POLL_INTERVAL)

    logger.error("I2I poll timeout | taskId=%s | attempts=%d", task_id, MAX_POLL_ATTEMPTS)
    return None


async def generate_reference_image(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    image_urls: list[str],
    prompt: str,
) -> str | None:
    """
    Полный цикл: создание задачи → polling → возврат URL результата.

    Kie.ai хранит URL в поле resultJson (JSON-строка):
      {"resultUrls": ["https://..."]}

    Возвращает URL первого изображения или None.
    """
    logger.info("I2I GENERATE | images=%d | prompt_len=%d", len(image_urls), len(prompt))

    task_id = await create_i2i_task(
        session=session,
        api_base=api_base,
        api_key=api_key,
        image_urls=image_urls,
        prompt=prompt,
    )
    if not task_id:
        return None

    logger.info("I2I TASK CREATED | taskId=%s", task_id)

    result = await poll_task_status(
        session=session,
        api_base=api_base,
        api_key=api_key,
        task_id=task_id,
    )
    if not result:
        return None

    # resultJson — это JSON-строка вида {"resultUrls": ["https://..."]}
    result_json_str = result.get("resultJson", "")
    try:
        result_data = json.loads(result_json_str)
        urls = result_data.get("resultUrls", [])
        image_url = urls[0] if urls else None
    except (json.JSONDecodeError, IndexError, TypeError):
        logger.error("I2I result parse error | resultJson=%s", result_json_str)
        image_url = None

    logger.info("I2I RESULT | taskId=%s | image_url=%s", task_id, image_url)
    return image_url
