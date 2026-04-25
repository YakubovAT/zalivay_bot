"""
handlers/flows/t2i_admin.py

Секретная команда /08111981 — генерация T2I изображений для Pinterest.
Доступна только администраторам (ADMIN_USER_IDS в .env).

Flow:
  1. /08111981 → проверка прав
  2. Бот спрашивает количество
  3. Пользователь вводит число
  4. Бот запускает фоновую генерацию и присылает прогресс
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import asyncpg
from telegram import Update
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

# ── Настройки ──────────────────────────────────────────────────────────────────
_ADMIN_IDS: frozenset[int] = frozenset(
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()
)

_API_KEY      = os.getenv("I2I_API_KEY") or os.getenv("AI_API_KEY")
_API_BASE     = os.getenv("I2I_API_BASE", "https://api.kie.ai")
_DATABASE_URL = os.getenv("DATABASE_URL")

_MODEL        = "gpt-image-2-text-to-image"
_ASPECT_RATIO = "auto"

_USER_ID      = 171470918
_ARTICLE_CODE = "00000"

_PROMPTS_FILE = Path("promts/t2i_pinterest.md")
_MEDIA_DIR    = Path(f"media/{_USER_ID}/generated/{_ARTICLE_CODE}")

_MAX_POLL_ATTEMPTS = 60
_POLL_INTERVAL     = 5    # сек
_CONCURRENCY       = 5    # параллельных задач одновременно
_MAX_COUNT         = 500

# ── Состояния FSM ──────────────────────────────────────────────────────────────
_WAIT_COUNT = 0


# ── Вспомогательные функции ────────────────────────────────────────────────────

def _load_prompts() -> list[str]:
    if not _PROMPTS_FILE.exists():
        return []
    lines = _PROMPTS_FILE.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


async def _create_task(session: aiohttp.ClientSession, prompt: str) -> str | None:
    payload = {
        "model": _MODEL,
        "input": {"prompt": prompt, "aspect_ratio": _ASPECT_RATIO},
    }
    try:
        async with session.post(
            f"{_API_BASE}/api/v1/jobs/createTask",
            headers={"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("taskId")
            logger.error("T2I create: code=%s msg=%s", data.get("code"), data.get("msg"))
    except Exception as e:
        logger.error("T2I create error: %s", e)
    return None


async def _poll_task(session: aiohttp.ClientSession, task_id: str) -> str | None:
    for attempt in range(1, _MAX_POLL_ATTEMPTS + 1):
        try:
            async with session.get(
                f"{_API_BASE}/api/v1/jobs/recordInfo",
                params={"taskId": task_id},
                headers={"Authorization": f"Bearer {_API_KEY}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data  = await resp.json()
                code  = data.get("code")
                inner = data.get("data", {})
                state = inner.get("state", "unknown")

                if code == 249 or state in ("waiting", "queuing", "generating"):
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                if code == 200 and state == "success":
                    urls = json.loads(inner.get("resultJson", "{}")).get("resultUrls", [])
                    return urls[0] if urls else None

                if state == "fail":
                    logger.error("T2I task fail: %s %s", inner.get("failCode"), inner.get("failMsg"))
                    return None

                await asyncio.sleep(_POLL_INTERVAL)
        except Exception as e:
            logger.warning("T2I poll #%d: %s", attempt, e)
            await asyncio.sleep(_POLL_INTERVAL)
    return None


async def _download(session: aiohttp.ClientSession, url: str, path: Path) -> bool:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(await resp.read())
            return True
    except Exception as e:
        logger.error("T2I download error: %s", e)
        return False


# ── Фоновая генерация ──────────────────────────────────────────────────────────

async def _run_generation(bot, chat_id: int, count: int) -> None:
    prompts = _load_prompts()
    if not prompts:
        await bot.send_message(chat_id, "❌ Файл промптов пуст или не найден.")
        return

    db = await asyncpg.connect(_DATABASE_URL)
    sem = asyncio.Semaphore(_CONCURRENCY)
    results = {"done": 0, "failed": 0}
    lock = asyncio.Lock()

    async def process_one(idx: int) -> None:
        prompt = prompts[idx % len(prompts)]
        async with sem:
            task_id = await _create_task(worker_session, prompt)
            if not task_id:
                async with lock:
                    results["failed"] += 1
                return

            url = await _poll_task(worker_session, task_id)
            if not url:
                async with lock:
                    results["failed"] += 1
                return

            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"photo_{ts}_{idx:04d}.png"
            save_path = _MEDIA_DIR / filename

            ok = await _download(worker_session, url, save_path)
            if ok:
                await db.execute(
                    "INSERT INTO media_files (user_id, article_code, file_path, result_url, file_type) "
                    "VALUES ($1, $2, $3, $4, 'photo')",
                    _USER_ID, _ARTICLE_CODE, str(save_path), url,
                )
                async with lock:
                    results["done"] += 1
                    done = results["done"]

                if done % 10 == 0:
                    try:
                        await bot.send_message(
                            chat_id,
                            f"⏳ Готово {done}/{count} изображений..."
                        )
                    except Exception:
                        pass
            else:
                async with lock:
                    results["failed"] += 1

    connector = aiohttp.TCPConnector(limit=20)
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(connect=10, total=120),
    ) as worker_session:
        tasks = [asyncio.create_task(process_one(i)) for i in range(count)]
        await asyncio.gather(*tasks, return_exceptions=True)

    await db.close()

    done   = results["done"]
    failed = results["failed"]
    await bot.send_message(
        chat_id,
        f"✅ Генерация завершена!\n\n"
        f"Создано: {done}\n"
        f"Ошибок: {failed}\n\n"
        f"Файлы доступны в /pinterest и /watermark"
    )


# ── Обработчики FSM ────────────────────────────────────────────────────────────

async def cmd_t2i_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in _ADMIN_IDS:
        return ConversationHandler.END

    prompts = _load_prompts()
    if not prompts:
        await update.message.reply_text(
            "❌ Файл промптов не найден или пуст.\n"
            f"Добавь промпты в: {_PROMPTS_FILE}"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"🎨 T2I генератор\n\n"
        f"Промптов в файле: {len(prompts)}\n"
        f"Артикул: {_ARTICLE_CODE}\n\n"
        f"Сколько изображений создать? (1–{_MAX_COUNT})"
    )
    return _WAIT_COUNT


async def msg_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text("Введи число, например: 100")
        return _WAIT_COUNT

    count = int(text)
    if count < 1 or count > _MAX_COUNT:
        await update.message.reply_text(f"Число должно быть от 1 до {_MAX_COUNT}")
        return _WAIT_COUNT

    prompts = _load_prompts()
    await update.message.reply_text(
        f"🚀 Запускаю генерацию {count} изображений\n"
        f"Промптов: {len(prompts)} (по кругу)\n"
        f"Параллельно: {_CONCURRENCY}\n\n"
        f"Буду присылать прогресс каждые 10 фото."
    )

    asyncio.create_task(
        _run_generation(context.bot, update.effective_chat.id, count)
    )

    return ConversationHandler.END


# ── Сборка хендлера ────────────────────────────────────────────────────────────

async def _end_and_redispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    asyncio.create_task(context.application.process_update(update))
    return ConversationHandler.END


def build_t2i_admin_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("08111981", cmd_t2i_admin)],
        states={
            _WAIT_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_count)],
        },
        fallbacks=[
            CommandHandler("08111981", cmd_t2i_admin),
            MessageHandler(filters.COMMAND, _end_and_redispatch),
        ],
        name="t2i_admin",
        persistent=False,
    )
