# Удаление медиафайлов — дизайн

**Дата:** 2026-04-25

---

## Цель

Добавить мягкое удаление медиафайлов из вкладок «Медиафайлы» и «Пинтерест», объединить корзину эталонов и медиафайлов в один смешанный список.

---

## Поведение при удалении

Кнопка 🗑 на карточке (рядом с ⓘ). Показывается только если у файла есть `media_file_id`.

| Откуда | Состояние файла | Действие |
|--------|----------------|----------|
| Медиафайлы или Пинтерест | нет водяного знака | `media_files.deleted_at = NOW()` |
| Пинтерест | есть водяной знак (`watermarked_path IS NOT NULL`) | удалить watermark-файл с диска + `watermarked_path = NULL`; оригинал остаётся |

Файлы без записи в `media_files` (legacy, без `media_file_id`) — кнопку 🗑 не показываем.

Восстановление: `deleted_at = NULL`. Жёсткое удаление из корзины: файл с диска + строка из БД.

---

## БД

```sql
ALTER TABLE media_files
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL;
```

`GET /api/files` и `GET /api/pinterest/files` фильтруют `WHERE deleted_at IS NULL`.

---

## Backend — новые роуты

| Метод | Путь | Описание |
|-------|------|----------|
| `DELETE` | `/api/media/{id}` | Soft delete: `deleted_at = NOW()` |
| `DELETE` | `/api/media/{id}/watermark` | Удалить только watermark: файл с диска + `watermarked_path = NULL` |
| `POST` | `/api/trash/media/{id}/restore` | Восстановить: `deleted_at = NULL` |
| `DELETE` | `/api/trash/media/{id}` | Жёсткое удаление: файл с диска + строка из БД |

### Изменения в существующих роутах

**`GET /api/files`** — добавить `media_file_id` в ответ через LEFT JOIN с `media_files`:
```sql
LEFT JOIN media_files mf
  ON mf.file_path = gt.file_path AND mf.user_id = gt.user_id AND mf.deleted_at IS NULL
```
Поле `media_file_id: mf.id | null` в каждом объекте файла.

**`GET /api/pinterest/files`** — добавить `id` в SELECT, добавить `AND deleted_at IS NULL` в WHERE. Поле `media_file_id` в ответе.

**`GET /api/trash`** — расширить: возвращает и эталоны, и медиафайлы.

Структура ответа:
```json
{
  "trash": [
    {
      "kind": "reference",
      "id": 1,
      "articul": "SKU123",
      "product_name": "Название",
      "ref_path": "123/references/...",
      "days_left": 25,
      "deleted_at": "2026-04-20T10:00:00"
    },
    {
      "kind": "media",
      "id": 42,
      "articul": "SKU456",
      "file_type": "photo",
      "path": "123/generated/SKU456/photo_SKU456_1.png",
      "days_left": 28,
      "deleted_at": "2026-04-22T14:00:00"
    }
  ]
}
```

Сортировка: `deleted_at DESC` (оба типа вместе).
Авто-финализация (>30 дней): распространяется и на медиафайлы (файл с диска + `is_active = FALSE` или удаление строки).

---

## Frontend

### Карточки (Медиафайлы и Пинтерест)

Кнопка 🗑 добавляется в `cardHTML` и `pintCardHTML` рядом с ⓘ, только если `f.media_file_id`:

```html
<button class="card-del-btn" onclick="deleteMediaFile(event, f)" title="Удалить">🗑</button>
```

CSS: позиционируется в левом нижнем углу карточки.

**`deleteMediaFile(e, f)`** — логика:
- Если вкладка Пинтерест И `f.has_watermark` → `DELETE /api/media/{id}/watermark` → обновить карточку (убрать watermark-версию, перезагрузить)
- Иначе → подтверждение → `DELETE /api/media/{id}` → карточка исчезает, показать вкладку Корзина

### Вкладка «Корзина» — смешанный список

Список отсортирован по `deleted_at DESC`. Каждый элемент:

**Эталон** (как сейчас, без изменений визуала):
- Бейдж «Эталон»
- Фото эталона + артикул + название + «удалится через N дн.»
- Кнопки: Восстановить · ✕

**Медиафайл**:
- Бейдж «Фото» или «Видео»
- Превью (`/thumb/`) + артикул + «удалится через N дн.»
- Кнопки: Восстановить · ✕

Вкладка «Корзина» показывается если в ответе `trash.length > 0` (любого типа).

---

## Затронутые файлы

| Файл | Изменение |
|------|-----------|
| `database/schema.sql` | `ALTER TABLE media_files ADD COLUMN deleted_at` |
| `web/app.py` | 4 новых роута; изменения в `list_files`, `pinterest_files`, `list_trash` |
| `web/templates/index.html` | Кнопка 🗑 на карточках; обновление рендера корзины |

---

## Что не входит

- Мультиселект и массовое удаление (следующая фаза)
- Удаление оригинального файла при удалении watermark (только помечаем, файл остаётся)
