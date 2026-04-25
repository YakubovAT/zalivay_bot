# Вкладка «Пинтерест» — дизайн

**Дата:** 2026-04-25

---

## Цель

Добавить пользователю вкладку «Пинтерест» в веб-интерфейс (`media.zaliv.ai`), отображающую медиафайлы из таблицы `media_files` в том же стиле, что и вкладка «Медиафайлы».

---

## Архитектура

### Новый API-эндпоинт: `GET /api/pinterest/files`

- Читает из таблицы `media_files` (не сканирует ФС)
- Авторизация: требует сессию (как все остальные эндпоинты)
- Возвращает массив объектов:

```json
[
  {
    "path": "123/generated/SKU/photo_SKU_42.png",
    "articul": "SKU123",
    "type": "photo",
    "has_watermark": true,
    "export_count": 3,
    "exported_at": "2026-04-20T10:00:00",
    "created_at": "2026-04-15T08:00:00"
  }
]
```

**Логика пути:**
- Если `watermarked_path IS NOT NULL` — используется `watermarked_path`
- Иначе — `file_path`
- Оба поля обрезаются от префикса `media/` через существующую функцию `_db_path_to_serve_path()`

**SQL:**
```sql
SELECT id, article_code, file_type, file_path, watermarked_path,
       pinterest_export_count, pinterest_exported_at, created_at
FROM media_files
WHERE user_id = $1 AND is_active = TRUE
ORDER BY created_at DESC
```

### SPA-маршрут

Добавить `/pinterest` в `_SPA_PATHS` в `web/app.py`.

---

## Фронтенд

### Вкладка в навбаре

```html
<button class="tab-btn" data-tab="pinterest" onclick="switchTab('pinterest')">Пинтерест</button>
```

Размещается после «Корзина», перед «Администратор».

### Контейнер вкладки

```html
<div id="tab-pinterest" class="tab-content" style="display:none"></div>
```

### Сетка карточек

Идентична вкладке «Медиафайлы»:
- `grid-template-columns: repeat(auto-fill, minmax(200px, 1fr))`
- Превью через `/thumb/{path}` — для фото напрямую, для видео — canvas-фрейм через `_extractFrame()`
- Клик на карточку — тот же лайтбокс
- Кнопка ⓘ в углу — info drawer

### Фильтры

Те же два фильтра что в «Медиафайлы»:
- По типу: Все / Фото / Видео
- По артикулу: выпадающий список уникальных артикулов

### Info drawer

Показывает Pinterest-специфичные поля:
| Поле | Значение |
|------|----------|
| Артикул | `articul` |
| Тип | Фото / Видео |
| Водяной знак | ✓ Нанесён / ✗ Нет |
| Экспортов в Pinterest | N (или «Не экспортировался» если 0) |
| Последний экспорт | дата или «—» |
| Дата создания | дата |

---

## Данные

| Источник | Поле |
|----------|------|
| `media_files.file_path` или `watermarked_path` | путь к файлу для превью |
| `media_files.article_code` | артикул |
| `media_files.file_type` | тип (`photo` / `video`) |
| `media_files.watermarked_path IS NOT NULL` | флаг водяного знака |
| `media_files.pinterest_export_count` | количество экспортов |
| `media_files.pinterest_exported_at` | дата последнего экспорта |
| `media_files.created_at` | дата создания |

---

## Затронутые файлы

| Файл | Изменение |
|------|-----------|
| `web/app.py` | Новый эндпоинт `GET /api/pinterest/files`, добавить `/pinterest` в `_SPA_PATHS` |
| `web/templates/index.html` | Новая вкладка, контейнер, JS-функции загрузки/рендера, фильтры, info drawer |

---

## Что не входит в этот этап

- Генерация Pinterest CSV из веба (уже есть `POST /api/pinterest/generate`, но UI не реализован)
- Нанесение водяного знака из веба
- Настройки Pinterest (board, hashtags, link_template)
