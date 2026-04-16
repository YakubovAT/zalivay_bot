CREATE TABLE IF NOT EXISTS users (
    user_id         BIGINT PRIMARY KEY,
    username        TEXT,
    balance         INTEGER NOT NULL DEFAULT 0,
    ad_budget       TEXT,
    articles_count  TEXT,
    is_registered   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS article_references (
    id                SERIAL PRIMARY KEY,
    user_id           BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    articul           TEXT NOT NULL,
    reference_number  INTEGER NOT NULL DEFAULT 1,
    file_id           TEXT NOT NULL,
    file_path         TEXT,
    reference_image_url TEXT,
    category          TEXT,
    reference_prompt  TEXT,
    product_description TEXT,
    product_name      TEXT,
    product_color     TEXT,
    product_material  TEXT,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_article_references_user_articul
    ON article_references (user_id, articul, is_active);

CREATE TABLE IF NOT EXISTS user_actions (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    username    TEXT,
    action_type TEXT NOT NULL,
    content     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_actions_user_id ON user_actions (user_id);
CREATE INDEX IF NOT EXISTS idx_user_actions_created_at ON user_actions (created_at DESC);

CREATE TABLE IF NOT EXISTS articles (
    id           SERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    article_code TEXT NOT NULL,
    marketplace  TEXT NOT NULL CHECK (marketplace IN ('WB', 'OZON')),
    name         TEXT,
    color        TEXT,
    material     TEXT,
    wb_images    JSONB DEFAULT '[]',
    parsed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_user_article
    ON articles (user_id, article_code, marketplace);

-- Очередь задач генерации фото и видео
CREATE TABLE IF NOT EXISTS generation_tasks (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    chat_id     BIGINT NOT NULL,
    task_type   TEXT NOT NULL CHECK (task_type IN ('photo', 'video', 'lifestyle_photo', 'lifestyle_video')),
    articul     TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    result_url  TEXT,
    error_msg   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generation_tasks_status
    ON generation_tasks (status, created_at);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_user
    ON generation_tasks (user_id, created_at DESC);

-- Группа задач генерации (один запрос пользователя = N фото)
CREATE TABLE IF NOT EXISTS generation_jobs (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    chat_id         BIGINT NOT NULL,
    article         TEXT NOT NULL,
    ref_number      INTEGER NOT NULL,
    ref_image_url   TEXT NOT NULL,
    wish            TEXT,
    count           INTEGER NOT NULL,
    cost            INTEGER NOT NULL,
    screen_msg_id   BIGINT,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generation_jobs_user
    ON generation_jobs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_jobs_status
    ON generation_jobs (status, created_at);

-- Добавляем job_id и file_path к существующей таблице задач
ALTER TABLE generation_tasks
    ADD COLUMN IF NOT EXISTS job_id    INTEGER REFERENCES generation_jobs(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS file_path TEXT;

-- Добавляем lifestyle_video в CHECK constraint (миграция для существующих БД)
DO $$
BEGIN
    ALTER TABLE generation_tasks DROP CONSTRAINT IF EXISTS generation_tasks_task_type_check;
    ALTER TABLE generation_tasks ADD CONSTRAINT generation_tasks_task_type_check
        CHECK (task_type IN ('photo', 'video', 'lifestyle_photo', 'lifestyle_video'));
EXCEPTION WHEN others THEN NULL;
END $$;

-- Исходные фото эталона и дата мягкого удаления (web-корзина)
ALTER TABLE article_references
    ADD COLUMN IF NOT EXISTS source_photo_paths JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL;

-- Кэш маркетплейса: хранит подтверждённый результат (WB/OZON)
-- для ускорения повторного ввода того же артикула.
CREATE TABLE IF NOT EXISTS marketplace_cache (
    user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    article     TEXT   NOT NULL,
    marketplace TEXT   NOT NULL CHECK (marketplace IN ('WB', 'OZON')),
    cached_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, article)
);

CREATE INDEX IF NOT EXISTS idx_marketplace_cache_lookup
    ON marketplace_cache (user_id, article);

-- ============================================================
-- Промпты: шаблоны и списки элементов (редактируются через admin)
-- ============================================================

-- Шаблоны промптов — 8 записей (4 фото + 4 видео).
-- Ключи фиксированы: менять нельзя (привязаны к коду).
-- Значение template редактируется: текст вокруг {placeholders}.
-- ВАЖНО: имена {placeholder} в шаблонах — контракт с кодом, переименовывать запрещено.
CREATE TABLE IF NOT EXISTS prompt_templates (
    key         TEXT PRIMARY KEY,
    template    TEXT NOT NULL,
    description TEXT,
    banner      TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Добавляем banner к существующим БД (idempotent)
ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS banner TEXT;

-- Устанавливаем баннер для msg_welcome
-- NULL = использовать banner_default.png (поведение по умолчанию)
UPDATE prompt_templates
    SET banner = 'welcom_banner_1.png'
    WHERE key = 'msg_welcome' AND banner IS NULL;

-- Элементы списков: локации, одежда, цвета и т.д.
-- list_key привязан к коду — не переименовывать.
-- value — основное значение (текст элемента).
-- value2 — вторичное значение: движение модели (video_locations) или цвет одежды (video_*_items).
-- is_active = FALSE скрывает элемент без удаления.
-- sort_order управляет порядком в admin-панели.
CREATE TABLE IF NOT EXISTS prompt_list_items (
    id          SERIAL PRIMARY KEY,
    list_key    TEXT NOT NULL,
    value       TEXT NOT NULL,
    value2      TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prompt_list_items_lookup
    ON prompt_list_items (list_key, is_active, sort_order);

-- Seed: вставляем только если таблицы пусты (идемпотентно)
-- При редактировании через admin-панель данные обновляются в БД,
-- повторный запуск schema.sql при рестарте бота их не перезатирает.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates LIMIT 1) THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('photo_top',
     'Fashion lifestyle editorial photograph. A stylish young woman wearing {description}, paired with {item_color} {bottom_item}. Setting: {location}. Confident, natural relaxed pose. Soft diffused natural light, warm tones, shallow depth of field with blurred bokeh background. Sharp focus on the top garment — fabric texture, fit, and drape clearly visible. Photorealistic commercial photography, high resolution, no distortion.',
     'Фото — категория «верх». Переменные: {description}, {item_color}, {bottom_item}, {location}'),
    ('photo_bottom',
     'Fashion lifestyle editorial photograph. A stylish young woman wearing {description}, paired with {item_color} {top_item}. Setting: {location}. Natural relaxed stance, elongated silhouette. Soft diffused natural light, warm tones, shallow depth of field with blurred bokeh background. Sharp focus on the bottom garment — fabric texture, fit, and leg line clearly visible. Photorealistic commercial photography, high resolution, no distortion.',
     'Фото — категория «низ». Переменные: {description}, {item_color}, {top_item}, {location}'),
    ('photo_shoes',
     'Fashion lifestyle editorial photograph. A stylish young woman wearing {description}. Outfit: {neutral_outfit}. Setting: {location}. Natural pose with footwear prominent in frame, slight low-angle view to feature the shoes. Soft side natural lighting, shallow depth of field. Sharp focus on the footwear — material texture, construction, and sole detail clearly visible. Photorealistic commercial photography, high resolution, no distortion.',
     'Фото — категория «обувь». Переменные: {description}, {neutral_outfit}, {location}'),
    ('photo_hat',
     'Fashion lifestyle editorial photograph. A stylish young woman wearing {description}. Outfit: {neutral_outfit}. Setting: {location}. Natural confident pose, upper body and headwear in clean frame. Soft diffused natural light, warm tones. Sharp focus on the headwear — fabric, structure, and brim detail clearly visible. Photorealistic commercial photography, high resolution, no distortion.',
     'Фото — категория «головной убор». Переменные: {description}, {neutral_outfit}, {location}'),
    ('video_top',
     'Smooth cinematic fashion lifestyle video. A stylish young woman wearing {description}, paired with {item_color} {item}. Location: {location}. The model is {motion}. Slow gliding camera captures the fabric drape and flow of the garment. Warm soft natural lighting, cinematic color grading, shallow depth of field. The top garment stays in sharp focus throughout the motion. Professional e-commerce fashion footage, no camera shake, fluid movement.',
     'Видео — категория «верх». Переменные: {description}, {item_color}, {item}, {location}, {motion}'),
    ('video_bottom',
     'Smooth cinematic fashion lifestyle video. A stylish young woman wearing {description}, paired with {item_color} {item}. Location: {location}. The model is {motion}. Slow tracking camera at mid-height captures the drape and movement of the bottom garment. Warm soft natural lighting, cinematic color grading, shallow depth of field. The garment stays in sharp focus throughout the motion. Professional e-commerce fashion footage, no camera shake, fluid movement.',
     'Видео — категория «низ». Переменные: {description}, {item_color}, {item}, {location}, {motion}'),
    ('video_shoes',
     'Smooth cinematic fashion lifestyle video. A stylish young woman wearing {description}, styled with a {outfit}. Location: {location}. The model is {motion}. Camera alternates between full-body and waist-down close-up angles, highlighting the footwear in motion. Warm directional natural lighting, cinematic color grading. Material texture and movement of the shoes clearly visible throughout. Professional e-commerce fashion footage, no camera shake, fluid movement.',
     'Видео — категория «обувь». Переменные: {description}, {outfit}, {location}, {motion}'),
    ('video_hat',
     'Smooth cinematic fashion lifestyle video. A stylish young woman wearing {description}, styled with a {outfit}. Location: {location}. The model is {motion}. Camera frames from shoulders up, with the headwear prominently featured. Soft golden-hour or studio lighting, cinematic color grading. Fabric texture, structure, and movement of the headwear clearly visible. Professional e-commerce fashion footage, no camera shake, fluid movement.',
     'Видео — категория «головной убор». Переменные: {description}, {outfit}, {location}, {motion}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_locations' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_locations', 'city park with green trees', 0),
    ('photo_locations', 'minimalist photo studio with soft light', 1),
    ('photo_locations', 'city street with urban background', 2),
    ('photo_locations', 'cozy cafe interior', 3),
    ('photo_locations', 'sandy beach at sunset', 4),
    ('photo_locations', 'forest path in autumn', 5),
    ('photo_locations', 'river embankment promenade', 6),
    ('photo_locations', 'modern office lobby', 7),
    ('photo_locations', 'rooftop terrace with city view', 8),
    ('photo_locations', 'shopping street with storefronts', 9),
    ('photo_locations', 'botanical garden with flowers', 10),
    ('photo_locations', 'loft interior with brick walls', 11);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_items' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_items', 'jeans', 0),
    ('photo_bottom_items', 'trousers', 1),
    ('photo_bottom_items', 'skirt', 2),
    ('photo_bottom_items', 'shorts', 3),
    ('photo_bottom_items', 'leggings', 4),
    ('photo_bottom_items', 'palazzo pants', 5),
    ('photo_bottom_items', 'straight-leg pants', 6),
    ('photo_bottom_items', 'midi skirt', 7);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_items' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_items', 't-shirt', 0),
    ('photo_top_items', 'shirt', 1),
    ('photo_top_items', 'sweater', 2),
    ('photo_top_items', 'blouse', 3),
    ('photo_top_items', 'hoodie', 4),
    ('photo_top_items', 'top', 5),
    ('photo_top_items', 'cardigan', 6),
    ('photo_top_items', 'turtleneck', 7);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_neutral_outfits' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_neutral_outfits', 'white t-shirt and blue jeans', 0),
    ('photo_neutral_outfits', 'beige sweater and black trousers', 1),
    ('photo_neutral_outfits', 'black blouse and white skirt', 2),
    ('photo_neutral_outfits', 'grey hoodie and dark jeans', 3),
    ('photo_neutral_outfits', 'striped shirt and beige trousers', 4);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_colors' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_colors', 'white', 0),
    ('photo_colors', 'black', 1),
    ('photo_colors', 'navy blue', 2),
    ('photo_colors', 'beige', 3),
    ('photo_colors', 'light grey', 4),
    ('photo_colors', 'dark brown', 5),
    ('photo_colors', 'olive green', 6),
    ('photo_colors', 'pastel pink', 7),
    ('photo_colors', 'cream', 8),
    ('photo_colors', 'charcoal', 9);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'video_locations' LIMIT 1) THEN
    -- value = локация, value2 = движение модели
    INSERT INTO prompt_list_items (list_key, value, value2, sort_order) VALUES
    ('video_locations', 'a sunny city street', 'walking confidently forward, hair gently moving', 0),
    ('video_locations', 'a modern coffee shop', 'sitting gracefully and glancing up at the camera', 1),
    ('video_locations', 'a lush green park', 'strolling leisurely, light breeze in the air', 2),
    ('video_locations', 'a bright minimalist studio', 'rotating slowly with arms slightly extended', 3),
    ('video_locations', 'a seaside promenade', 'walking along the waterfront with a relaxed stride', 4),
    ('video_locations', 'a stylish rooftop terrace with city skyline', 'standing and gazing into the distance', 5),
    ('video_locations', 'a cozy warmly lit café interior', 'reaching for a cup and smiling slightly', 6),
    ('video_locations', 'a vibrant outdoor flower market', 'walking through the stalls, glancing at flowers', 7),
    ('video_locations', 'a clean white studio with soft fill light', 'posing and turning to show all angles', 8),
    ('video_locations', 'an urban pedestrian bridge', 'walking toward the camera with a confident gait', 9),
    ('video_locations', 'a forest path with autumn foliage', 'walking through softly falling leaves', 10),
    ('video_locations', 'an elegant marble hotel lobby', 'walking through the entrance with a graceful stride', 11),
    ('video_locations', 'a sunlit courtyard with stone architecture', 'stepping forward and pausing naturally', 12),
    ('video_locations', 'a glass-front boutique street', 'walking past storefronts, window reflection visible', 13);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'video_bottom_items' LIMIT 1) THEN
    -- value = название элемента одежды, value2 = цвет (для подстановки в {item_color})
    -- Используется для категории «верх» (дополняющий низ)
    INSERT INTO prompt_list_items (list_key, value, value2, sort_order) VALUES
    ('video_bottom_items', 'white jeans', 'light', 0),
    ('video_bottom_items', 'black slim trousers', 'dark', 1),
    ('video_bottom_items', 'beige linen pants', 'neutral', 2),
    ('video_bottom_items', 'light blue denim skirt', 'blue', 3),
    ('video_bottom_items', 'khaki wide-leg pants', 'khaki', 4);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'video_top_items' LIMIT 1) THEN
    -- Используется для категории «низ» (дополняющий верх)
    INSERT INTO prompt_list_items (list_key, value, value2, sort_order) VALUES
    ('video_top_items', 'white fitted t-shirt', 'white', 0),
    ('video_top_items', 'light beige blouse', 'beige', 1),
    ('video_top_items', 'soft grey knit', 'grey', 2),
    ('video_top_items', 'pastel pink turtleneck', 'pink', 3),
    ('video_top_items', 'navy blue shirt', 'navy', 4);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'video_neutral_outfits' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('video_neutral_outfits', 'neutral beige linen outfit', 0),
    ('video_neutral_outfits', 'minimalist white and grey ensemble', 1),
    ('video_neutral_outfits', 'simple all-black monochrome look', 2),
    ('video_neutral_outfits', 'soft cream knit and wide-leg ivory trousers', 3),
    ('video_neutral_outfits', 'light denim jacket over a white linen shirt and straight trousers', 4),
    ('video_neutral_outfits', 'camel turtleneck and tailored sand-colored trousers', 5),
    ('video_neutral_outfits', 'pastel lavender blouse and white straight-leg pants', 6);
  END IF;
END $$;

-- ============================================================
-- UI-сообщения бота (редактируются через admin)
-- Ключи начинаются с msg_ — отличие от AI-промптов.
-- {placeholder} в тексте — переменные подставляемые кодом, не переименовывать.
-- ============================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_welcome') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_welcome',
     'Шаг 1: Приветствие

Система массовой автоматизированной генерации профессионального
фото и видео контента для товаров с последующим размещением в социальных сетях.

Возможно создавать фото и видео в различных форматах
по заранее спроектированным промптам для ваших товаров.',
     'Шаг 1 — экран приветствия при /start. Переменных нет.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_profile') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_profile',
     'Шаг 2: Профиль

👤 *Профиль:*
> • ID: `{user_id}`
> • Имя: {full_name}

📊 *Статистика:*
> • Товаров: {articles}
> • Эталонов: {references}
> • Фото: {photos}
> • Видео: {videos}
> • Баланс: {balance}₽',
     'Шаг 2 — экран профиля/меню. Переменные: {user_id}, {full_name}, {articles}, {references}, {photos}, {videos}, {balance}.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_marketplace_select') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_marketplace_select',
     'Шаг 3 из N: Выбор маркетплейса

Выберите маркетплейс, на котором продаётся ваш товар. После мы с вами создадим фото и видео контент для последующего размещения в социальных сетях. Вам нужно будет ввести артикул товара, и мы создадим эталон вашего товара для генерации фото и видео контента.',
     'Шаг 3 — экран выбора маркетплейса. Переменных нет.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_article_input') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_article_input',
     'Шаг 4 из N: Ввод артикула

В строку сообщений введите артикул.

Мы загрузим фото из карточки. Выберите 3 лучших — где ваш товар виден наиболее чётко и детально. Это станет основой для генерации фото и видео контента.',
     'Шаг 4 — экран ввода артикула. Переменных нет.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_product_found') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_product_found',
     'Шаг 5 из N: Найден товар

📦 {name}
🏷 Бренд: {brand}
🎨 Цвет: {color}
🧵 Состав: {material}

Это тот товар?',
     'Шаг 5 — найденный товар и подтверждение. Переменные: {name}, {brand}, {color}, {material}.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_photo_select') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_photo_select',
     'Шаг 6 из N: Выбор фото — {current} из {total}

{selection_text}',
     'Шаг 6 — экран выбора фото. Переменные: {current}, {total}, {selection_text}.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_reference_create_confirm') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_reference_create_confirm',
     'Шаг 7 из N: Создание эталона

Вы выбрали 3 фото для артикула <code>{article}</code>.

Убедитесь, что на этих фото товар виден лучше всего — по ним будет создан эталон для генерации контента.',
     'Шаг 7 — подтверждение создания эталона после выбора 3 фото. Переменные: {article}.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_reference_creating') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_reference_creating',
     '⏳ Создаю эталон для артикула <code>{article}</code>...

<a href="https://zaliv.ai/">Zaliv.AI</a> — сервис массовой автоматизированной генерации профессионального фото и видео контента для товаров с последующим размещением в социальных сетях.

Это займёт 1-3 минуты...',
     'Шаг 8 — экран начала создания эталона. Переменные: {article}.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_reference_generating_photo') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_reference_generating_photo',
     '⏳ Генерирую фото эталона...
Тип товара: {category}

Созданный эталон позволит вам массово генерировать фото и видео для любых площадок: Telegram, VK, Instagram, YouTube и других социальных сетей.

Осталось немного...',
     'Шаг 10 — экран генерации фото эталона. Переменные: {category}.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_reference_ready') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_reference_ready',
     'Шаг 11 из N: Эталон готов!

📦 Артикул: <code>{article}</code>
📸 Это ваш {reference_number}-й эталон для этого товара
🏷 Тип товара: {category}

💰 Списано: {reference_cost}₽
💳 Ваш баланс: {new_balance}₽

Эталон может немного отличаться от оригинала.
Если отличия значительные — перегенерируйте эталон,
заменив фотографии на шаге выбора фото.

Теперь вы можете генерировать фото и видео!',
     'Шаг 11 — экран готового эталона. Переменные: {article}, {reference_number}, {category}, {reference_cost}, {new_balance}.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_my_refs_empty') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_my_refs_empty',
     '📂 Мои эталоны (Шаг 15)

У вас пока нет товаров с эталонами.

Создайте первый эталон, чтобы генерировать фото и видео для ваших товаров.',
     'Шаг 15 — список эталонов пуст. Переменных нет.');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_my_refs_list') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_my_refs_list',
     '📂 Мои эталоны (Шаг 15)

👤 Профиль: {full_name}
🆔 ID: {user_id}
📊 Товаров: {articles} | Эталонов: {references}
📸 Фото: {photos} | 🎥 Видео: {videos} | 💳 Баланс: {balance}₽

Ниже ваши артикулы с эталонами.
Нажмите на артикул — откроется меню работы с эталонами.',
     'Шаг 15 — список артикулов с эталонами. Переменные: {user_id}, {full_name}, {articles}, {references}, {photos}, {videos}, {balance}.');
  END IF;
END $$;
