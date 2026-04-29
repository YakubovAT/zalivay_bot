"""
services/reference_i2i_welcome.py

Создание эталона и 4 фото для велком флоу через Image-to-Image API.

Flow:
  1. Создание эталона товара (2x2 сетка на прозрачном фоне)
  2. Генерация 4 фото товара в стилях (разделение 3:4 PNG на 4 части)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

I2I_MODEL = "nano-banana-2"
MAX_POLL_ATTEMPTS = 60
POLL_INTERVAL = 5

_STATES_IN_PROGRESS = {"waiting", "queuing", "generating"}
_STATE_SUCCESS = "success"
_STATE_FAIL = "fail"


async def create_i2i_task(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    image_urls: list[str],
    prompt: str,
    aspect_ratio: str = "9:16",
    resolution: str = "1K",
    output_format: str = "png",
) -> str | None:
    """Создаёт задачу I2I в Kie.ai API."""
    payload = {
        "model": I2I_MODEL,
        "input": {
            "image_input": image_urls,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
        },
    }

    url = f"{api_base}/api/v1/jobs/createTask"
    logger.info("I2I CREATE welcome | model=%s | images=%d | prompt_len=%d",
                I2I_MODEL, len(image_urls), len(prompt))

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
            logger.info("I2I CREATE RESPONSE welcome | code=%s | msg=%s", code, data.get("msg"))

            if code == 200:
                task_id = data.get("data", {}).get("taskId")
                if task_id:
                    return task_id
                logger.error("I2I create welcome: taskId missing")
                return None
            else:
                logger.error("I2I create welcome failed | code=%s | msg=%s", code, data.get("msg"))
                return None

    except Exception as e:
        logger.error("I2I create welcome error: %s", e)
        return None


async def poll_task_status(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    task_id: str,
) -> dict[str, Any] | None:
    """Polling статуса I2I задачи."""
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

                logger.info("I2I POLL welcome #%d | code=%s | state=%s", attempt, code, state)

                if code == 249 or state in _STATES_IN_PROGRESS:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                if code == 200 and state == _STATE_SUCCESS:
                    return inner

                if state == _STATE_FAIL:
                    logger.error("I2I task failed welcome | failCode=%s | failMsg=%s",
                                inner.get("failCode"), inner.get("failMsg"))
                    return None

                logger.warning("I2I POLL unexpected welcome | code=%s state=%s", code, state)
                await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.warning("I2I poll welcome #%d error: %s", attempt, e)
            await asyncio.sleep(POLL_INTERVAL)

    logger.error("I2I poll welcome timeout | taskId=%s", task_id)
    return None


async def generate_reference_image(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    image_urls: list[str],
    prompt: str,
) -> str | None:
    """
    Создаёт эталон товара на прозрачном фоне через I2I.

    Returns:
        URL эталонного изображения или None при ошибке.
    """
    logger.info("I2I GENERATE reference welcome | images=%d | prompt_len=%d",
                len(image_urls), len(prompt))

    task_id = await create_i2i_task(
        session=session,
        api_base=api_base,
        api_key=api_key,
        image_urls=image_urls,
        prompt=prompt,
        aspect_ratio="1:1",
        resolution="1K",
        output_format="png",
    )
    if not task_id:
        return None

    logger.info("I2I TASK CREATED reference welcome | taskId=%s", task_id)

    result = await poll_task_status(
        session=session,
        api_base=api_base,
        api_key=api_key,
        task_id=task_id,
    )
    if not result:
        return None

    result_json_str = result.get("resultJson", "")
    try:
        result_data = json.loads(result_json_str)
        urls = result_data.get("resultUrls", [])
        image_url = urls[0] if urls else None
    except (json.JSONDecodeError, IndexError, TypeError):
        logger.error("I2I result parse error | resultJson=%s", result_json_str)
        image_url = None

    logger.info("I2I RESULT reference welcome | image_url=%s", image_url)
    return image_url


async def generate_4_photos(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    image_urls: list[str],
    prompts: list[str],
) -> str | None:
    """
    Генерирует 4 фото в сетке 2x2 (3:4 аспект).

    Args:
        session: aiohttp сессия
        api_base: Kie.ai API base URL
        api_key: Kie.ai API key
        image_urls: список 3-4 фото товара для I2I
        prompts: список 4 промтов для 4 фото

    Returns:
        URL сгенерированного PNG (3:4, с 4 фото в сетке) или None при ошибке.
    """
    if len(prompts) < 4:
        logger.error("I2I 4photos: требуется 4 промта, получено %d", len(prompts))
        return None

    # Объединяем 4 промта в один
    combined_prompt = (
        "Generate a 2x2 grid of product images (4 equal parts), aspect ratio 3:4, resolution 1K PNG.\n\n"
        f"Top-left: {prompts[0]}\n"
        f"Top-right: {prompts[1]}\n"
        f"Bottom-left: {prompts[2]}\n"
        f"Bottom-right: {prompts[3]}\n\n"
        "All 4 images must be the SAME PRODUCT from different angles/styles."
    )

    logger.info("I2I 4PHOTOS welcome | images=%d | combined_prompt_len=%d",
                len(image_urls), len(combined_prompt))

    task_id = await create_i2i_task(
        session=session,
        api_base=api_base,
        api_key=api_key,
        image_urls=image_urls,
        prompt=combined_prompt,
        aspect_ratio="3:4",
        resolution="1K",
        output_format="png",
    )
    if not task_id:
        return None

    logger.info("I2I 4PHOTOS TASK CREATED welcome | taskId=%s", task_id)

    result = await poll_task_status(
        session=session,
        api_base=api_base,
        api_key=api_key,
        task_id=task_id,
    )
    if not result:
        return None

    result_json_str = result.get("resultJson", "")
    try:
        result_data = json.loads(result_json_str)
        urls = result_data.get("resultUrls", [])
        image_url = urls[0] if urls else None
    except (json.JSONDecodeError, IndexError, TypeError):
        logger.error("I2I 4photos result parse error | resultJson=%s", result_json_str)
        image_url = None

    logger.info("I2I 4PHOTOS RESULT welcome | image_url=%s", image_url)
    return image_url
