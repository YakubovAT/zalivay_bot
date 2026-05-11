# db_schema.md — Схема базы данных Zalivai Bot

## Таблицы

---

### users
Пользователи бота. Создаётся при первом `/start`.

| Поле          | Тип                       | Описание                |
|---------------|---------------------------|-------------------------|
| user_id       | BIGINT PK                 | Telegram user ID        |
| username      | TEXT                      | Telegram username       |
| balance       | INT DEFAULT 0             | Баланс в рублях         |
| is_onboarded  | BOOLEAN DEFAULT FALSE     | Прошёл ли первый визит  |
| referral_id   | BIGINT FK → users.user_id | Кто привёл пользователя |
| created_at    | TIMESTAMPTZ DEFAULT NOW() | Дата регистрации        |
|---------------|---------------------------|-------------------------|
---

### user_sources
UTM метки при первом входе. Одна запись на пользователя.

| Поле | Тип | Описание |
|---------------|---------------------------|-----------------------------------------|
| id            | SERIAL PK                 |                                         |
| user_id       | BIGINT FK → users.user_id |                                         |
| utm_source    | TEXT                      | Источник трафика (google, telegram, vk) |
| utm_medium    | TEXT                      | Тип трафика (cpc, banner, email)        |
| utm_campaign  | TEXT                      | Название рекламной кампании             |
| created_at    | TIMESTAMPTZ DEFAULT NOW() |                                         |
|---------------|---------------------------|-----------------------------------------|
---

### articles
Товары пользователей с маркетплейса. Один артикул = одна запись.

| Поле | Тип | Описание |
|------|-----|----------|
| id | SERIAL PK | |
| user_id | BIGINT FK → users.user_id | |
| article_code | TEXT | Артикул с маркетплейса |
| marketplace | TEXT | WB / OZON |
| status | TEXT | parsed / confirmed / ready |
| raw_json | JSONB | Сырые данные с маркетплейса (название, фото, характеристики) |
| ai_json | JSONB | Результат T2T (category, safe_name, description, визуальные характеристики) |
| reference_path | TEXT | Путь к фото-эталону на диске |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |

**Статусы articles:**
- `parsed` — товар спарсен, ждём подтверждения пользователя
- `confirmed` — пользователь подтвердил товар
- `ready` — фото-эталон создан, можно генерировать контент

**Пример ai_json:**
```json
{
  "category": "низ",
  "safe_name": "джинсы",
  "description": "wide leg distressed jeans, blue denim, 100% cotton"
}
```

**Индекс:** UNIQUE (user_id, article_code, marketplace)

---

### media_files
Сгенерированный контент (фото и видео) для артикулов.

| Поле | Тип | Описание |
|------|-----|----------|
| id | SERIAL PK | |
| user_id | BIGINT FK → users.user_id | |
| article_code | TEXT FK → articles.article_code | |
| file_path | TEXT | Путь к оригиналу без маркировки |
| marked_path | TEXT | Путь к файлу с маркировкой (артикул + название) |
| file_type | TEXT | photo / video |
| title_content | TEXT | Шаблон заголовка для Pinterest с переменными |
| description_content | TEXT | Шаблон описания для Pinterest с переменными |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |

**Пример title_content:**
```
Эта {переменная1} {предмет} подойдет для {переменная2} {id}
```

**Пример description_content:**
```
Эта {переменная1} {предмет} подойдет для {переменная2} {id} #тег1 #тег2 #тег3
```

---

### jobs
Группы задач генерации. Один запрос пользователя = один job.

| Поле | Тип | Описание |
|------|-----|----------|
| id | SERIAL PK | |
| user_id | BIGINT FK → users.user_id | |
| article_code | TEXT FK → articles.article_code | |
| type | TEXT | photo / video |
| status | TEXT | pending / processing / done / failed |
| count | INT | Желаемое количество финальных файлов |
| cost | INT | Стоимость задачи в рублях |
| screen_msg_id | BIGINT | ID сообщения в Telegram для отправки результата |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |

**Логика count → tasks:**
- count = 4 → ceil(4/4) = 1 task (1 запрос I2I → нарезка → 4 фото)
- count = 20 → ceil(20/4) = 5 tasks
- count = 50 → ceil(50/4) = 13 tasks
- count = 100 → ceil(100/4) = 25 tasks

---

### tasks
Отдельные задачи внутри job. Один task = один запрос к I2I или I2V API.

| Поле | Тип | Описание |
|------|-----|----------|
| id | SERIAL PK | |
| job_id | INT FK → jobs.id | |
| user_id | BIGINT FK → users.user_id | |
| status | TEXT | pending / processing / done / failed |
| prompt | TEXT | Промпт для I2I или I2V |
| result_url | TEXT | URL результата от API |
| error | TEXT | Текст ошибки если status = failed |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |

---

### variables
Массивы синонимов для генерации уникальных заголовков, описаний и промптов.

| Поле | Тип | Описание |
|------|-----|----------|
| id | SERIAL PK | |
| platform | TEXT | pinterest / instagram / tiktok / NULL (для промптов) |
| category | TEXT | title / description / prompt |
| name | TEXT | переменная1 / переменная2 / локация / поза |
| values | JSONB | Массив значений ["красивый", "прекрасный", "лучший"] |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |

**Пример заполнения:**

| platform | category | name | values |
|----------|----------|------|--------|
| pinterest | title | переменная1 | ["красивый", "прекрасный", "лучший", "стильный"] |
| pinterest | title | переменная2 | ["вечеринку", "в гости", "на выход", "на вечер"] |
| pinterest | description | переменная3 | ["девушки", "женщины", "модницы"] |
| NULL | prompt | локация | ["парк", "кафе", "улица", "студия"] |
| NULL | prompt | поза | ["сидит", "идёт", "стоит", "смотрит в камеру"] |

---

### prompts
Шаблоны промптов для T2T, I2I и I2V. Редактируются через админку без деплоя.

| Поле | Тип | Описание |
|------|-----|----------|
| id | SERIAL PK | |
| type | TEXT | t2t / i2i / i2v |
| name | TEXT | reference / content / 4photos |
| template | TEXT | Промпт с переменными {safe_name}, {category} и т.д. |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |

**Пример:**

| type | name | template |
|------|------|----------|
| t2t | reference | Определи категорию товара: {imt_name}, состав: {material}... |
| i2i | reference | Выдели только {safe_name} на прозрачном фоне... |
| i2i | 4photos | Создай изображение разделённое на 4 части... |

---

### messages
Тексты сообщений бота. Редактируются через админку без деплоя.

| Поле | Тип | Описание |
|------|-----|----------|
| id | SERIAL PK | |
| key | TEXT UNIQUE | Уникальный ключ сообщения |
| text | TEXT | Текст сообщения с переменными |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |

**Пример заполнения:**

| key | text |
|-----|------|
| start_welcome | Привет! 👋 Я помогу тебе создать красивые пины... |
| article_input | Введи артикул товара с Wildberries 👇 |
| error_invalid_article | ❌ Не распознал артикул. Введи только цифры, например: 832731061 |
| confirm_product | Нашёл твой товар 👆 |
| generating | ⏳ Создаю фото-эталон твоего товара... |

---

## Связи между таблицами

```
users
  ├── user_sources        (один пользователь → одна запись UTM)
  ├── articles            (один пользователь → много артикулов)
  │     ├── media_files   (один артикул → много медиафайлов)
  │     └── jobs          (один артикул → много job'ов)
  │           └── tasks   (один job → много tasks)
  └── referral_id → users (самоссылка — кто привёл)

Независимые таблицы (не привязаны к пользователю):
  variables               (синонимы для генерации)
  prompts                 (шаблоны промптов)
  messages                (тексты сообщений бота)
```

---

## Правила

1. Все таблицы имеют `created_at`
2. Удаление пользователя → CASCADE удаляет всё его данные
3. `variables`, `prompts`, `messages` — только через админку, не в коде
4. `ai_json` и `raw_json` — JSONB для быстрого поиска внутри
5. Не хранить то что можно вычислить (например количество медиафайлов)
6. Каждое поле отвечает на вопрос "зачем оно нужно прямо сейчас"
