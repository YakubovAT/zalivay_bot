---
name: Database
description: Creates and maintains database schema and functions for Zalivai Bot. Use this agent when you need to create schema.sql, db.py, or any database-related code.
tools: [read, write, edit]
---

# skill_db.md — Инструкция для субагента БД

## Цель
Создать модуль базы данных для Zalivai Bot:
- `database/schema.sql` — структура таблиц
- `database/db.py` — функции для работы с БД
- `database/__init__.py` — экспорты

## Входные данные
Читай файл `docs/db_schema.md` — там полная схема БД с описанием всех таблиц, полей и связей.

---

## Технологии
- **PostgreSQL** — база данных
- **asyncpg** — асинхронный драйвер
- **Python 3.11+** — язык

---

## Правила schema.sql

1. Все таблицы создавать через `CREATE TABLE IF NOT EXISTS`
2. Все внешние ключи через `REFERENCES` с `ON DELETE CASCADE`
3. Все индексы через `CREATE INDEX IF NOT EXISTS`
4. Порядок создания таблиц — от независимых к зависимым:
   - сначала: `users`, `variables`, `prompts`, `messages`
   - потом: `user_sources`, `articles`
   - потом: `media_files`, `jobs`
   - потом: `tasks`

### Пример таблицы
```sql
CREATE TABLE IF NOT EXISTS users (
    user_id     BIGINT PRIMARY KEY,
    username    TEXT,
    balance     INT NOT NULL DEFAULT 0,
    is_onboarded BOOLEAN NOT NULL DEFAULT FALSE,
    referral_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Правила db.py

1. Один пул соединений на всё приложение (`asyncpg.Pool`)
2. Все функции `async`
3. Каждая функция делает одно действие
4. Названия функций: `get_`, `save_`, `update_`, `delete_`
5. Всегда возвращать конкретный тип — не `None` там где ожидается результат
6. Обработка ошибок — только логировать, не глотать

### Инициализация пула
```python
import asyncpg
from config import DATABASE_URL

_pool: asyncpg.Pool | None = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool

async def init_db():
    pool = await get_pool()
    with open("database/schema.sql", "r", encoding="utf-8") as f:
        schema = f.read()
    async with pool.acquire() as conn:
        await conn.execute(schema)
```

### Пример функции get_
```python
async def get_user(user_id: int) -> asyncpg.Record | None:
    pool = await get_pool()
    return await pool.fetchrow(
        "SELECT * FROM users WHERE user_id = $1",
        user_id
    )
```

### Пример функции save_
```python
async def save_user(user_id: int, username: str | None) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO users (user_id, username)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
        """,
        user_id, username
    )
```

### Пример функции update_
```python
async def update_user_onboarded(user_id: int) -> None:
    pool = await get_pool()
    await pool.execute(
        "UPDATE users SET is_onboarded = TRUE WHERE user_id = $1",
        user_id
    )
```

---

## Правила __init__.py

Экспортировать только публичные функции которые используются в других модулях.

```python
from .db import (
    get_pool,
    init_db,
    get_user,
    save_user,
    update_user_onboarded,
    # ... остальные функции
)

__all__ = [
    "get_pool",
    "init_db",
    "get_user",
    "save_user",
    "update_user_onboarded",
]
```

---

## Структура файлов

```
database/
  __init__.py   — экспорты
  db.py         — все функции
  schema.sql    — структура таблиц
```

---

## Функции которые нужно реализовать

### users
- `get_user(user_id)` → Record | None
- `save_user(user_id, username)` → None
- `update_user_onboarded(user_id)` → None
- `update_user_balance(user_id, amount)` → int (новый баланс)

### user_sources
- `save_user_source(user_id, utm_source, utm_medium, utm_campaign)` → None

### articles
- `get_article(user_id, article_code)` → Record | None
- `save_article(user_id, article_code, marketplace, raw_json)` → int (id)
- `update_article_status(article_id, status)` → None
- `update_article_ai_json(article_id, ai_json)` → None
- `update_article_reference_path(article_id, reference_path)` → None

### media_files
- `save_media_file(user_id, article_code, file_path, marked_path, file_type, title_content, description_content)` → int (id)
- `get_media_files(user_id, article_code)` → list[Record]

### jobs
- `create_job(user_id, article_code, type, count, cost, screen_msg_id)` → int (id)
- `update_job_status(job_id, status)` → None
- `get_job(job_id)` → Record | None

### tasks
- `create_task(job_id, user_id, prompt)` → int (id)
- `update_task_status(task_id, status, result_url, error)` → None
- `get_pending_tasks(limit)` → list[Record]
- `get_job_tasks(job_id)` → list[Record]

### variables
- `get_variables(platform, category)` → list[Record]

### prompts
- `get_prompt(type, name)` → str | None

### messages
- `get_message(key)` → str | None

---

## Чего НЕ делать

- Не хранить бизнес-логику в db.py — только SQL
- Не делать JOIN'ы там где можно два простых запроса
- Не создавать поля "на будущее"
- Не дублировать функции
- Не использовать `SELECT *` в продакшн функциях — указывать конкретные поля
