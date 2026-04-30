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
from pathlib import Path
from typing import Any

import aiohttp
from PIL import Image

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
        "Создай изображение разделённое на 4 равных части в каждом своё изображение:\n\n"
        f"Верхний левый угол: {prompts[0]}\n"
        f"Верхний правый угол: {prompts[1]}\n"
        f"Нижний левый угол: {prompts[2]}\n"
        f"Нижний правый угол: {prompts[3]}\n\n"
        "Все 4 изображения — ОДИН И ТОТ ЖЕ ТОВАР из разных углов/стилей. Аспект 3:4, разрешение 1K PNG."
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


async def download_image_from_url(
    session: aiohttp.ClientSession,
    url: str,
    output_path: str,
) -> bool:
    """Скачивает изображение по URL и сохраняет в файл."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(await resp.read())
                logger.info("Downloaded image | url=%s | path=%s", url, output_path)
                return True
            else:
                logger.error("Download failed | url=%s | status=%d", url, resp.status)
                return False
    except Exception as e:
        logger.error("Download error | url=%s | error=%s", url, e)
        return False


def split_image_2x2(
    image_path: str,
    output_dir: str,
    article_code: str,
    task_id: str,
) -> list[str] | None:
    """
    Разрезает PNG (3:4) на 4 равные части (2x2 сетка).

    Args:
        image_path: путь к исходному PNG файлу
        output_dir: папка для сохранения 4 частей
        article_code: артикул товара (для названия файлов)
        task_id: ID задачи (для уникальности)

    Returns:
        Список из 4 путей к файлам или None при ошибке.
    """
    try:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        img = Image.open(image_path)
        logger.info("Split image | path=%s | size=%s", image_path, img.size)

        width, height = img.size

        half_width = width // 2
        half_height = height // 2

        coords = [
            (0, 0, half_width, half_height),              # top-left
            (half_width, 0, width, half_height),          # top-right
            (0, half_height, half_width, height),         # bottom-left
            (half_width, half_height, width, height),     # bottom-right
        ]

        output_paths = []
        for i, (left, top, right, bottom) in enumerate(coords, 1):
            part = img.crop((left, top, right, bottom))
            part_path = f"{output_dir}/photo_{article_code}_{task_id}_{i}.png"
            part.save(part_path, "PNG")
            output_paths.append(part_path)
            logger.info("Split part #%d | path=%s | size=%s", i, part_path, part.size)

        logger.info("Image split successfully | parts=%d", len(output_paths))
        return output_paths

    except Exception as e:
        logger.error("Split image error | path=%s | error=%s", image_path, e)
        return None
