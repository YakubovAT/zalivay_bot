"""
web/app.py

Веб-интерфейс для просмотра медиафайлов и управления промптами.
Авторизация через Telegram Login Widget.

Запуск:
    uvicorn web.app:app --host 0.0.0.0 --port 8080

Переменные окружения (берутся из .env):
    BOT_TOKEN        — токен бота (для проверки подписи Telegram auth)
    BOT_USERNAME     — username бота без @ (для виджета входа)
    WEB_SECRET       — секрет для подписи сессионных куков
    MEDIA_ROOT       — путь к папке media (по умолчанию ./media)
    DATABASE_URL     — строка подключения к PostgreSQL
    ADMIN_USER_IDS   — Telegram user_id через запятую (владелец + поддержка)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Any

import asyncpg
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
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/zalivai_db")
THUMB_SIZE   = (400, 400)

# Поля, которые разрешено редактировать через веб
EDITABLE_REFERENCE_FIELDS = {
    "product_name", "product_color", "product_material",
    "product_description", "category",
}

# Telegram user_id администраторов (владелец + тех. поддержка)
_raw_admins = os.getenv("ADMIN_USER_IDS", "")
ADMIN_USER_IDS: set[int] = {
    int(x.strip()) for x in _raw_admins.split(",") if x.strip().isdigit()
}

# list_key'и у которых есть поле value2 (показываем вторую колонку в UI)
LIST_KEYS_WITH_VALUE2 = {
    "video_locations", "video_bottom_items", "video_top_items",
}

_db_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db_pool
    _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    yield
    if _db_pool:
        await _db_pool.close()


app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


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
        if time.time() - int(ts_str) > 86400 * 30:
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
            if f.name.startswith(".thumb_"):
                continue
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


def _find_wb_original(user_id: int, articul: str) -> str | None:
    """Возвращает путь (относительно MEDIA_ROOT) к первому оригинальному фото WB."""
    wb_dir = MEDIA_ROOT / str(user_id) / "WB" / articul
    if not wb_dir.exists():
        return None
    PHOTO_EXT = {".png", ".jpg", ".jpeg", ".webp"}
    candidates = sorted(
        [f for f in wb_dir.iterdir() if f.suffix.lower() in PHOTO_EXT],
        key=lambda f: f.name,
    )
    if not candidates:
        return None
    return str(candidates[0].relative_to(MEDIA_ROOT))


def _db_path_to_serve_path(file_path: str | None) -> str | None:
    """
    Конвертирует путь из БД (media/{user_id}/...) в путь для /files/ (без media/).
    """
    if not file_path:
        return None
    p = file_path.lstrip("/")
    if p.startswith("media/"):
        p = p[len("media/"):]
    return p


# ---------------------------------------------------------------------------
# Утилиты авторизации — admin
# ---------------------------------------------------------------------------

def _is_admin(session: str | None) -> bool:
    user = _get_current_user(session)
    if not user:
        return False
    return user["user_id"] in ADMIN_USER_IDS


def _require_admin(session: str | None) -> dict:
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user["user_id"] not in ADMIN_USER_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ---------------------------------------------------------------------------
# Роуты — основные
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, session: str | None = Cookie(default=None)):
    user = _get_current_user(session)
    is_admin = bool(user and user["user_id"] in ADMIN_USER_IDS)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user":         user,
            "bot_username": BOT_USERNAME,
            "is_admin":     is_admin,
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


# ---------------------------------------------------------------------------
# Роуты — эталоны
# ---------------------------------------------------------------------------

@app.get("/api/references")
async def list_references(session: str | None = Cookie(default=None)):
    """Возвращает активные (не удалённые) эталоны пользователя."""
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = user["user_id"]

    rows = await _db_pool.fetch(
        """
        SELECT
            ar.id,
            ar.articul,
            ar.reference_number,
            ar.file_path,
            ar.category,
            ar.product_description,
            ar.product_name,
            ar.product_color,
            ar.product_material,
            ar.created_at,
            a.name     AS article_name,
            a.color    AS article_color,
            a.material AS article_material
        FROM article_references ar
        LEFT JOIN articles a
            ON a.user_id = ar.user_id AND a.article_code = ar.articul
        WHERE ar.user_id = $1 AND ar.is_active = TRUE AND ar.deleted_at IS NULL
        ORDER BY ar.created_at DESC
        """,
        user_id,
    )

    result = []
    for row in rows:
        result.append({
            "id":                  row["id"],
            "articul":             row["articul"],
            "reference_number":    row["reference_number"],
            "ref_path":            _db_path_to_serve_path(row["file_path"]),
            "orig_path":           _find_wb_original(user_id, row["articul"]),
            "category":            row["category"] or "",
            "product_description": row["product_description"] or "",
            "product_name":        row["product_name"] or row["article_name"] or "",
            "product_color":       row["product_color"] or row["article_color"] or "",
            "product_material":    row["product_material"] or row["article_material"] or "",
            "created_at":          row["created_at"].isoformat() if row["created_at"] else None,
        })

    return {"references": result}


@app.delete("/api/references/{ref_id}")
async def delete_reference(ref_id: int, session: str | None = Cookie(default=None)):
    """Перемещает эталон в корзину (soft delete, 30 дней до полного удаления)."""
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await _db_pool.execute(
        """
        UPDATE article_references
        SET deleted_at = NOW()
        WHERE user_id = $1 AND id = $2 AND is_active = TRUE AND deleted_at IS NULL
        """,
        user["user_id"], ref_id,
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Reference not found")

    return {"ok": True}


@app.get("/api/trash")
async def list_trash(session: str | None = Cookie(default=None)):
    """Возвращает эталоны из корзины. Попутно финализирует просроченные (>30 дней)."""
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = user["user_id"]

    # Финализируем просроченные — переводим в is_active = FALSE
    await _db_pool.execute(
        """
        UPDATE article_references
        SET is_active = FALSE
        WHERE user_id = $1
          AND deleted_at IS NOT NULL
          AND deleted_at < NOW() - INTERVAL '30 days'
        """,
        user_id,
    )

    rows = await _db_pool.fetch(
        """
        SELECT
            ar.id,
            ar.articul,
            ar.reference_number,
            ar.file_path,
            ar.product_name,
            ar.product_color,
            ar.deleted_at,
            a.name AS article_name
        FROM article_references ar
        LEFT JOIN articles a
            ON a.user_id = ar.user_id AND a.article_code = ar.articul
        WHERE ar.user_id = $1 AND ar.is_active = TRUE AND ar.deleted_at IS NOT NULL
        ORDER BY ar.deleted_at DESC
        """,
        user_id,
    )

    result = []
    for row in rows:
        deleted_at = row["deleted_at"]
        days_left  = 30 - (time.time() - deleted_at.timestamp()) / 86400
        result.append({
            "id":               row["id"],
            "articul":          row["articul"],
            "reference_number": row["reference_number"],
            "ref_path":         _db_path_to_serve_path(row["file_path"]),
            "orig_path":        _find_wb_original(user_id, row["articul"]),
            "product_name":     row["product_name"] or row["article_name"] or "",
            "deleted_at":       deleted_at.isoformat(),
            "days_left":        max(0, int(days_left)),
        })

    return {"trash": result}


@app.post("/api/trash/{ref_id}/restore")
async def restore_reference(ref_id: int, session: str | None = Cookie(default=None)):
    """Восстанавливает эталон из корзины."""
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await _db_pool.execute(
        """
        UPDATE article_references
        SET deleted_at = NULL
        WHERE user_id = $1 AND id = $2 AND is_active = TRUE AND deleted_at IS NOT NULL
        """,
        user["user_id"], ref_id,
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Reference not found in trash")

    return {"ok": True}


@app.delete("/api/trash/{ref_id}")
async def purge_reference(ref_id: int, session: str | None = Cookie(default=None)):
    """Окончательно удаляет эталон из корзины (необратимо)."""
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await _db_pool.execute(
        """
        UPDATE article_references
        SET is_active = FALSE
        WHERE user_id = $1 AND id = $2 AND is_active = TRUE AND deleted_at IS NOT NULL
        """,
        user["user_id"], ref_id,
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Reference not found in trash")

    return {"ok": True}


@app.patch("/api/references/{ref_id}")
async def update_reference(
    ref_id: int,
    request: Request,
    session: str | None = Cookie(default=None),
):
    """Обновляет редактируемые поля эталона. Доступ только владельцу."""
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    body: dict[str, Any] = await request.json()

    # Отфильтровываем только разрешённые поля
    updates = {k: v for k, v in body.items() if k in EDITABLE_REFERENCE_FIELDS}
    if not updates:
        raise HTTPException(status_code=400, detail="No editable fields provided")

    # Строим SET-часть запроса динамически
    set_clauses = ", ".join(f"{col} = ${i+3}" for i, col in enumerate(updates))
    values = [user["user_id"], ref_id, *updates.values()]

    result = await _db_pool.execute(
        f"""
        UPDATE article_references
        SET {set_clauses}
        WHERE user_id = $1 AND id = $2 AND is_active = TRUE
        """,
        *values,
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Reference not found")

    return {"ok": True}


# ---------------------------------------------------------------------------
# Роуты — admin (промпты)
# ---------------------------------------------------------------------------

@app.get("/api/admin/prompts")
async def admin_get_prompts(session: str | None = Cookie(default=None)):
    """Возвращает все шаблоны и элементы списков для admin-панели."""
    _require_admin(session)

    template_rows = await _db_pool.fetch(
        "SELECT key, template, description, updated_at FROM prompt_templates ORDER BY key"
    )
    item_rows = await _db_pool.fetch(
        """
        SELECT id, list_key, value, value2, is_active, sort_order, updated_at
        FROM prompt_list_items
        ORDER BY list_key, sort_order, id
        """
    )

    templates_out = [
        {
            "key":         r["key"],
            "template":    r["template"],
            "description": r["description"] or "",
            "updated_at":  r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in template_rows
    ]

    # Группируем элементы по list_key
    lists_out: dict[str, list] = {}
    for r in item_rows:
        lk = r["list_key"]
        lists_out.setdefault(lk, []).append({
            "id":         r["id"],
            "value":      r["value"],
            "value2":     r["value2"] or "",
            "is_active":  r["is_active"],
            "sort_order": r["sort_order"],
        })

    return {
        "templates":         templates_out,
        "lists":             lists_out,
        "keys_with_value2":  list(LIST_KEYS_WITH_VALUE2),
    }


@app.patch("/api/admin/prompts/templates/{key}")
async def admin_update_template(
    key: str,
    request: Request,
    session: str | None = Cookie(default=None),
):
    """Обновляет текст шаблона промпта."""
    _require_admin(session)
    body = await request.json()
    template = body.get("template", "").strip()
    if not template:
        raise HTTPException(status_code=400, detail="template is required")

    result = await _db_pool.execute(
        "UPDATE prompt_templates SET template = $1, updated_at = NOW() WHERE key = $2",
        template, key,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}


@app.post("/api/admin/prompts/lists/items")
async def admin_add_list_item(
    request: Request,
    session: str | None = Cookie(default=None),
):
    """Добавляет новый элемент в список промптов."""
    _require_admin(session)
    body = await request.json()
    list_key   = body.get("list_key", "").strip()
    value      = body.get("value", "").strip()
    value2     = body.get("value2", "").strip() or None
    sort_order = int(body.get("sort_order", 0))

    if not list_key or not value:
        raise HTTPException(status_code=400, detail="list_key and value are required")

    row = await _db_pool.fetchrow(
        """
        INSERT INTO prompt_list_items (list_key, value, value2, sort_order)
        VALUES ($1, $2, $3, $4) RETURNING id
        """,
        list_key, value, value2, sort_order,
    )
    return {"ok": True, "id": row["id"]}


@app.patch("/api/admin/prompts/lists/items/{item_id}")
async def admin_update_list_item(
    item_id: int,
    request: Request,
    session: str | None = Cookie(default=None),
):
    """Обновляет value, value2, is_active или sort_order элемента списка."""
    _require_admin(session)
    body = await request.json()

    allowed = {"value", "value2", "is_active", "sort_order"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    set_clauses = ", ".join(f"{col} = ${i+2}" for i, col in enumerate(updates))
    values = [item_id, *updates.values()]

    result = await _db_pool.execute(
        f"UPDATE prompt_list_items SET {set_clauses}, updated_at = NOW() WHERE id = $1",
        *values,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Item not found")
    return {"ok": True}


@app.delete("/api/admin/prompts/lists/items/{item_id}")
async def admin_delete_list_item(
    item_id: int,
    session: str | None = Cookie(default=None),
):
    """Полностью удаляет элемент списка."""
    _require_admin(session)
    result = await _db_pool.execute(
        "DELETE FROM prompt_list_items WHERE id = $1", item_id
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Item not found")
    return {"ok": True}


@app.post("/api/admin/prompts/invalidate")
async def admin_invalidate_prompts(session: str | None = Cookie(default=None)):
    """Сбрасывает кэш prompt_store в текущем процессе.
    Бот подхватит изменения автоматически через TTL (≤10 сек).
    """
    _require_admin(session)
    from services import prompt_store
    await prompt_store.invalidate()
    return {"ok": True, "ttl_seconds": 10}


# ---------------------------------------------------------------------------
# Раздача файлов
# ---------------------------------------------------------------------------

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

    parts = path.split("/")
    if not parts or parts[0] != str(user["user_id"]):
        raise HTTPException(status_code=403, detail="Access denied")

    file_path = MEDIA_ROOT / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)
