"""
services/lifestyle_photo_generator.py

Создание lifestyle-фото для товаров на основе эталона.

Отличия от reference_i2i:
  - Использует тот же Kie.ai I2I API
  - Параметры оптимизированы для lifestyle-фото (aspect_ratio, quality)
  - Полный цикл: create → poll → URL
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# I2I модель для создания lifestyle-фото
LIFESTYLE_I2I_MODEL = "gpt-image/1.5-image-to-image"

# Параметры для lifestyle-фото
LIFESTYLE_ASPECT_RATIO = "2:3"  # Портретный формат
LIFESTYLE_QUALITY = "medium"  # Среднее качество (как в reference_i2i)

# Максимальное количество попыток polling и интервал
MAX_POLL_ATTEMPTS = 60
POLL_INTERVAL = 5  # секунды

# Состояния задачи на стороне провайдера
_STATES_IN_PROGRESS = {"waiting", "queuing", "generating"}
_STATE_SUCCESS = "success"
_STATE_FAIL = "fail"


async def _create_task(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    image_url: str,
    prompt: str,
    aspect_ratio: str = LIFESTYLE_ASPECT_RATIO,
    quality: str = LIFESTYLE_QUALITY,
) -> str | None:
    """Создаёт задачу создания lifestyle-фото."""
    payload = {
        "model": LIFESTYLE_I2I_MODEL,
        "input": {
            "input_urls": [image_url],
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "quality": quality,
        },
    }

    url = f"{api_base}/api/v1/jobs/createTask"
    logger.info(
        "LIFESTYLE_I2I CREATE | model=%s | image=%s | prompt_len=%d",
        LIFESTYLE_I2I_MODEL, image_url, len(prompt),
    )

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
            code = data.get("code")
            logger.info(
                "LIFESTYLE_I2I CREATE RESPONSE | code=%s | data=%s | msg=%s",
                code, data.get("data"), data.get("msg"),
            )

            if code == 200:
                task_id = data.get("data", {}).get("taskId")
                if task_id:
                    return task_id
                logger.error("LIFESTYLE_I2I create: taskId missing in response: %s", data)
                return None
            else:
                logger.error("LIFESTYLE_I2I create failed | code=%s | msg=%s", code, data.get("msg"))
                return None

    except Exception as e:
        logger.error("LIFESTYLE_I2I create request error: %s", e)
        return None


async def _poll_task(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    task_id: str,
) -> dict[str, Any] | None:
    """Polling статуса задачи."""
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
                code = data.get("code")
                inner = data.get("data", {})
                state = inner.get("state") or "unknown"

                logger.info(
                    "LIFESTYLE_I2I POLL #%d | taskId=%s | code=%s | state=%s",
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
                        "LIFESTYLE_I2I task failed | taskId=%s | failCode=%s | failMsg=%s",
                        task_id, inner.get("failCode"), inner.get("failMsg"),
                    )
                    return None

                # Неожиданный ответ — ждём
                logger.warning("LIFESTYLE_I2I POLL unexpected | code=%s state=%s", code, state)
                await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.warning("LIFESTYLE_I2I poll #%d error: %s", attempt, e)
            await asyncio.sleep(POLL_INTERVAL)

    logger.error("LIFESTYLE_I2I poll timeout | taskId=%s | attempts=%d", task_id, MAX_POLL_ATTEMPTS)
    return None


async def generate_lifestyle_photo(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    ref_image_url: str,
    prompt: str,
) -> str | None:
    """
    Полный цикл создания lifestyle-фото.

    Args:
        session: aiohttp.ClientSession
        api_base: URL API (https://api.kie.ai)
        api_key: API ключ
        ref_image_url: URL эталона (входное изображение)
        prompt: промпт на английском

    Returns:
        URL созданного фото или None
    """
    logger.info(
        "LIFESTYLE_PHOTO GENERATE | ref=%s | prompt_len=%d",
        ref_image_url, len(prompt),
    )

    task_id = await _create_task(
        session=session,
        api_base=api_base,
        api_key=api_key,
        image_url=ref_image_url,
        prompt=prompt,
    )
    if not task_id:
        return None

    logger.info("LIFESTYLE_PHOTO TASK CREATED | taskId=%s", task_id)

    result = await _poll_task(
        session=session,
        api_base=api_base,
        api_key=api_key,
        task_id=task_id,
    )
    if not result:
        return None

    # resultJson — JSON-строка вида {"resultUrls": ["https://..."]}
    result_json_str = result.get("resultJson", "")
    try:
        result_data = json.loads(result_json_str)
        urls = result_data.get("resultUrls", [])
        image_url = urls[0] if urls else None
    except (json.JSONDecodeError, IndexError, TypeError):
        logger.error("LIFESTYLE_PHOTO result parse error | resultJson=%s", result_json_str)
        image_url = None

    logger.info("LIFESTYLE_PHOTO RESULT | taskId=%s | image_url=%s", task_id, image_url)
    return image_url
