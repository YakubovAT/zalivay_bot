"""
services/lifestyle_video_generator.py

Генерация lifestyle-видео для товаров на основе эталона.

Использует Kie.ai sora-2-image-to-video API.
Полный цикл: create → poll → URL видео.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# I2V модель
LIFESTYLE_VIDEO_MODEL = "sora-2-image-to-video"

# Параметры видео
LIFESTYLE_VIDEO_ASPECT_RATIO = "portrait"   # portrait | landscape
LIFESTYLE_VIDEO_N_FRAMES = "10"             # 10 | 15
LIFESTYLE_VIDEO_REMOVE_WATERMARK = True
LIFESTYLE_VIDEO_UPLOAD_METHOD = "s3"        # s3 | oss

# Polling (видео генерируется дольше фото)
MAX_POLL_ATTEMPTS = 120
POLL_INTERVAL = 5  # секунды

_STATES_IN_PROGRESS = {"waiting", "queuing", "generating"}
_STATE_SUCCESS = "success"
_STATE_FAIL = "fail"


async def _create_video_task(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    image_url: str,
    prompt: str,
) -> str | None:
    """Создаёт задачу генерации lifestyle-видео через sora-2-image-to-video."""
    payload = {
        "model": LIFESTYLE_VIDEO_MODEL,
        "input": {
            "prompt": prompt,
            "image_urls": [image_url],
            "aspect_ratio": LIFESTYLE_VIDEO_ASPECT_RATIO,
            "n_frames": LIFESTYLE_VIDEO_N_FRAMES,
            "remove_watermark": LIFESTYLE_VIDEO_REMOVE_WATERMARK,
            "upload_method": LIFESTYLE_VIDEO_UPLOAD_METHOD,
        },
    }

    url = f"{api_base}/api/v1/jobs/createTask"
    logger.info(
        "LIFESTYLE_VIDEO CREATE | model=%s | image=%s | prompt_len=%d",
        LIFESTYLE_VIDEO_MODEL, image_url, len(prompt),
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
                "LIFESTYLE_VIDEO CREATE RESPONSE | code=%s | data=%s | msg=%s",
                code, data.get("data"), data.get("msg"),
            )

            if code == 200:
                task_id = data.get("data", {}).get("taskId")
                if task_id:
                    return task_id
                logger.error("LIFESTYLE_VIDEO create: taskId missing in response: %s", data)
                return None
            else:
                logger.error("LIFESTYLE_VIDEO create failed | code=%s | msg=%s", code, data.get("msg"))
                return None

    except Exception as e:
        logger.error("LIFESTYLE_VIDEO create request error: %s", e)
        return None


async def _poll_video_task(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    task_id: str,
) -> dict[str, Any] | None:
    """Polling статуса задачи видео."""
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
                    "LIFESTYLE_VIDEO POLL #%d | taskId=%s | code=%s | state=%s",
                    attempt, task_id, code, state,
                )

                if code == 249 or state in _STATES_IN_PROGRESS:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                if code == 200 and state == _STATE_SUCCESS:
                    return inner

                if state == _STATE_FAIL:
                    logger.error(
                        "LIFESTYLE_VIDEO task failed | taskId=%s | failCode=%s | failMsg=%s",
                        task_id, inner.get("failCode"), inner.get("failMsg"),
                    )
                    return None

                logger.warning("LIFESTYLE_VIDEO POLL unexpected | code=%s state=%s", code, state)
                await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.warning("LIFESTYLE_VIDEO poll #%d error: %s", attempt, e)
            await asyncio.sleep(POLL_INTERVAL)

    logger.error("LIFESTYLE_VIDEO poll timeout | taskId=%s | attempts=%d", task_id, MAX_POLL_ATTEMPTS)
    return None


async def generate_lifestyle_video(
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    ref_image_url: str,
    prompt: str,
) -> str | None:
    """
    Полный цикл генерации lifestyle-видео через sora-2-image-to-video.

    Args:
        session: aiohttp.ClientSession
        api_base: URL API (https://api.kie.ai)
        api_key: API ключ
        ref_image_url: URL эталона (первый кадр видео)
        prompt: промпт на английском (max 10000 символов)

    Returns:
        URL сгенерированного видео или None
    """
    logger.info(
        "LIFESTYLE_VIDEO GENERATE | ref=%s | prompt_len=%d",
        ref_image_url, len(prompt),
    )

    task_id = await _create_video_task(
        session=session,
        api_base=api_base,
        api_key=api_key,
        image_url=ref_image_url,
        prompt=prompt,
    )
    if not task_id:
        return None

    logger.info("LIFESTYLE_VIDEO TASK CREATED | taskId=%s", task_id)

    result = await _poll_video_task(
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
        video_url = urls[0] if urls else None
    except (json.JSONDecodeError, IndexError, TypeError):
        logger.error("LIFESTYLE_VIDEO result parse error | resultJson=%s", result_json_str)
        video_url = None

    logger.info("LIFESTYLE_VIDEO RESULT | taskId=%s | video_url=%s", task_id, video_url)
    return video_url
