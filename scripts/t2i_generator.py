#!/usr/bin/env python3
"""
scripts/t2i_generator.py

Генерирует изображения через gpt-image-2-text-to-image (T2I),
сохраняет в media/{USER_ID}/generated/{ARTICLE_CODE}/
и регистрирует в таблице media_files — как обычные фото бота.

Запуск: python scripts/t2i_generator.py
Остановка: Ctrl+C
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import asyncpg
from dotenv import load_dotenv

load_dotenv()

# ── Настройки ──────────────────────────────────────────────────────────────────
API_KEY      = os.getenv("I2I_API_KEY") or os.getenv("AI_API_KEY")
API_BASE     = os.getenv("I2I_API_BASE", "https://api.kie.ai")
DATABASE_URL = os.getenv("DATABASE_URL")

MODEL        = "gpt-image-2-text-to-image"
ASPECT_RATIO = "auto"   # "auto" | "1:1" | "2:3" | "3:2"

USER_ID      = 171470918
ARTICLE_CODE = "00000"

PROMPTS_FILE = Path("promts/t2i_pinterest.md")
MEDIA_DIR    = Path(f"media/{USER_ID}/generated/{ARTICLE_CODE}")

MAX_POLL_ATTEMPTS = 60
POLL_INTERVAL     = 5   # сек между проверками статуса
DELAY_BETWEEN     = 2   # сек между задачами

# ── Логирование ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("t2i")


# ── Промпты ────────────────────────────────────────────────────────────────────
def load_prompts() -> list[str]:
    if not PROMPTS_FILE.exists():
        sys.exit(f"Файл промптов не найден: {PROMPTS_FILE}")
    lines = PROMPTS_FILE.read_text(encoding="utf-8").splitlines()
    prompts = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    if not prompts:
        sys.exit(f"В файле нет промптов: {PROMPTS_FILE}")
    log.info("Загружено промптов: %d из %s", len(prompts), PROMPTS_FILE)
    return prompts


# ── API ────────────────────────────────────────────────────────────────────────
async def create_task(session: aiohttp.ClientSession, prompt: str) -> str | None:
    payload = {
        "model": MODEL,
        "input": {"prompt": prompt, "aspect_ratio": ASPECT_RATIO},
    }
    try:
        async with session.post(
            f"{API_BASE}/api/v1/jobs/createTask",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
            if data.get("code") == 200:
                task_id = data.get("data", {}).get("taskId")
                log.info("Задача создана: %s", task_id)
                return task_id
            log.error("Ошибка создания: code=%s msg=%s", data.get("code"), data.get("msg"))
    except Exception as e:
        log.error("create_task error: %s", e)
    return None


async def poll_task(session: aiohttp.ClientSession, task_id: str) -> str | None:
    """Ожидает завершения задачи. Возвращает URL изображения или None."""
    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        try:
            async with session.get(
                f"{API_BASE}/api/v1/jobs/recordInfo",
                params={"taskId": task_id},
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data  = await resp.json()
                code  = data.get("code")
                inner = data.get("data", {})
                state = inner.get("state", "unknown")
                log.info("Polling #%d | %s | state=%s", attempt, task_id, state)

                if code == 249 or state in ("waiting", "queuing", "generating"):
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                if code == 200 and state == "success":
                    result_json = json.loads(inner.get("resultJson", "{}"))
                    urls = result_json.get("resultUrls", [])
                    return urls[0] if urls else None

                if state == "fail":
                    log.error("Задача провалена: failCode=%s failMsg=%s",
                              inner.get("failCode"), inner.get("failMsg"))
                    return None

                await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            log.warning("poll_task #%d error: %s", attempt, e)
            await asyncio.sleep(POLL_INTERVAL)

    log.error("Таймаут polling: %s", task_id)
    return None


async def download_image(session: aiohttp.ClientSession, url: str, path: Path) -> bool:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(await resp.read())
            log.info("Сохранено: %s", path)
            return True
    except Exception as e:
        log.error("download_image error: %s", e)
        return False


# ── БД ─────────────────────────────────────────────────────────────────────────
async def register_file(db: asyncpg.Connection, file_path: str, result_url: str) -> None:
    await db.execute(
        """
        INSERT INTO media_files (user_id, article_code, file_path, result_url, file_type)
        VALUES ($1, $2, $3, $4, 'photo')
        """,
        USER_ID, ARTICLE_CODE, file_path, result_url,
    )
    log.info("Зарегистрировано в БД: %s", file_path)


# ── Главный цикл ───────────────────────────────────────────────────────────────
async def main() -> None:
    if not API_KEY:
        sys.exit("Не задан I2I_API_KEY в .env")
    if not DATABASE_URL:
        sys.exit("Не задан DATABASE_URL в .env")

    prompts = load_prompts()
    db = await asyncpg.connect(DATABASE_URL)
    total = 0
    idx   = 0

    log.info("Запуск T2I генератора | model=%s | article=%s | user=%s",
             MODEL, ARTICLE_CODE, USER_ID)
    log.info("Промптов в очереди: %d (по кругу). Остановить: Ctrl+C", len(prompts))

    try:
        async with aiohttp.ClientSession() as session:
            while True:
                prompt_idx = idx % len(prompts)
                prompt = prompts[prompt_idx]
                idx   += 1
                total += 1

                log.info("─── [%d] промпт #%d: %.80s...", total, prompt_idx + 1, prompt)

                task_id = await create_task(session, prompt)
                if not task_id:
                    log.warning("Пропуск: задача не создана")
                    await asyncio.sleep(DELAY_BETWEEN)
                    continue

                result_url = await poll_task(session, task_id)
                if not result_url:
                    log.warning("Пропуск: нет URL результата")
                    await asyncio.sleep(DELAY_BETWEEN)
                    continue

                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                filename = f"photo_{ts}_{total:04d}.png"
                save_path = MEDIA_DIR / filename

                ok = await download_image(session, result_url, save_path)
                if ok:
                    await register_file(db, str(save_path), result_url)
                    log.info("✓ Готово [всего: %d]", total)

                await asyncio.sleep(DELAY_BETWEEN)

    except KeyboardInterrupt:
        log.info("Остановлено. Всего сгенерировано: %d", total)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
