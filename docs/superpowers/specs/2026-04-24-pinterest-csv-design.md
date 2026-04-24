# Pinterest CSV Generator — Design Spec
**Date:** 2026-04-24

---

## Цель

Универсальный сервис генерации CSV-файла для загрузки медиаконтента в Pinterest.
Вызывается как из Telegram-бота, так и из веб-панели.

---

## Новые таблицы БД

### `media_files`

Центральный реестр всех сгенерированных медиафайлов. Каждый файл — самостоятельная сущность с историей использования.

```sql
CREATE TABLE media_files (
    id                    SERIAL PRIMARY KEY,
    user_id               BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    article_code          TEXT NOT NULL,
    task_id               INTEGER REFERENCES generation_tasks(id) ON DELETE SET NULL,
    file_path             TEXT NOT NULL,        -- локальный путь
    result_url            TEXT,                 -- CDN URL (kie.ai или наш сервер)
    file_type             TEXT NOT NULL CHECK (file_type IN ('photo', 'video')),
    pinterest_exported_at TIMESTAMPTZ NULL,     -- NULL = ещё не экспортировался
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Заполняется автоматически при завершении задачи в `complete_job_task` и `complete_video_job_task` (в `db.py`).

Фильтр необработанных: `WHERE user_id=$1 AND article_code=$2 AND pinterest_exported_at IS NULL`.

### `pinterest_settings`

Настройки Pinterest на двух уровнях: артикул и пользователь.

```sql
CREATE TABLE pinterest_settings (
    id            SERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    article_code  TEXT NULL,           -- NULL = настройки уровня пользователя
    board         TEXT NULL,
    link_template TEXT NULL,           -- шаблон ссылки, напр. "https://t.me/shop?item={article}"
    hashtags      TEXT[] NULL          -- массив хештегов без #
);

-- В PostgreSQL UNIQUE с NULL не работает как ожидается (NULL != NULL),
-- поэтому два частичных индекса вместо одного UNIQUE constraint:
CREATE UNIQUE INDEX idx_pinterest_settings_user_default
    ON pinterest_settings (user_id) WHERE article_code IS NULL;
CREATE UNIQUE INDEX idx_pinterest_settings_user_article
    ON pinterest_settings (user_id, article_code) WHERE article_code IS NOT NULL;
```

**Fallback при генерации (для каждого поля отдельно):**
1. Запись с `article_code = $article` → берём значение
2. Запись с `article_code IS NULL` (уровень пользователя) → берём значение
3. Пустая строка / NULL

---

## Сервис `services/pinterest_csv_generator.py`

### Публичный интерфейс

```python
async def generate_pinterest_csv(
    user_id: int,
    article_codes: list[str],
    rows_limit: int = 200,
    output_format: str = "csv",   # "csv" | "json" | "rows"
) -> dict:
    ...
```

**Возвращает:**
```python
{
    "batch_id": str,              # uuid[:8]
    "content": str | list,        # CSV-строка, JSON или list[dict]
    "processed_files": list[int], # id из media_files
    "stats": {
        "count": int,
        "skipped": int,
        "errors": list[str],
    }
}
```

### Логика (шаги)

**Шаг 1 — Сбор данных:**
- Для каждого артикула из `articles` взять `name`, `color`
- Загрузить настройки Pinterest из `pinterest_settings` (с fallback)
- Получить необработанные файлы из `media_files` (`pinterest_exported_at IS NULL`)
- Отфильтровать: только изображения или видео (по `file_type`)

**Шаг 2 — Генерация строк (до `rows_limit`):**

| Поле CSV | Правило |
|---|---|
| `Title` | `{color_first} {name_word1} {random_prefix} {article} {i:04d}` |
| `Media URL` | `result_url` из `media_files` |
| `Pinterest board` | `board` из настроек (может быть пусто) |
| `Thumbnail` | случайно: `"0:01"`, `"0:02"`, `"0:03"` или `""` (25%) |
| `Description` | `"{name} {color}. {случайная фраза из пула}" + 5 случайных хештегов из настроек` |
| `Link` | `link_template` с подстановкой `{article}`, `{index}` (пусто если не задан) |
| `Publish date` | `now + 1 day` + накопительный рандомный шаг 30–120 мин, ISO 8601 |
| `Keywords` | пусто |

Уникальность `Title` в батче гарантируется через `set` уже использованных значений.

**Шаг 3 — Пост-обработка:**
- `UPDATE media_files SET pinterest_exported_at = NOW() WHERE id = ANY($exported_ids)`
- Вернуть результат в запрошенном формате

**CSV кодировка:** `utf-8-sig` (совместимость с Excel)

### Обработка ошибок

| Ситуация | Поведение |
|---|---|
| Артикул не найден в `articles` | лог + пропуск, добавить в `stats.errors` |
| Нет необработанных файлов для артикула | пропуск, отразить в `stats.skipped` |
| Ошибка при генерации строки | лог + пропуск файла, батч не прерывается |
| `rows_limit` достигнут | остановка, остальные файлы не трогаем |

---

## Интеграция

### db.py — новые функции

```python
# Регистрация файла при завершении задачи
async def register_media_file(user_id, article_code, task_id, file_path, result_url, file_type) -> int

# Файлы для Pinterest (необработанные)
async def get_unexported_media_files(user_id, article_code) -> list[Record]

# Пометить как экспортированные
async def mark_pinterest_exported(file_ids: list[int]) -> None

# Pinterest настройки
async def get_pinterest_settings(user_id, article_code) -> dict  # уже с fallback
async def save_pinterest_settings(user_id, article_code, board, link_template, hashtags) -> None
```

`complete_job_task` и `complete_video_job_task` дополняются вызовом `register_media_file`.

### Telegram-бот

Новый handler (кнопка или команда `/pinterest`):
1. Показать список артикулов пользователя
2. Пользователь выбирает артикулы
3. Вызов `generate_pinterest_csv(user_id, articles)`
4. Отправить CSV-файл документом

### Веб-панель (`web/app.py`)

Новый эндпоинт `POST /api/pinterest/generate`:
```json
{ "user_id": 123, "articles": ["38959282"], "rows_limit": 200 }
```
Возвращает CSV-файл или JSON.

---

## Что НЕ входит в этот этап

- UI для редактирования `pinterest_settings` в боте/вебе (отдельная задача)
- Прямая загрузка в Pinterest API (только CSV-файл)
- Аналитика по батчам

---

## Структура файлов

```
database/
  schema.sql                        # + media_files, pinterest_settings
  db.py                             # + новые функции
services/
  pinterest_csv_generator.py        # новый сервис
handlers/flows/
  pinterest.py                      # новый handler для бота
web/app.py                          # + новый эндпоинт
```
