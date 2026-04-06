#!/usr/bin/env python3
"""
Mock Kie.ai сервер для локальной разработки и тестирования.

Эмулирует API Kie.ai:
  - T2T: POST /gpt-5-2/v1/chat/completions
  - I2I: POST /api/v1/jobs/createTask (model: gpt-image-1.5, seedream, flux...)
  - I2V: POST /api/v1/jobs/createTask (model: sora-2-image-to-video...)
  - Статус: GET /api/v1/jobs/taskDetail/{task_id}

Запуск:
  uvicorn mock_kie_server:app --host 0.0.0.0 --port 8080 --reload
"""

import time
import uuid
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Mock Kie.ai Server", version="1.0.0")

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

# Виртуальное изображение-заглушка для I2I/I2V результатов
MOCK_IMAGE_URL = "https://via.placeholder.com/1024x1024/ffffff/cccccc?text=Mock+Reference+Image"

# Хранилище задач (in-memory, только для dev)
_tasks: dict = {}


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _check_auth(authorization: Optional[str]) -> None:
    """Проверяет Bearer токен. В mock — всегда пропускает если есть заголовок."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": 401, "msg": "You do not have access permissions"})


# ---------------------------------------------------------------------------
# T2T: Chat Completions
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]


@app.post("/gpt-5-2/v1/chat/completions")
async def chat_completions(req: ChatRequest, authorization: Optional[str] = Header(None)):
    """T2T — генерация промпта для эталона (OpenAI-совместимый формат)."""
    _check_auth(authorization)

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
                },
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

class TaskInput(BaseModel):
    prompt: str
    image_urls: Optional[list[str]] = []
    aspect_ratio: Optional[str] = None
    n_frames: Optional[str] = None
    remove_watermark: Optional[bool] = None
    upload_method: Optional[str] = None


class CreateTaskRequest(BaseModel):
    model: str
    callBackUrl: Optional[str] = None
    input: TaskInput


@app.post("/api/v1/jobs/createTask")
async def create_task(req: CreateTaskRequest, authorization: Optional[str] = Header(None)):
    """I2I или I2V — создание задачи. Возвращает task_id."""
    _check_auth(authorization)

    task_id = f"task_{uuid.uuid4().hex[:16]}"

    _tasks[task_id] = {
        "task_id": task_id,
        "model": req.model,
        "status": "completed",  # Mock: сразу completed
        "progress": 100,
        "input": req.input.model_dump(),
        "result": {
            "image_url": MOCK_IMAGE_URL,
        },
        "created_at": int(time.time()),
        "credits_used": 1,
    }

    return {
        "code": 200,
        "data": {
            "task_id": task_id,
        },
    }


# ---------------------------------------------------------------------------
# Task Detail (polling)
# ---------------------------------------------------------------------------

@app.get("/api/v1/jobs/taskDetail/{task_id}")
async def task_detail(task_id: str, authorization: Optional[str] = Header(None)):
    """Статус задачи."""
    _check_auth(authorization)

    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": 404, "msg": "Task not found"})

    return {
        "code": 200,
        "data": {
            "task_id": task["task_id"],
            "model": task["model"],
            "status": task["status"],
            "progress": task["progress"],
            "result": task["result"],
            "created_at": task["created_at"],
            "credits_used": task["credits_used"],
        },
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "tasks": len(_tasks)}
