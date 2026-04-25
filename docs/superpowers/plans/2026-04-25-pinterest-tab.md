# Pinterest Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить вкладку «Пинтерест» в веб-интерфейс — сетка карточек с медиафайлами из таблицы `media_files`, идентичная вкладке «Медиафайлы» по стилю.

**Architecture:** Новый эндпоинт `GET /api/pinterest/files` читает из таблицы `media_files` и возвращает данные с Pinterest-специфичными полями. Фронтенд добавляет вкладку с теми же CSS-классами, фильтрами, лайтбоксом и info drawer, что и «Медиафайлы», но с собственными переменными состояния.

**Tech Stack:** FastAPI + asyncpg (backend), vanilla JS + existing CSS classes (frontend), PostgreSQL `media_files` table.

---

## Файловая карта

| Файл | Изменение |
|------|-----------|
| `web/app.py` | Добавить `/pinterest` в `_SPA_PATHS`; новый роут `GET /api/pinterest/files` |
| `web/templates/index.html` | Кнопка вкладки, HTML-панель, JS (состояние + load + render + фильтры + info drawer) |

---

## Task 1: Backend — эндпоинт `GET /api/pinterest/files`

**Files:**
- Modify: `web/app.py` (строки 884-885 для `_SPA_PATHS`, вставить роут перед строкой 887)

- [ ] **Шаг 1: Добавить `/pinterest` в `_SPA_PATHS`**

Найти в `web/app.py`:
```python
_SPA_PATHS = {"/mediafiles", "/etalons", "/trash", "/admin",
              "/admin/prompts", "/admin/messages", "/admin/users"}
```
Заменить на:
```python
_SPA_PATHS = {"/mediafiles", "/etalons", "/trash", "/pinterest", "/admin",
              "/admin/prompts", "/admin/messages", "/admin/users"}
```

- [ ] **Шаг 2: Добавить роут `GET /api/pinterest/files` перед `@app.post("/api/pinterest/generate")`**

Вставить в `web/app.py` перед строкой `@app.post("/api/pinterest/generate")`:

```python
@app.get("/api/pinterest/files")
async def pinterest_files(session: str | None = Cookie(default=None)):
    """Возвращает медиафайлы пользователя из таблицы media_files."""
    user = _get_current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    rows = await _db_pool.fetch(
        """
        SELECT article_code, file_type, file_path, watermarked_path,
               pinterest_export_count, pinterest_exported_at, created_at
        FROM media_files
        WHERE user_id = $1
        ORDER BY created_at DESC
        """,
        user["user_id"],
    )

    files = []
    for r in rows:
        serve_path = _db_path_to_serve_path(r["watermarked_path"] or r["file_path"])
        if not serve_path:
            continue
        files.append({
            "path":         serve_path,
            "articul":      r["article_code"],
            "type":         r["file_type"],
            "has_watermark": r["watermarked_path"] is not None,
            "export_count": r["pinterest_export_count"],
            "exported_at":  r["pinterest_exported_at"].isoformat() if r["pinterest_exported_at"] else None,
            "created_at":   r["created_at"].isoformat(),
        })

    articuls = sorted({f["articul"] for f in files})
    return {"files": files, "articuls": articuls}
```

- [ ] **Шаг 3: Проверить синтаксис**

```bash
cd /var/www/bots/Zalivai_bot && python -c "import web.app"
```

Ожидаемый результат: нет ошибок (пустой вывод).

- [ ] **Шаг 4: Коммит**

```bash
git add web/app.py
git commit -m "feat: добавить GET /api/pinterest/files и SPA-путь /pinterest"
```

---

## Task 2: Frontend HTML — вкладка и панель

**Files:**
- Modify: `web/templates/index.html`

- [ ] **Шаг 1: Добавить кнопку вкладки**

Найти в `index.html`:
```html
    <button class="tab-btn"        data-tab="trash" id="tab-btn-trash" style="display:none" onclick="switchTab('trash')">Корзина</button>
```
После этой строки вставить:
```html
    <button class="tab-btn"        data-tab="pinterest" onclick="switchTab('pinterest')">Пинтерест</button>
```

- [ ] **Шаг 2: Добавить HTML-панель**

Найти в `index.html`:
```html
  {% if is_admin %}
  <!-- ── Вкладка: Администратор ── -->
```
Перед этим блоком вставить:
```html
  <!-- ── Вкладка: Пинтерест ── -->
  <div id="tab-pinterest" class="tab-panel">

    <div class="filters">
      <div class="filter-group" id="pint-type-filters">
        <button class="chip active" data-type="all"   onclick="setPintType(this)">Все</button>
        <button class="chip photo"  data-type="photo" onclick="setPintType(this)">📷 Фото</button>
        <button class="chip video"  data-type="video" onclick="setPintType(this)">🎬 Видео</button>
      </div>

      <div class="filter-sep"></div>

      <div class="filter-group" id="pint-articul-filters">
        <button class="chip active" data-articul="all" onclick="setPintArticul(this)">Все артикулы</button>
      </div>
    </div>

    <div class="stats" id="pint-stats"></div>
    <div id="pint-content">
      <div class="loader"><div class="spinner"></div></div>
    </div>

  </div>

```

- [ ] **Шаг 3: Коммит**

```bash
git add web/templates/index.html
git commit -m "feat: добавить HTML-панель вкладки Пинтерест"
```

---

## Task 3: Frontend JS — состояние, загрузка, рендер, фильтры

**Files:**
- Modify: `web/templates/index.html` (секция `<script>`)

- [ ] **Шаг 1: Добавить `pinterest` в URL-маппинги и флаг загрузки**

Найти:
```javascript
let refsLoaded  = false;
let trashLoaded = false;
let adminLoaded = false;

const _TAB_URL   = { media: '/mediafiles', refs: '/etalons', trash: '/trash', admin: '/admin' };
```
Заменить на:
```javascript
let refsLoaded  = false;
let trashLoaded = false;
let pintLoaded  = false;
let adminLoaded = false;

const _TAB_URL   = { media: '/mediafiles', refs: '/etalons', trash: '/trash', pinterest: '/pinterest', admin: '/admin' };
```

- [ ] **Шаг 2: Добавить вызов `loadPinterest()` в `switchTab`**

Найти в функции `switchTab`:
```javascript
  if (name === 'admin' && !adminLoaded) {
    adminLoaded = true;
    loadAdmin();
  }
```
Перед этим блоком вставить:
```javascript
  if (name === 'pinterest' && !pintLoaded) {
    pintLoaded = true;
    loadPinterest();
  }
```

- [ ] **Шаг 3: Добавить переменные состояния Pinterest**

Найти:
```javascript
// ── Медиафайлы: состояние фильтров ───────────────────────────────────────────

let allFiles   = [];
```
Перед этим блоком добавить:
```javascript
// ── Пинтерест: состояние ─────────────────────────────────────────────────────

let pintFiles      = [];
let pintActiveType = 'all';
let pintActiveArt  = 'all';
let pintLbFiles    = [];
```

- [ ] **Шаг 4: Добавить функции Pinterest после секции `// ── Корзина ──`**

Найти строку:
```javascript
// ── Корзина ───────────────────────────────────────────────────────────────────
```
Перед ней вставить:

```javascript
// ── Пинтерест ─────────────────────────────────────────────────────────────────

function loadPinterest() {
  fetch('/api/pinterest/files')
    .then(r => r.json())
    .then(data => {
      pintFiles = data.files;

      const artContainer = document.getElementById('pint-articul-filters');
      data.articuls.forEach(art => {
        const btn = document.createElement('button');
        btn.className = 'chip';
        btn.dataset.articul = art;
        btn.textContent = art;
        btn.onclick = () => setPintArticul(btn);
        artContainer.appendChild(btn);
      });

      renderPinterest();
    })
    .catch(() => {
      document.getElementById('pint-content').innerHTML =
        '<div class="empty"><h3>Ошибка загрузки</h3><p>Попробуйте обновить страницу.</p></div>';
    });
}

function setPintType(btn) {
  pintActiveType = btn.dataset.type;
  document.querySelectorAll('#pint-type-filters .chip').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderPinterest();
}

function setPintArticul(btn) {
  pintActiveArt = btn.dataset.articul;
  document.querySelectorAll('#pint-articul-filters .chip').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderPinterest();
}

function pintFiltered() {
  return pintFiles.filter(f => {
    if (pintActiveType !== 'all' && f.type !== pintActiveType) return false;
    if (pintActiveArt  !== 'all' && f.articul !== pintActiveArt)  return false;
    return true;
  });
}

function renderPinterest() {
  const files   = pintFiltered();
  const content = document.getElementById('pint-content');
  const stats   = document.getElementById('pint-stats');

  const photos = files.filter(f => f.type === 'photo').length;
  const videos = files.filter(f => f.type === 'video').length;
  stats.textContent = files.length === 0 ? '' :
    `Показано: ${files.length} файл${plural(files.length, '', 'а', 'ов')}` +
    (photos ? ` · ${photos} фото` : '') +
    (videos ? ` · ${videos} видео` : '');

  if (files.length === 0) {
    content.innerHTML = `
      <div class="empty">
        <h3>Файлы не найдены</h3>
        <p>Попробуйте изменить фильтры или создайте фото в боте.</p>
      </div>`;
    return;
  }

  pintLbFiles = files;
  content.innerHTML = `<div class="grid">${files.map((f, i) => pintCardHTML(f, i)).join('')}</div>`;
  observePintVideoThumbs();
}

function pintCardHTML(f, i) {
  const media = f.type === 'photo'
    ? `<img src="/thumb/${f.path}" loading="lazy" alt="${f.articul}">`
    : `<img class="video-thumb" data-video-src="/files/${f.path}" alt="${f.articul}">`;

  return `
    <div class="card" onclick="openPintLightbox(${i})">
      ${media}
      ${f.type === 'video' ? '<span class="badge-video">▶ видео</span>' : ''}
      <button class="card-info-btn" onclick="showPintInfoDrawer(event,${i})" title="Информация">ⓘ</button>
      <div class="card-overlay">
        <span class="card-articul">${f.articul}</span>
      </div>
    </div>`;
}

function observePintVideoThumbs() {
  document.querySelectorAll('#pint-content .video-thumb:not([src])').forEach(img => {
    _vthumbObserver.observe(img);
  });
}

function openPintLightbox(i) {
  lbFiles = pintLbFiles;
  openLightbox(i);
}

```

- [ ] **Шаг 5: Коммит**

```bash
git add web/templates/index.html
git commit -m "feat: добавить JS-логику вкладки Пинтерест (загрузка, рендер, фильтры)"
```

---

## Task 4: Frontend JS — info drawer для Pinterest

**Files:**
- Modify: `web/templates/index.html`

- [ ] **Шаг 1: Добавить функцию `showPintInfoDrawer`**

Найти в `index.html`:
```javascript
function closeInfoDrawer() {
```
Перед ней вставить:

```javascript
function showPintInfoDrawer(e, i) {
  e.stopPropagation();
  const f = pintLbFiles[i];

  document.getElementById('info-drawer-title').textContent =
    (f.type === 'video' ? '▶ Видео' : '📷 Фото') + ' · ' + f.articul;

  const createdAt = new Date(f.created_at).toLocaleString('ru-RU', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  });
  const exportedAt = f.exported_at
    ? new Date(f.exported_at).toLocaleString('ru-RU', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
      })
    : '—';

  const rows = [
    ['📅', 'Создан',            createdAt],
    ['📦', 'Артикул',           f.articul],
    ['🎨', 'Тип',               f.type === 'photo' ? 'Фото' : 'Видео'],
    ['🔖', 'Водяной знак',      f.has_watermark ? '✓ Нанесён' : '✗ Нет'],
    ['📤', 'Экспортов Pinterest', f.export_count > 0 ? String(f.export_count) : 'Не экспортировался'],
    ['🗓', 'Последний экспорт', exportedAt],
  ];

  const body = rows.map(([icon, label, val]) => `
    <div class="info-row">
      <span class="info-icon">${icon}</span>
      <span class="info-label">${label}:</span>
      <span class="info-value">${escHtml(String(val))}</span>
    </div>`).join('');

  document.getElementById('info-drawer-body').innerHTML = body;
  document.getElementById('info-overlay').classList.add('open');
  document.getElementById('info-drawer').classList.add('open');
  document.addEventListener('keydown', onKeyDown);
}

```

- [ ] **Шаг 2: Коммит**

```bash
git add web/templates/index.html
git commit -m "feat: добавить info drawer для вкладки Пинтерест"
```

---

## Task 5: Деплой и проверка

- [ ] **Шаг 1: Деплой на сервер**

```bash
ssh -o RemoteCommand=none -o RequestTTY=no sku "cd /var/www/bots/Zalivai_bot && git pull && sudo systemctl restart zalivai-web"
```

- [ ] **Шаг 2: Ручная проверка**

Открыть `https://media.zaliv.ai/pinterest`.

Проверить:
1. Вкладка «Пинтерест» видна в навбаре
2. Сетка карточек загружается (те же размеры что в Медиафайлах)
3. Фильтры по типу и артикулу работают
4. Видео показывают превью (canvas)
5. Клик на карточку — открывается лайтбокс
6. ⓘ открывает drawer с полями: Артикул, Тип, Водяной знак, Экспортов, Последний экспорт, Создан
7. Прямой переход по URL `https://media.zaliv.ai/pinterest` работает без 404
