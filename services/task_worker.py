"""
services/task_worker.py

Фоновый воркер очереди задач генерации фото и видео.

Логика:
  - Каждые POLL_INTERVAL секунд берёт pending задачи из БД (пачками по BATCH_SIZE)
  - Для каждой задачи: I2I API → скачать → отправить пользователю → complete_task
  - При ошибке: fail_task → уведомить пользователя
  - При старте: сбрасывает зависшие processing задачи обратно в pending
"""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO

import aiohttp

from database import get_pending_tasks, complete_task, fail_task, fail_stuck_tasks, get_reference
from services.reference_i2i import generate_reference_image
from config import AI_API_BASE, AI_API_KEY

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5   # секунд между проверками очереди
BATCH_SIZE    = 3   # задач за один цикл


async def _process_task(task: dict, session: aiohttp.ClientSession, bot) -> None:
    """Обрабатывает одну задачу: I2I → скачать → отправить пользователю."""
    task_id   = task["id"]
    user_id   = task["user_id"]
    chat_id   = task["chat_id"]
    task_type = task["task_type"]
    articul   = task["articul"]
    prompt    = task["prompt"]

    logger.info("WORKER | task_id=%d | type=%s | user_id=%d | articul=%s",
                task_id, task_type, user_id, articul)

    try:
        if task_type == "photo":
            # Получаем URL эталона из БД для I2I
            ref = await get_reference(user_id, articul)
            ref_image_url = ref["reference_image_url"] if ref and ref.get("reference_image_url") else ""

            if ref_image_url:
                logger.info("WORKER | task_id=%d | using reference_image: %s", task_id, ref_image_url[:80])
                image_urls = [ref_image_url]
            else:
                logger.warning("WORKER | task_id=%d | no reference_image_url, using prompt-only", task_id)
                image_urls = []

            # I2I генерация — передаём эталон + промпт
            image_url = await generate_reference_image(
                session=session,
                api_base=AI_API_BASE,
                api_key=AI_API_KEY,
                image_urls=image_urls,
                prompt=prompt,
            )

            if not image_url:
                raise RuntimeError("I2I вернул пустой URL")

            # Скачиваем изображение
            async with session.get(
                image_url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                image_data = await resp.read()

            # Отправляем пользователю
            await bot.send_photo(
                chat_id=chat_id,
                photo=BytesIO(image_data),
                caption=f"📸 Фото для артикула <code>{articul}</code> готово!",
                parse_mode="HTML",
            )

            await complete_task(task_id, image_url)
            logger.info("WORKER | task_id=%d | completed", task_id)

        elif task_type == "video":
            # TODO: видео генерация
            raise NotImplementedError("Video generation not implemented yet")

    except Exception as e:
        error_msg = str(e)
        logger.error("WORKER | task_id=%d | failed: %s", task_id, error_msg)
        await fail_task(task_id, error_msg)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка генерации фото для артикула <code>{articul}</code>.\n"
                     f"Попробуйте позже.",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def run_worker(bot, session: aiohttp.ClientSession) -> None:
    """
    Основной цикл воркера. Запускается как asyncio task при старте бота.
    """
    logger.info("WORKER | started | poll_interval=%ds | batch=%d", POLL_INTERVAL, BATCH_SIZE)

    # Сбрасываем зависшие задачи при старте
    recovered = await fail_stuck_tasks(minutes=10)
    if recovered:
        logger.info("WORKER | recovered %d stuck tasks", recovered)

    while True:
        try:
            tasks = await get_pending_tasks(limit=BATCH_SIZE)

            if tasks:
                logger.info("WORKER | picked %d tasks", len(tasks))
                for task in tasks:
                    await _process_task(dict(task), session, bot)

        except Exception as e:
            logger.error("WORKER | loop error: %s", e)

        await asyncio.sleep(POLL_INTERVAL)
