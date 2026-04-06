#!/usr/bin/env python3
"""
Mock Kie.ai сервер — полная эмуляция реального API.

Документация: https://docs.kie.ai/
Эндпоинты:
  - T2T: POST /gpt-5-2/v1/chat/completions
  - I2I/I2V: POST /api/v1/jobs/createTask
  - Статус: GET /api/v1/jobs/taskDetail/{taskId}

Запуск:
  uvicorn mock_kie_server:app --host 0.0.0.0 --port 8080 --reload
"""

import logging
import os
import time
import uuid
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("mock_kie")

app = FastAPI(title="Mock Kie.ai Server", version="2.0.0")

# Путь к файлу-заглушке
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MOCK_IMAGE_PATH = os.path.join(_BASE_DIR, "эталон225616209.png")
MOCK_IMAGE_URL = "http://localhost:8080/static/reference.png"

# ---------------------------------------------------------------------------
# Заготовленные ответы
# ---------------------------------------------------------------------------

MOCK_PROMPT = (
    "Analyze the provided product photographs and isolate ONLY the clothing item. "
    "Remove the model body, background, accessories, text, and all other objects. "
    "Preserve the natural 3D shape with accurate proportions, all fabric details: "
    "texture, folds, seams, stitching, patterns, prints, exact colors and lighting. "
    "Create a new PNG image with the isolated item on a transparent background (RGBA). "
    "Maximum resolution, professional e-commerce standard. "
    "Centered as on an invisible mannequin. Clean edges, no halos or artifacts. "
    "Suitable for clothing catalog and video animation. "
    "Output ONLY the final image — nothing else. "
    "Do not add, invent, or modify any details, colors, or patterns of the garment."
)

# In-memory task storage
_tasks: dict = {}

# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _check_auth(authorization: Optional[str]) -> None:
    """Проверяет Bearer токен. В mock — всегда пропускает если есть заголовок."""
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("AUTH FAILED — 401 Unauthorized")
        raise HTTPException(
            status_code=401,
            detail={"code": 401, "msg": "You do not have access permissions"},
        )

# ---------------------------------------------------------------------------
# T2T: Chat Completions
# ---------------------------------------------------------------------------

class ChatContentItem(BaseModel):
    type: str
    text: Optional[str] = None
    image_url: Optional[dict] = None


class ChatMessage(BaseModel):
    role: str
    content: str | list[ChatContentItem]


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    tools: Optional[list[dict]] = None
    reasoning_effort: Optional[str] = None


@app.post("/gpt-5-2/v1/chat/completions")
async def chat_completions(req: ChatRequest, authorization: Optional[str] = Header(None)):
    """T2T — генерация промпта (OpenAI-совместимый формат)."""
    _check_auth(authorization)

    # Логируем запрос
    system_msg = next((str(m.content) for m in req.messages if m.role == "system"), "")
    user_msg = next((str(m.content) for m in req.messages if m.role == "user"), "")

    logger.info(
        "T2T REQUEST | model=%s | system_len=%d | user_len=%d",
        req.model, len(system_msg), len(user_msg),
    )
    logger.debug("T2T SYSTEM: %s", system_msg[:200])
    logger.debug("T2T USER: %s", user_msg[:200])

    logger.info("T2T RESPONSE | generated prompt (%d chars)", len(MOCK_PROMPT))

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "gpt-5-2",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": MOCK_PROMPT,
                    "refusal": None,
                    "annotations": [],
                },
                "logprobs": None,
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": len(MOCK_PROMPT.split()),
            "total_tokens": 120 + len(MOCK_PROMPT.split()),
        },
    }


# ---------------------------------------------------------------------------
# I2I / I2V: Create Task
# ---------------------------------------------------------------------------

class I2IInput(BaseModel):
    input_urls: Optional[list[str]] = []
    prompt: str
    aspect_ratio: Optional[str] = None
    quality: Optional[str] = None
    # I2V поля (опциональны для валидации)
    image_urls: Optional[list[str]] = []
    n_frames: Optional[str] = None
    remove_watermark: Optional[bool] = None
    upload_method: Optional[str] = None
    character_id_list: Optional[list[str]] = None


class CreateTaskRequest(BaseModel):
    model: str
    callBackUrl: Optional[str] = None
    progressCallBackUrl: Optional[str] = None
    input: I2IInput


@app.post("/api/v1/jobs/createTask")
async def create_task(req: CreateTaskRequest, authorization: Optional[str] = Header(None)):
    """I2I или I2V — создание задачи."""
    _check_auth(authorization)

    task_id = f"task_{req.model.replace('/', '-').replace('.', '_')}_{int(time.time() * 1000)}"

    # Определяем URLs для результата
    urls = req.input.input_urls if req.input.input_urls else req.input.image_urls or []

    logger.info(
        "CREATE TASK | taskId=%s | model=%s | prompt_len=%d | images=%d | urls=%s",
        task_id, req.model, len(req.input.prompt), len(urls), urls,
    )

    _tasks[task_id] = {
        "taskId": task_id,
        "model": req.model,
        "status": "completed",
        "progress": 100,
        "input": req.input.model_dump(),
        "result": {
            "imageUrl": MOCK_IMAGE_URL,
        },
        "created_at": int(time.time()),
        "credits_used": 1,
    }

    logger.info("CREATE TASK RESPONSE | taskId=%s | status=completed", task_id)

    return {
        "code": 200,
        "msg": "success",
        "data": {
            "taskId": task_id,
        },
    }


# ---------------------------------------------------------------------------
# Task Detail (polling)
# ---------------------------------------------------------------------------

@app.get("/api/v1/jobs/recordInfo")
async def task_detail(taskId: str, authorization: Optional[str] = Header(None)):
    """Статус задачи. Реальный путь: GET /api/v1/jobs/recordInfo?taskId=..."""
    _check_auth(authorization)

    task = _tasks.get(taskId)
    if not task:
        logger.warning("TASK NOT FOUND | taskId=%s", taskId)
        raise HTTPException(
            status_code=404,
            detail={"code": 404, "msg": "Task not found"},
        )

    logger.info(
        "TASK DETAIL | taskId=%s | model=%s | status=%s | result=%s",
        taskId, task["model"], task["status"], task.get("result"),
    )

    return {
        "code": 200,
        "msg": "success",
        "data": {
            "taskId": task["taskId"],
            "model": task["model"],
            "status": task["status"],
            "progress": task["progress"],
            "result": task.get("result", {}),
            "created_at": task["created_at"],
            "credits_used": task["credits_used"],
        },
    }


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

@app.get("/static/reference.png")
async def serve_reference_image():
    """Раздаёт файл-заглушку эталона."""
    if os.path.exists(MOCK_IMAGE_PATH):
        return FileResponse(MOCK_IMAGE_PATH, media_type="image/png")
    raise HTTPException(status_code=404, detail="Image not found")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    logger.info("HEALTH CHECK | tasks=%d | taskIds=%s", len(_tasks), list(_tasks.keys()))
    return {"status": "ok", "tasks": len(_tasks)}
