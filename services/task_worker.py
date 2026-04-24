"""
services/task_worker.py

Два воркера в одном модуле:

1. run_worker — старый последовательный воркер для задач типа 'photo'/'video'
   (создание эталонов). Работает как раньше.

2. run_job_worker — новый параллельный воркер для задач типа 'lifestyle_photo'
   (создание фото через gen_photo flow).
   - Держит до MAX_CONCURRENT задач одновременно через asyncio.create_task
   - После завершения каждой задачи проверяет готовность группы (job)
   - Если группа готова — собирает альбом и отправляет пользователю
   - Если группа полностью упала — уведомляет об ошибке
   - Переживает рестарт бота: зависшие processing → pending при старте
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from io import BytesIO

import aiohttp
from telegram import Bot

from database import (
    get_pending_tasks,
    complete_task,
    fail_task,
    fail_stuck_tasks,
    get_reference,
    get_pending_job_tasks,
    complete_job_task,
    fail_job_task,
    get_job_status,
    get_job_info,
    get_job_results,
    complete_generation_job,
    fail_generation_job,
    fail_stuck_jobs,
    deduct_balance,
    get_pending_video_job_tasks,
    fail_stuck_video_jobs,
    register_media_file,
)
from services.reference_i2i import generate_reference_image
from services.lifestyle_photo_generator import generate_lifestyle_photo
from services.lifestyle_video_generator import generate_lifestyle_video
from config import I2I_API_BASE, I2I_API_KEY, PHOTO_COST, VIDEO_COST
from handlers.keyboards import kb_gen_photo_result, kb_gen_video_result
from handlers.flows.messages.common import (
    msg_generation_done,
    msg_generation_failed,
    msg_video_generation_done,
    msg_video_generation_failed,
)

logger = logging.getLogger(__name__)

# Старый воркер
POLL_INTERVAL = 5    # секунд между проверками очереди
BATCH_SIZE    = 3    # задач за один цикл

# Новый job-воркер
JOB_POLL_INTERVAL = 3    # секунд между проверками очереди job-задач
MAX_CONCURRENT    = 10   # максимум одновременных запросов к Kie.ai


# ---------------------------------------------------------------------------
# Старый воркер — создание эталонов (photo / video)
# ---------------------------------------------------------------------------

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
            ref = await get_reference(user_id, articul)
            ref_image_url = ref["reference_image_url"] if ref and ref.get("reference_image_url") else ""

            if ref_image_url:
                logger.info("WORKER | task_id=%d | using reference_image: %s", task_id, ref_image_url[:80])
                image_urls = [ref_image_url]
            else:
                logger.warning("WORKER | task_id=%d | no reference_image_url, using prompt-only", task_id)
                image_urls = []

            image_url = await generate_reference_image(
                session=session,
                api_base=I2I_API_BASE,
                api_key=I2I_API_KEY,
                image_urls=image_urls,
                prompt=prompt,
            )

            if not image_url:
                raise RuntimeError("I2I вернул пустой URL")

            async with session.get(
                image_url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                image_data = await resp.read()

            await bot.send_photo(
                chat_id=chat_id,
                photo=BytesIO(image_data),
                caption=f"📸 Фото для артикула <code>{articul}</code> готово!",
                parse_mode="HTML",
            )

            await complete_task(task_id, image_url)
            logger.info("WORKER | task_id=%d | completed", task_id)

        elif task_type == "video":
            raise NotImplementedError("Video generation not implemented yet")

    except Exception as e:
        error_msg = str(e)
        logger.error("WORKER | task_id=%d | failed: %s", task_id, error_msg)
        await fail_task(task_id, error_msg)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка создания фото для артикула <code>{articul}</code>.\n"
                     f"Попробуйте позже.",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def run_worker(bot, session: aiohttp.ClientSession) -> None:
    """Старый последовательный воркер для photo/video задач."""
    logger.info("WORKER | started | poll_interval=%ds | batch=%d", POLL_INTERVAL, BATCH_SIZE)

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


# ---------------------------------------------------------------------------
# Новый job-воркер — создание lifestyle фото (параллельный, Вариант C)
# ---------------------------------------------------------------------------

async def _finish_job(job_id: int, bot, session: aiohttp.ClientSession) -> None:
    """
    Проверяет готовность группы. Если все задачи завершены — отправляет альбом.
    Вызывается после каждого complete/fail задачи группы.
    """
    status = await get_job_status(job_id)
    if status["in_progress"] > 0:
        # Ещё есть незавершённые задачи — ждём
        return

    job = await get_job_info(job_id)
    if not job:
        return

    user_id    = job["user_id"]
    chat_id    = job["chat_id"]
    article    = job["article"]
    ref_number = job["ref_number"]
    completed  = status["completed"]
    failed     = status["failed"]

    # Время создания
    elapsed = datetime.now(timezone.utc) - job["created_at"]
    elapsed_min = int(elapsed.total_seconds() // 60)
    elapsed_sec = int(elapsed.total_seconds() % 60)
    elapsed_str = f"{elapsed_min}м {elapsed_sec}с" if elapsed_min else f"{elapsed_sec}с"

    logger.info(
        "JOB_WORKER | job_id=%d | finished | completed=%d failed=%d elapsed=%s",
        job_id, completed, failed, elapsed_str,
    )

    if completed == 0:
        # Все упали — уведомляем, баланс не списываем
        await fail_generation_job(job_id)
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=open("assets/banner_default.png", "rb"),
                caption=await msg_generation_failed(job_id),
                parse_mode="HTML",
                reply_markup=kb_gen_photo_result(),
            )
        except Exception as e:
            logger.error("JOB_WORKER | job_id=%d | notify_fail error: %s", job_id, e)
        return

    # Есть готовые фото — списываем и отправляем первое
    file_paths  = await get_job_results(job_id)
    actual_cost = len(file_paths) * PHOTO_COST
    new_balance = await deduct_balance(user_id, actual_cost)

    caption = await msg_generation_done(
        article=article,
        ref_number=ref_number,
        total=len(file_paths),
        actual_cost=actual_cost,
        new_balance=new_balance,
        elapsed_str=elapsed_str,
        job_id=job_id,
        failed=failed,
    )

    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=open(file_paths[0], "rb"),
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb_gen_photo_result(),
        )
        await complete_generation_job(job_id)
        logger.info("JOB_WORKER | job_id=%d | done | files=%d elapsed=%s", job_id, len(file_paths), elapsed_str)

    except Exception as e:
        logger.error("JOB_WORKER | job_id=%d | send_result error: %s", job_id, e)
        await fail_generation_job(job_id)


async def _process_job_task(
    task: dict,
    session: aiohttp.ClientSession,
    bot,
    semaphore: asyncio.Semaphore,
) -> None:
    """
    Обрабатывает одну lifestyle_photo задачу:
    createTask → poll → скачать → complete_job_task → проверить группу.
    """
    task_id   = task["id"]
    job_id    = task["job_id"]
    user_id   = task["user_id"]
    articul   = task["articul"]
    prompt    = task["prompt"]

    logger.info("JOB_WORKER | task_id=%d job_id=%d | start", task_id, job_id)

    async with semaphore:
        try:
            job = await get_job_info(job_id)
            if not job:
                raise RuntimeError(f"job_id={job_id} не найден")

            ref_image_url = job["ref_image_url"]

            result_url = await generate_lifestyle_photo(
                session=session,
                api_base=I2I_API_BASE,
                api_key=I2I_API_KEY,
                ref_image_url=ref_image_url,
                prompt=prompt,
            )

            if not result_url:
                raise RuntimeError("generate_lifestyle_photo вернул None")

            # Скачиваем и сохраняем локально
            save_dir = f"media/{user_id}/generated/{articul}"
            os.makedirs(save_dir, exist_ok=True)
            save_path = f"{save_dir}/photo_{articul}_{task_id}.png"

            async with session.get(result_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    with open(save_path, "wb") as f:
                        f.write(await resp.read())
                else:
                    raise RuntimeError(f"Скачивание упало: HTTP {resp.status}")

            await complete_job_task(task_id, result_url, save_path)
            await register_media_file(user_id, articul, task_id, save_path, result_url, "photo")
            logger.info("JOB_WORKER | task_id=%d | completed | path=%s", task_id, save_path)

        except Exception as e:
            logger.error("JOB_WORKER | task_id=%d | failed: %s", task_id, e)
            await fail_job_task(task_id, str(e))

    # После завершения задачи (вне семафора) — проверяем группу
    try:
        await _finish_job(job_id, bot, session)
    except Exception as e:
        logger.error("JOB_WORKER | job_id=%d | _finish_job error: %s", job_id, e)


async def run_job_worker(bot, session: aiohttp.ClientSession) -> None:
    """
    Параллельный воркер lifestyle_photo задач.

    Держит пул asyncio.Task размером MAX_CONCURRENT.
    Каждые JOB_POLL_INTERVAL секунд добирает задачи до максимума.
    """
    logger.info(
        "JOB_WORKER | started | poll_interval=%ds | max_concurrent=%d",
        JOB_POLL_INTERVAL, MAX_CONCURRENT,
    )

    # Сбрасываем зависшие при старте
    recovered = await fail_stuck_jobs(minutes=15)
    if recovered:
        logger.info("JOB_WORKER | recovered %d stuck job tasks", recovered)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    running: set[asyncio.Task] = set()

    while True:
        try:
            # Сколько слотов свободно
            free_slots = MAX_CONCURRENT - len(running)
            if free_slots > 0:
                tasks = await get_pending_job_tasks(limit=free_slots)
                for task in tasks:
                    t = asyncio.create_task(
                        _process_job_task(dict(task), session, bot, semaphore)
                    )
                    running.add(t)
                    t.add_done_callback(running.discard)

                if tasks:
                    logger.info("JOB_WORKER | dispatched %d tasks | running=%d", len(tasks), len(running))

        except Exception as e:
            logger.error("JOB_WORKER | loop error: %s", e)

        await asyncio.sleep(JOB_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Video job-воркер — создание lifestyle видео (параллельный)
# ---------------------------------------------------------------------------

# Видео создается дольше — держим меньше параллельных задач
VIDEO_MAX_CONCURRENT = 5
VIDEO_POLL_INTERVAL  = 5


async def _finish_video_job(job_id: int, bot, session: aiohttp.ClientSession) -> None:
    """
    Проверяет готовность группы видео. Если все задачи завершены — отправляет первое видео.
    """
    status = await get_job_status(job_id)
    if status["in_progress"] > 0:
        return

    job = await get_job_info(job_id)
    if not job:
        return

    user_id    = job["user_id"]
    chat_id    = job["chat_id"]
    article    = job["article"]
    ref_number = job["ref_number"]
    completed  = status["completed"]
    failed     = status["failed"]

    elapsed = datetime.now(timezone.utc) - job["created_at"]
    elapsed_min = int(elapsed.total_seconds() // 60)
    elapsed_sec = int(elapsed.total_seconds() % 60)
    elapsed_str = f"{elapsed_min}м {elapsed_sec}с" if elapsed_min else f"{elapsed_sec}с"

    logger.info(
        "VIDEO_JOB_WORKER | job_id=%d | finished | completed=%d failed=%d elapsed=%s",
        job_id, completed, failed, elapsed_str,
    )

    if completed == 0:
        await fail_generation_job(job_id)
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=open("assets/banner_default.png", "rb"),
                caption=await msg_video_generation_failed(job_id),
                parse_mode="HTML",
                reply_markup=kb_gen_video_result(),
            )
        except Exception as e:
            logger.error("VIDEO_JOB_WORKER | job_id=%d | notify_fail error: %s", job_id, e)
        return

    file_paths  = await get_job_results(job_id)
    actual_cost = len(file_paths) * VIDEO_COST
    new_balance = await deduct_balance(user_id, actual_cost)

    caption = await msg_video_generation_done(
        article=article,
        ref_number=ref_number,
        total=len(file_paths),
        actual_cost=actual_cost,
        new_balance=new_balance,
        elapsed_str=elapsed_str,
        job_id=job_id,
        failed=failed,
    )

    try:
        await bot.send_video(
            chat_id=chat_id,
            video=open(file_paths[0], "rb"),
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb_gen_video_result(),
        )
        await complete_generation_job(job_id)
        logger.info("VIDEO_JOB_WORKER | job_id=%d | done | files=%d elapsed=%s", job_id, len(file_paths), elapsed_str)

    except Exception as e:
        logger.error("VIDEO_JOB_WORKER | job_id=%d | send_result error: %s", job_id, e)
        await fail_generation_job(job_id)


async def _process_video_job_task(
    task: dict,
    session: aiohttp.ClientSession,
    bot,
    semaphore: asyncio.Semaphore,
) -> None:
    """
    Обрабатывает одну lifestyle_video задачу:
    createTask → poll → скачать → complete_job_task → проверить группу.
    """
    task_id = task["id"]
    job_id  = task["job_id"]
    user_id = task["user_id"]
    articul = task["articul"]
    prompt  = task["prompt"]

    logger.info("VIDEO_JOB_WORKER | task_id=%d job_id=%d | start", task_id, job_id)

    async with semaphore:
        try:
            job = await get_job_info(job_id)
            if not job:
                raise RuntimeError(f"job_id={job_id} не найден")

            ref_image_url = job["ref_image_url"]

            result_url = await generate_lifestyle_video(
                session=session,
                api_base=I2I_API_BASE,
                api_key=I2I_API_KEY,
                ref_image_url=ref_image_url,
                prompt=prompt,
            )

            if not result_url:
                raise RuntimeError("generate_lifestyle_video вернул None")

            # Скачиваем и сохраняем локально
            save_dir = f"media/{user_id}/generated/{articul}"
            os.makedirs(save_dir, exist_ok=True)
            save_path = f"{save_dir}/video_{articul}_{task_id}.mp4"

            async with session.get(result_url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status == 200:
                    with open(save_path, "wb") as f:
                        f.write(await resp.read())
                else:
                    raise RuntimeError(f"Скачивание упало: HTTP {resp.status}")

            await complete_job_task(task_id, result_url, save_path)
            await register_media_file(user_id, articul, task_id, save_path, result_url, "video")
            logger.info("VIDEO_JOB_WORKER | task_id=%d | completed | path=%s", task_id, save_path)

        except Exception as e:
            logger.error("VIDEO_JOB_WORKER | task_id=%d | failed: %s", task_id, e)
            await fail_job_task(task_id, str(e))

    try:
        await _finish_video_job(job_id, bot, session)
    except Exception as e:
        logger.error("VIDEO_JOB_WORKER | job_id=%d | _finish_video_job error: %s", job_id, e)


async def run_video_job_worker(bot, session: aiohttp.ClientSession) -> None:
    """
    Параллельный воркер lifestyle_video задач.
    """
    logger.info(
        "VIDEO_JOB_WORKER | started | poll_interval=%ds | max_concurrent=%d",
        VIDEO_POLL_INTERVAL, VIDEO_MAX_CONCURRENT,
    )

    recovered = await fail_stuck_video_jobs(minutes=30)
    if recovered:
        logger.info("VIDEO_JOB_WORKER | recovered %d stuck video tasks", recovered)

    semaphore = asyncio.Semaphore(VIDEO_MAX_CONCURRENT)
    running: set[asyncio.Task] = set()

    while True:
        try:
            free_slots = VIDEO_MAX_CONCURRENT - len(running)
            if free_slots > 0:
                tasks = await get_pending_video_job_tasks(limit=free_slots)
                for task in tasks:
                    t = asyncio.create_task(
                        _process_video_job_task(dict(task), session, bot, semaphore)
                    )
                    running.add(t)
                    t.add_done_callback(running.discard)

                if tasks:
                    logger.info("VIDEO_JOB_WORKER | dispatched %d tasks | running=%d", len(tasks), len(running))

        except Exception as e:
            logger.error("VIDEO_JOB_WORKER | loop error: %s", e)

        await asyncio.sleep(VIDEO_POLL_INTERVAL)
