"""
services/i2i_generator.py

Генерация эталона через Image-to-Image API (Kie.ai).

Flow:
  1. POST /api/v1/jobs/createTask — создание задачи
  2. GET  /api/v1/jobs/recordInfo?taskId=... — polling статуса
  3. Возврат URL готового изображения
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# I2I модель для генерации эталона
I2I_MODEL = "gpt-image/1.5-image-to-image"

# Максимальное количество попыток polling и интервал
MAX_POLL_ATTEMPTS = 30
POLL_INTERVAL = 3  # секунды


async def create_i2i_task(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    image_urls: list[str],
    prompt: str,
    aspect_ratio: str = "1:1",
    quality: str = "medium",
) -> str | None:
    """
    Создаёт задачу генерации изображения.
    Возвращает task_id или None при ошибке.
    """
    payload = {
        "model": I2I_MODEL,
        "input": {
            "input_urls": image_urls,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "quality": quality,
        },
    }

    url = f"{api_base}/api/v1/jobs/createTask"
    logger.info("I2I CREATE TASK | model=%s | images=%d | url=%s", I2I_MODEL, len(image_urls), url)

    try:
        async with session.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
            logger.info("I2I CREATE RESPONSE | code=%s | data=%s", data.get("code"), data.get("data"))

            if data.get("code") == 200:
                return data["data"]["taskId"]
            else:
                logger.error("I2I create failed: %s", data)
                return None

    except Exception as e:
        logger.error("I2I create request failed: %s", e)
        return None


async def poll_task_status(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    task_id: str,
) -> dict[str, Any] | None:
    """
    Опрос статуса задачи через GET /api/v1/jobs/recordInfo.
    Возвращает data объекта задачи или None.
    """
    url = f"{api_base}/api/v1/jobs/recordInfo"
    params = {"taskId": task_id}

    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        try:
            async with session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                result = data.get("data", {})
                status = result.get("status", "unknown")

                logger.info(
                    "I2I POLL #%d | taskId=%s | status=%s | progress=%s",
                    attempt, task_id, status, result.get("progress"),
                )

                if status == "completed":
                    return result
                elif status in ("failed", "error"):
                    logger.error("I2I task failed: %s", result)
                    return None

                # Still processing
                await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.warning("I2I poll #%d failed: %s", attempt, e)
            await asyncio.sleep(POLL_INTERVAL)

    logger.error("I2I poll timeout after %d attempts", MAX_POLL_ATTEMPTS)
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
    Возвращает URL готового изображения или None.
    """
    task_id = await create_i2i_task(
        session=session,
        api_base=api_base,
        api_key=api_key,
        image_urls=image_urls,
        prompt=prompt,
    )

    if not task_id:
        return None

    result = await poll_task_status(
        session=session,
        api_base=api_base,
        api_key=api_key,
        task_id=task_id,
    )

    if not result:
        return None

    # Kie.ai возвращает imageUrl в result
    image_url = result.get("result", {}).get("imageUrl")
    if not image_url:
        # Альтернативные поля
        image_url = result.get("imageUrl") or result.get("image_url")

    logger.info("I2I RESULT | task_id=%s | image_url=%s", task_id, image_url)
    return image_url
