"""
web/app.py

Простой веб-интерфейс для просмотра медиафайлов пользователя.
Авторизация через Telegram Login Widget.

Запуск:
    uvicorn web.app:app --host 0.0.0.0 --port 8080

Переменные окружения (берутся из .env):
    BOT_TOKEN      — токен бота (для проверки подписи Telegram auth)
    BOT_USERNAME   — username бота без @ (для виджета входа)
    WEB_SECRET     — секрет для подписи сессионных куков (придумайте любой)
    MEDIA_ROOT     — путь к папке media (по умолчанию ./media)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from PIL import Image

load_dotenv()

BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "ZalivaiBot")
WEB_SECRET   = os.getenv("WEB_SECRET", "change-me-in-production")
MEDIA_ROOT   = Path(os.getenv("MEDIA_ROOT", "media"))
THUMB_SIZE   = (400, 400)   # размер превью в пикселях

app = FastAPI(docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Раздаём media-файлы только авторизованным (через /files/ endpoint ниже)
# Не монтируем StaticFiles напрямую на /media


# ---------------------------------------------------------------------------
# Утилиты авторизации
# ---------------------------------------------------------------------------

def _verify_telegram_auth(data: dict) -> bool:
    """Проверяет подпись данных от Telegram Login Widget."""
    received_hash = data.get("hash", "")
    fields = {k: v for k, v in data.items() if k != "hash"}
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return False
    # Данные не старше 1 суток
    auth_date = int(fields.get("auth_date", 0))
    if time.time() - auth_date > 86400:
        return False
    return True


def _make_session(user_id: int, first_name: str) -> str:
    ts = int(time.time())
    payload = f"{user_id}:{first_name}:{ts}"
    sig = hmac.new(WEB_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{payload}:{sig}"


def _parse_session(token: str) -> dict | None:
    try:
        *parts, sig = token.split(":")
        payload = ":".join(parts)
        expected = hmac.new(WEB_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(expected, sig):
            return None
        user_id_str, first_name, ts_str = parts[0], parts[1], parts[2]
        if time.time() - int(ts_str) > 86400 * 30:  # 30 дней
            return None
        return {"user_id": int(user_id_str), "first_name": first_name}
    except Exception:
        return None


def _get_current_user(session: str | None) -> dict | None:
    if not session:
        return None
    return _parse_session(session)


# ---------------------------------------------------------------------------
# Утилиты файлов
# ---------------------------------------------------------------------------

def _list_user_files(user_id: int) -> list[dict]:
    """Сканирует media/{user_id}/generated/ и возвращает список файлов."""
    gen_dir = MEDIA_ROOT / str(user_id) / "generated"
    if not gen_dir.exists():
        return []

    PHOTO_EXT = {".png", ".jpg", ".jpeg", ".webp"}
    VIDEO_EXT = {".mp4", ".mov", ".webm", ".avi"}

    files = []
    for articul_dir in sorted(gen_dir.iterdir()):
        if not articul_dir.is_dir():
            continue
        articul = articul_dir.name
        for f in articul_dir.iterdir():
            ext = f.suffix.lower()
            if ext in PHOTO_EXT:
                ftype = "photo"
            elif ext in VIDEO_EXT:
                ftype = "video"
            else:
                continue
            files.append({
                "path": str(f.relative_to(MEDIA_ROOT)),
                "articul": articul,
                "type": ftype,
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
            })

    return sorted(files, key=lambda x: x["mtime"], reverse=True)


# ---------------------------------------------------------------------------
# Роуты
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, session: str | None = Cookie(default=None)):
    user = _get_current_user(session)
    # Starlette 0.36+ / 1.0: request идёт первым аргументом
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "bot_username": BOT_USERNAME,
        },
    )


@app.post("/api/auth")
async def auth(request: Request):
    """Принимает данные от Telegram Login Widget, выдаёт сессионный куки."""
    data = await request.json()
    if not _verify_telegram_auth(dict(data)):
        raise HTTPException(status_code=403, detail="Invalid Telegram auth")

    user_id    = int(data["id"])
    first_name = data.get("first_name", "")
    token      = _make_session(user_id, first_name)

    resp = JSONResponse({"ok": True, "user_id": user_id})
    resp.set_cookie(
        key="session",
        value=token,
        max_age=86400 * 30,
        httponly=True,
        samesite="lax",
    )
    return resp


@app.post("/api/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    return resp


@app.get("/api/files")
async def list_files(session: str | None = Cookie(default=None)):
    """Возвращает список файлов текущего пользователя."""
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    files = _list_user_files(user["user_id"])
    articuls = sorted({f["articul"] for f in files})
    return {"files": files, "articuls": articuls}


@app.get("/thumb/{path:path}")
async def serve_thumb(path: str, session: str | None = Cookie(default=None)):
    """Отдаёт превью 400×400. Генерирует и кэширует рядом с оригиналом."""
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    parts = path.split("/")
    if not parts or parts[0] != str(user["user_id"]):
        raise HTTPException(status_code=403, detail="Access denied")

    orig = MEDIA_ROOT / path
    if not orig.exists() or not orig.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    thumb_path = orig.parent / f".thumb_{orig.stem}.jpg"

    if not thumb_path.exists() or thumb_path.stat().st_mtime < orig.stat().st_mtime:
        img = Image.open(orig).convert("RGB")
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        img.save(thumb_path, "JPEG", quality=80, optimize=True)

    return FileResponse(thumb_path, media_type="image/jpeg")


@app.get("/files/{path:path}")
async def serve_file(path: str, session: str | None = Cookie(default=None)):
    """Отдаёт файл только владельцу."""
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Путь начинается с user_id — проверяем что это его файл
    parts = path.split("/")
    if not parts or parts[0] != str(user["user_id"]):
        raise HTTPException(status_code=403, detail="Access denied")

    file_path = MEDIA_ROOT / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)
