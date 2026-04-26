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

-- Очередь задач создания фото и видео
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

-- Группа задач создания (один запрос пользователя = N фото)
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

-- Шаблоны промптов — 10 записей (5 фото + 5 видео).
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

-- Добавляем sort_order к существующим БД (idempotent)
ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;

-- Расставляем порядок UI-сообщений (только там где ещё 0, т.е. не задан вручную)
UPDATE prompt_templates SET sort_order = CASE key
    -- Основной флоу: онбординг + создание эталона
    WHEN 'msg_welcome'                        THEN 10
    WHEN 'msg_profile'                        THEN 20
    WHEN 'msg_marketplace_select'             THEN 30
    WHEN 'msg_article_input'                  THEN 40
    WHEN 'msg_product_found'                  THEN 50
    WHEN 'msg_photo_select'                   THEN 60
    WHEN 'msg_reference_create_confirm'       THEN 70
    WHEN 'msg_reference_creating'             THEN 80
    WHEN 'msg_reference_generating_photo'     THEN 90
    WHEN 'msg_reference_ready'                THEN 100
    -- Список эталонов
    WHEN 'msg_my_refs_empty'                  THEN 150
    WHEN 'msg_my_refs_list'                   THEN 155
    -- Карточка эталона + пересоздание
    WHEN 'msg_ref_card'                       THEN 160
    WHEN 'msg_regen_no_source_photos'         THEN 162
    WHEN 'msg_regen_wish'                     THEN 164
    WHEN 'msg_regen_generating'               THEN 166
    WHEN 'msg_regen_result'                   THEN 168
    -- Создание фото
    WHEN 'msg_gen_photo_count'                THEN 200
    WHEN 'msg_gen_photo_wish'                 THEN 210
    WHEN 'msg_gen_photo_confirm'              THEN 220
    WHEN 'msg_gen_photo_generating'           THEN 230
    -- Создание видео
    WHEN 'msg_gen_video_count'                THEN 300
    WHEN 'msg_gen_video_wish'                 THEN 310
    WHEN 'msg_gen_video_confirm'              THEN 320
    WHEN 'msg_gen_video_generating'           THEN 330
    -- Результаты фото
    WHEN 'msg_generation_done'                THEN 400
    WHEN 'msg_generation_done_failed_line'    THEN 410
    WHEN 'msg_generation_failed'              THEN 420
    -- Результаты видео
    WHEN 'msg_video_generation_done'          THEN 430
    WHEN 'msg_video_generation_done_failed_line' THEN 440
    WHEN 'msg_video_generation_failed'        THEN 450
    -- Системные
    WHEN 'msg_insufficient_funds'             THEN 600
    WHEN 'msg_insufficient_funds_with_purpose' THEN 610
    ELSE sort_order
END
WHERE key LIKE 'msg_%' AND sort_order = 0;

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

-- ============================================================
-- media_files — реестр сгенерированных медиафайлов
-- ============================================================
CREATE TABLE IF NOT EXISTS media_files (
    id                    SERIAL PRIMARY KEY,
    user_id               BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    article_code          TEXT NOT NULL,
    task_id               INTEGER REFERENCES generation_tasks(id) ON DELETE SET NULL,
    file_path             TEXT NOT NULL,
    result_url            TEXT,
    file_type             TEXT NOT NULL CHECK (file_type IN ('photo', 'video')),
    pinterest_export_count INT         NOT NULL DEFAULT 0,
    pinterest_exported_at  TIMESTAMPTZ NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_media_files_user_article
    ON media_files (user_id, article_code, pinterest_exported_at);

-- ============================================================
-- pinterest_settings — настройки Pinterest на уровне user/article
-- ============================================================
CREATE TABLE IF NOT EXISTS pinterest_settings (
    id            SERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    article_code  TEXT NULL,
    board         TEXT NULL,
    link_template TEXT NULL,
    hashtags      TEXT[] NULL
);

-- Partial unique indexes (UNIQUE не работает с NULL в PostgreSQL)
-- Миграция: добавить pinterest_export_count для существующих БД
ALTER TABLE media_files
    ADD COLUMN IF NOT EXISTS pinterest_export_count INT NOT NULL DEFAULT 0;

-- Миграция: путь к копии изображения с наложенным текстом (артикул + название)
ALTER TABLE media_files
    ADD COLUMN IF NOT EXISTS watermarked_path TEXT NULL;

-- Миграция: мягкое удаление медиафайлов
ALTER TABLE media_files
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_pinterest_settings_user_default
    ON pinterest_settings (user_id) WHERE article_code IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pinterest_settings_user_article
    ON pinterest_settings (user_id, article_code) WHERE article_code IS NOT NULL;

-- Seed: вставляем только если таблицы пусты (идемпотентно)
-- При редактировании через admin-панель данные обновляются в БД,
-- повторный запуск schema.sql при рестарте бота их не перезатирает.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates LIMIT 1) THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
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
     'Видео — категория «головной убор». Переменные: {description}, {outfit}, {location}, {motion}'),
    ('photo_komplekt',
     'Fashion lifestyle editorial photograph. A stylish young woman wearing {description} as a complete outfit. Accessories: {neutral_outfit}. Setting: {location}. Full-body composition, natural confident pose. Soft diffused natural light, warm tones, shallow depth of field with blurred bokeh background. Sharp focus on the jumpsuit — fabric texture, fit, silhouette, and drape clearly visible from neckline to hem. Photorealistic commercial photography, high resolution, no distortion.',
     'Фото — категория «комплект». Переменные: {description}, {neutral_outfit}, {location}'),
    ('video_komplekt',
     'Smooth cinematic fashion lifestyle video. A stylish young woman wearing {description} as a complete look, finished with {outfit}. Location: {location}. The model is {motion}. Slow gliding full-body camera shot captures the silhouette, fabric drape, and movement of the jumpsuit. Warm soft natural lighting, cinematic color grading, shallow depth of field. The garment stays in sharp focus throughout the motion — from neckline to hem. Professional e-commerce fashion footage, no camera shake, fluid movement.',
     'Видео — категория «комплект». Переменные: {description}, {outfit}, {location}, {motion}');
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
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_welcome',
     'Шаг 1: Приветствие

Система массовой автоматизированной создания профессионального
фото и видео контента для товаров с последующим размещением в социальных сетях.

Возможно создавать фото и видео в различных форматах
по заранее спроектированным промптам для ваших товаров.',
     'Шаг 1 — экран приветствия при /start. Переменных нет.', 10);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_profile') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
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
     'Шаг 2 — экран профиля/меню. Переменные: {user_id}, {full_name}, {articles}, {references}, {photos}, {videos}, {balance}.', 20);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_marketplace_select') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_marketplace_select',
     'Шаг 3 из N: Выбор маркетплейса

Выберите маркетплейс, на котором продаётся ваш товар. После мы с вами создадим фото и видео контент для последующего размещения в социальных сетях. Вам нужно будет ввести артикул товара, и мы создадим эталон вашего товара для создания фото и видео контента.',
     'Шаг 3 — экран выбора маркетплейса. Переменных нет.', 30);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_article_input') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_article_input',
     'Шаг 4 из N: Ввод артикула

В строку сообщений введите артикул.

Мы загрузим фото из карточки. Выберите 3 лучших — где ваш товар виден наиболее чётко и детально. Это станет основой для создания фото и видео контента.',
     'Шаг 4 — экран ввода артикула. Переменных нет.', 40);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_product_found') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_product_found',
     'Шаг 5 из N: Найден товар

📦 {name}
🏷 Бренд: {brand}
🎨 Цвет: {color}
🧵 Состав: {material}

Это тот товар?',
     'Шаг 5 — найденный товар и подтверждение. Переменные: {name}, {brand}, {color}, {material}.', 50);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_photo_select') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_photo_select',
     'Шаг 6 из N: Выбор фото — {current} из {total}

{selection_text}',
     'Шаг 6 — экран выбора фото. Переменные: {current}, {total}, {selection_text}.', 60);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_reference_create_confirm') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_reference_create_confirm',
     'Шаг 7 из N: Создание эталона

Вы выбрали 3 фото для артикула <code>{article}</code>.

Убедитесь, что на этих фото товар виден лучше всего — по ним будет создан эталон для создания контента.',
     'Шаг 7 — подтверждение создания эталона после выбора 3 фото. Переменные: {article}.', 70);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_reference_creating') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_reference_creating',
     '⏳ Создаю эталон для артикула <code>{article}</code>...

<a href="https://zaliv.ai/">Zaliv.AI</a> — сервис массовой автоматизированной создания профессионального фото и видео контента для товаров с последующим размещением в социальных сетях.

Это займёт 1-3 минуты...',
     'Шаг 8 — экран начала создания эталона. Переменные: {article}.', 80);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_reference_generating_photo') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_reference_generating_photo',
     '⏳ Создаю фото эталона...
Тип товара: {category}

Созданный эталон позволит вам массово создавать фото и видео для любых площадок: Telegram, VK, Instagram, YouTube и других социальных сетей.

Осталось немного...',
     'Шаг 10 — экран создания фото эталона. Переменные: {category}.', 90);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_reference_ready') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_reference_ready',
     'Шаг 11 из N: Эталон готов!

📦 Артикул: <code>{article}</code>
📸 Это ваш {reference_number}-й эталон для этого товара
🏷 Тип товара: {category}

💰 Списано: {reference_cost}₽
💳 Ваш баланс: {new_balance}₽

Эталон может немного отличаться от оригинала.
Если отличия значительные — пересоздайте эталон,
заменив фотографии на шаге выбора фото.

Теперь вы можете создавать фото и видео!',
     'Шаг 11 — экран готового эталона. Переменные: {article}, {reference_number}, {category}, {reference_cost}, {new_balance}.', 100);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_my_refs_empty') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_my_refs_empty',
     '📂 Мои эталоны (Шаг 15)

У вас пока нет товаров с эталонами.

Создайте первый эталон, чтобы создавать фото и видео для ваших товаров.',
     'Шаг 15 — список эталонов пуст. Переменных нет.', 150);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_my_refs_list') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_my_refs_list',
     '📂 Мои эталоны (Шаг 15)

👤 Профиль: {full_name}
🆔 ID: {user_id}
📊 Товаров: {articles} | Эталонов: {references}
📸 Фото: {photos} | 🎥 Видео: {videos} | 💳 Баланс: {balance}₽

Ниже ваши артикулы с эталонами.
Нажмите на артикул — откроется меню работы с эталонами.',
     'Шаг 15 — список артикулов с эталонами. Переменные: {user_id}, {full_name}, {articles}, {references}, {photos}, {videos}, {balance}.', 155);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_gen_photo_count') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_gen_photo_count',
     '📸 Шаг P1: Сколько фото?

Сколько фото создать на основе этого эталона?

Вы можете создать одно или множество изображений.
Каждое фото будет уникальным — разная локация, освещение, ракурс.

📦 Артикул: <code>{article}</code>
📸 Эталон: #{ref_number}
🏷 Тип товара: {category}

💰 Стоимость: {photo_cost}₽ за фото

Введите число:',
     'Шаг P1 — ввод количества фото для создания. Переменные: {article}, {ref_number}, {category}, {photo_cost}.', 200);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_gen_video_count') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_gen_video_count',
     '🎥 Шаг V1: Сколько видео?

Сколько видео создать на основе этого эталона?

Каждое видео будет уникальным — разная локация, освещение, движение модели.

📦 Артикул: <code>{article}</code>
📸 Эталон: #{ref_number}
🏷 Тип товара: {category}

💰 Стоимость: {video_cost}₽ за видео

Введите число (1–5) или выберите:',
     'Шаг V1 — ввод количества видео для создания. Переменные: {article}, {ref_number}, {category}, {video_cost}.', 300);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_gen_photo_wish') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_gen_photo_wish',
     '📸 Шаг P2: Пожелания

📦 Артикул: <code>{article}</code>
📸 Эталон: #{ref_number}

Будет создано: {count} фото
💰 Стоимость: {total_cost}₽

Есть пожелания к создания?

Например: «хочу фото на фоне моря», «сделай в студии».',
     'Шаг P2 — пожелания к создания фото. Переменные: {article}, {ref_number}, {count}, {total_cost}.', 210);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_gen_photo_confirm') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_gen_photo_confirm',
     '📸 Шаг P3: Подтверждение

Готов создавать {count} фото на основе изображения представленного выше.

📦 Артикул: <code>{article}</code>
{wish_block}💰 Стоимость: {total_cost}₽
💳 Ваш баланс: {balance}₽

Если всё устраивает, нажмите ✅ Создать и процесс запустится.',
     'Шаг P3 — подтверждение создания фото. Переменные: {article}, {count}, {wish_block}, {total_cost}, {balance}.', 220);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_gen_photo_generating') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_gen_photo_generating',
     '📸 Шаг P4: Создание

⏳ Поставил в очередь {count} фото для артикула <code>{article}</code>.

Фото создаются параллельно.
Я пришлю результат когда все будут готовы.',
     'Шаг P4 — постановка создания фото в очередь. Переменные: {article}, {count}.', 230);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_gen_video_wish') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_gen_video_wish',
     '🎥 Шаг V2: Пожелания

📦 Артикул: <code>{article}</code>
📸 Эталон: #{ref_number}

Будет создано: {count} видео
💰 Стоимость: {total_cost}₽

Есть пожелания к создания?

Например: «модель идёт по пляжу», «съёмка в студии».',
     'Шаг V2 — пожелания к создания видео. Переменные: {article}, {ref_number}, {count}, {total_cost}.', 310);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_gen_video_confirm') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_gen_video_confirm',
     '🎥 Шаг V3: Подтверждение

Готов создавать {count} видео на основе изображения выше.

📦 Артикул: <code>{article}</code>
{wish_block}💰 Стоимость: {total_cost}₽
💳 Ваш баланс: {balance}₽

Если всё устраивает, нажмите ✅ Создать.',
     'Шаг V3 — подтверждение создания видео. Переменные: {article}, {count}, {wish_block}, {total_cost}, {balance}.', 320);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_gen_video_generating') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_gen_video_generating',
     '🎥 Шаг V4: Создание

⏳ Поставил в очередь {count} видео для артикула <code>{article}</code>.

Видео создаются параллельно. Это занимает несколько минут.
Я пришлю результат когда всё будет готово.',
     'Шаг V4 — постановка создания видео в очередь. Переменные: {article}, {count}.', 330);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_generation_done') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_generation_done',
     '📸 <b>{total} из {total}</b> фото готовы для <code>{article}</code>
Тут представлен один из вариантов, все ваши создания хранятся здесь:
🖼 {web_viewer_url}

📦 Эталон: #{ref_number}
💰 Списано: {actual_cost}₽
💳 Остаток: {new_balance}₽
⏱ Время: {elapsed_str}
🆔 Задание #{job_id}',
     'Результат создания фото. Переменные: {total}, {article}, {web_viewer_url}, {ref_number}, {actual_cost}, {new_balance}, {elapsed_str}, {job_id}.', 400);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_generation_done_failed_line') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_generation_done_failed_line',
     '⚠️ Не удалось: {failed} из {requested}',
     'Доп. строка для результата создания фото при частичных падениях. Переменные: {failed}, {requested}.', 410);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_generation_failed') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_generation_failed',
     '❌ Не удалось создать фото.

С вашего баланса ничего не списано.

🆔 Задание #{job_id}

При обращении в поддержку укажите номер задания.',
     'Ошибка создания фото. Переменные: {job_id}.', 420);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_video_generation_done') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_video_generation_done',
     '🎥 <b>{total} из {total}</b> видео готовы для <code>{article}</code>
Тут представлен один из вариантов, все ваши создания хранятся здесь:
🖼 {web_viewer_url}

📦 Эталон: #{ref_number}
💰 Списано: {actual_cost}₽
💳 Остаток: {new_balance}₽
⏱ Время: {elapsed_str}
🆔 Задание #{job_id}',
     'Результат создания видео. Переменные: {total}, {article}, {web_viewer_url}, {ref_number}, {actual_cost}, {new_balance}, {elapsed_str}, {job_id}.', 430);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_video_generation_done_failed_line') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_video_generation_done_failed_line',
     '⚠️ Не удалось: {failed} из {requested}',
     'Доп. строка для результата создания видео при частичных падениях. Переменные: {failed}, {requested}.', 440);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_video_generation_failed') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_video_generation_failed',
     '❌ Не удалось создать видео.

С вашего баланса ничего не списано.

🆔 Задание #{job_id}

При обращении в поддержку укажите номер задания.',
     'Ошибка создания видео. Переменные: {job_id}.', 450);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_insufficient_funds') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_insufficient_funds',
     '❌ Недостаточно средств.

💰 Нужно: {needed}₽
💳 Ваш баланс: {balance}₽

Пополните баланс и попробуйте снова.',
     'Недостаточно средств (без указания purpose). Переменные: {needed}, {balance}.', 600);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_insufficient_funds_with_purpose') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_insufficient_funds_with_purpose',
     '❌ Недостаточно средств.

💰 {purpose}: {needed}₽
💳 Ваш баланс: {balance}₽

Пополните баланс и попробуйте снова.',
     'Недостаточно средств (с purpose). Переменные: {purpose}, {needed}, {balance}.', 610);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_ref_card') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_ref_card',
     '📸 Шаг 16: Эталон #{ref_number} из {total}
📦 Артикул: <code>{article}</code>
🏷 Тип товара: {category}',
     'Шаг 16 — заголовок карточки эталона. Переменные: {ref_number}, {total}, {article}, {category}', 160);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_regen_no_source_photos') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_regen_no_source_photos',
     '❌ Исходные фотографии для артикула <code>{article}</code> не найдены.

Возможно, файлы были удалены с сервера. Создайте новый эталон через «➕ Новый эталон».',
     'Шаг 16error — ошибка: исходные фото не найдены. Переменные: {article}', 162);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_regen_wish') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_regen_wish',
     '🔄 Шаг 16а: Пересоздание эталона

📦 Артикул: <code>{article}</code>
📸 Эталон: #{ref_number}

Будут использованы те же 3 фотографии, что и при создании.

Если хотите скорректировать результат — опишите, что не так (например: <i>убери фон, товар должен быть по центру</i>).

Или нажмите <b>Пропустить</b> — эталон пересоздастся с теми же настройками.',
     'Шаг 16а — запрос пожеланий перед пересозданием. Переменные: {article}, {ref_number}', 164);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_regen_generating') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_regen_generating',
     '⏳ Пересоздаю эталон для артикула <code>{article}</code>...

Это займёт 1–3 минуты...',
     'Шаг 16б — прогресс пересоздания. Переменные: {article}', 166);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_regen_result') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('msg_regen_result',
     '✅ Шаг 16а: Новый эталон готов!

📦 Артикул: <code>{article}</code>
📸 Эталон #{ref_number}
🏷 Тип товара: {category}

💰 Списано: {cost}₽
💳 Ваш баланс: {balance}₽

Теперь вы можете создавать фото и видео!',
     'Шаг 16а — финальный результат пересоздания. Переменные: {article}, {ref_number}, {category}, {cost}, {balance}', 168);
  END IF;
END $$;

-- ============================================================
-- Теги эталона: сезон, стиль, пол, возраст, жанр
-- ============================================================

ALTER TABLE article_references
    ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '{}';

-- ============================================================
-- Lifestyle-фото: сцены и переменные (image_prompt_generator)
-- ============================================================

-- Список сцен для категории «низ»
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_scenes' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_scenes', 'room_mirror', 0);
  END IF;
END $$;

-- Общие переменные (shared) — используются во всех сценах где есть плейсхолдер
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_hair_length' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_hair_length', 'short', 0),
    ('photo_shared_hair_length', 'medium-length', 1),
    ('photo_shared_hair_length', 'shoulder-length', 2),
    ('photo_shared_hair_length', 'long', 3),
    ('photo_shared_hair_length', 'waist-length', 4);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_hair_texture' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_hair_texture', 'straight', 0),
    ('photo_shared_hair_texture', 'wavy', 1),
    ('photo_shared_hair_texture', 'curly', 2),
    ('photo_shared_hair_texture', 'layered', 3);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_hair_color' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_hair_color', 'blonde', 0),
    ('photo_shared_hair_color', 'brunette', 1),
    ('photo_shared_hair_color', 'black', 2),
    ('photo_shared_hair_color', 'red', 3),
    ('photo_shared_hair_color', 'auburn', 4),
    ('photo_shared_hair_color', 'chestnut', 5),
    ('photo_shared_hair_color', 'platinum', 6),
    ('photo_shared_hair_color', 'ginger', 7),
    ('photo_shared_hair_color', 'strawberry blonde', 8);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_smartphone_color' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_smartphone_color', 'white', 0),
    ('photo_shared_smartphone_color', 'black', 1),
    ('photo_shared_smartphone_color', 'silver', 2),
    ('photo_shared_smartphone_color', 'gold', 3),
    ('photo_shared_smartphone_color', 'rose gold', 4),
    ('photo_shared_smartphone_color', 'blue', 5),
    ('photo_shared_smartphone_color', 'red', 6),
    ('photo_shared_smartphone_color', 'green', 7),
    ('photo_shared_smartphone_color', 'purple', 8),
    ('photo_shared_smartphone_color', 'gray', 9);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_camera_block' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_camera_block', 'Casual lifestyle photography. Soft natural window light from the left. Warm color grading, subtle film grain, 35mm lens, shallow depth of field.', 0),
    ('photo_shared_camera_block', 'Contemporary editorial. Bright diffused overhead light. Crisp sharp details, clean high-key palette, 50mm lens, airy magazine aesthetic.', 1),
    ('photo_shared_camera_block', 'Cinematic portrait. Warm golden sidelight with soft shadows. 85mm lens, creamy bokeh, rich warm tones, subtle filmic contrast.', 2);
  END IF;
END $$;

-- Шаблон сцены: комната с зеркалом (низ)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_bottom_room_mirror') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_bottom_room_mirror',
     'Generate an image of a young Slavic woman with light tan skin taking a mirror selfie.
She holds a {photo_shared_smartphone_color} smartphone at cheek level, partially revealing her face.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair
and wears a {photo_bottom_room_mirror_upper_color} {photo_bottom_room_mirror_upper_garment}.

Use Image A as the exact bottom garment she is wearing —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not invent or substitute the bottom garment.

The setting is a bright minimalist room with {photo_bottom_room_mirror_walls_color} walls,
{photo_bottom_room_mirror_flooring_material} hardwood floor, and a {photo_bottom_room_mirror_mirror_style} full-length mirror.
The room includes {photo_bottom_room_mirror_interior_details}.

{photo_shared_camera_block}

Keep the full body visible from head to toe.
No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «низ» — комната с зеркалом. Плейсхолдеры: photo_shared_hair_*, photo_shared_smartphone_color, photo_shared_camera_block, photo_bottom_room_mirror_upper_*, photo_bottom_room_mirror_walls_color, photo_bottom_room_mirror_flooring_material, photo_bottom_room_mirror_mirror_style, photo_bottom_room_mirror_interior_details.',
     1000);
  END IF;
END $$;

-- Переменные сцены: комната с зеркалом
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_room_mirror_upper_color' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_room_mirror_upper_color', 'lavender', 0),
    ('photo_bottom_room_mirror_upper_color', 'pink', 1),
    ('photo_bottom_room_mirror_upper_color', 'light blue', 2),
    ('photo_bottom_room_mirror_upper_color', 'mint green', 3),
    ('photo_bottom_room_mirror_upper_color', 'peach', 4),
    ('photo_bottom_room_mirror_upper_color', 'light yellow', 5),
    ('photo_bottom_room_mirror_upper_color', 'lilac', 6),
    ('photo_bottom_room_mirror_upper_color', 'sky blue', 7),
    ('photo_bottom_room_mirror_upper_color', 'soft coral', 8),
    ('photo_bottom_room_mirror_upper_color', 'pale pink', 9);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_room_mirror_upper_garment' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_room_mirror_upper_garment', 'blouse', 0),
    ('photo_bottom_room_mirror_upper_garment', 'shirt', 1),
    ('photo_bottom_room_mirror_upper_garment', 't-shirt', 2),
    ('photo_bottom_room_mirror_upper_garment', 'tank top', 3),
    ('photo_bottom_room_mirror_upper_garment', 'crop top', 4),
    ('photo_bottom_room_mirror_upper_garment', 'sweater', 5),
    ('photo_bottom_room_mirror_upper_garment', 'cardigan', 6),
    ('photo_bottom_room_mirror_upper_garment', 'blazer', 7),
    ('photo_bottom_room_mirror_upper_garment', 'hoodie', 8);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_room_mirror_walls_color' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_room_mirror_walls_color', 'light gray', 0),
    ('photo_bottom_room_mirror_walls_color', 'white', 1),
    ('photo_bottom_room_mirror_walls_color', 'beige', 2),
    ('photo_bottom_room_mirror_walls_color', 'pale blue', 3),
    ('photo_bottom_room_mirror_walls_color', 'soft pink', 4),
    ('photo_bottom_room_mirror_walls_color', 'cream', 5),
    ('photo_bottom_room_mirror_walls_color', 'light taupe', 6),
    ('photo_bottom_room_mirror_walls_color', 'off-white', 7),
    ('photo_bottom_room_mirror_walls_color', 'light lavender', 8);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_room_mirror_flooring_material' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_room_mirror_flooring_material', 'oak', 0),
    ('photo_bottom_room_mirror_flooring_material', 'maple', 1),
    ('photo_bottom_room_mirror_flooring_material', 'walnut', 2),
    ('photo_bottom_room_mirror_flooring_material', 'cherry', 3),
    ('photo_bottom_room_mirror_flooring_material', 'bamboo', 4),
    ('photo_bottom_room_mirror_flooring_material', 'hickory', 5),
    ('photo_bottom_room_mirror_flooring_material', 'pine', 6),
    ('photo_bottom_room_mirror_flooring_material', 'ash', 7),
    ('photo_bottom_room_mirror_flooring_material', 'beech', 8);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_room_mirror_mirror_style' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_room_mirror_mirror_style', 'wooden-framed', 0),
    ('photo_bottom_room_mirror_mirror_style', 'ornate', 1),
    ('photo_bottom_room_mirror_mirror_style', 'rustic', 2),
    ('photo_bottom_room_mirror_mirror_style', 'modern', 3),
    ('photo_bottom_room_mirror_mirror_style', 'vintage', 4),
    ('photo_bottom_room_mirror_mirror_style', 'minimalist', 5),
    ('photo_bottom_room_mirror_mirror_style', 'carved', 6),
    ('photo_bottom_room_mirror_mirror_style', 'gilded', 7),
    ('photo_bottom_room_mirror_mirror_style', 'simple', 8);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_room_mirror_interior_details' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_room_mirror_interior_details', 'a small white bedside table with a potted plant and a scented candle', 0),
    ('photo_bottom_room_mirror_interior_details', 'a light wooden shelf with folded towels and a small vase of dried flowers', 1),
    ('photo_bottom_room_mirror_interior_details', 'a minimal desk with a laptop and a ceramic mug in the background', 2),
    ('photo_bottom_room_mirror_interior_details', 'a soft beige armchair with a folded throw blanket in the corner', 3),
    ('photo_bottom_room_mirror_interior_details', 'a low wooden bench with a woven basket and a few books beside the mirror', 4),
    ('photo_bottom_room_mirror_interior_details', 'a windowsill with sheer curtains, soft daylight casting gentle shadows', 5),
    ('photo_bottom_room_mirror_interior_details', 'a coat rack near the wall with a tote bag and a light jacket hanging', 6),
    ('photo_bottom_room_mirror_interior_details', 'a small round rug and a floor lamp with a warm-toned shade beside the mirror', 7);
  END IF;
END $$;

-- ============================================================
-- Оставшиеся 6 сцен: fitting_room, flat_lay, hotel, mall, sitting, street
-- ============================================================

-- Добавляем сцены по одной (идемпотентно)
DO $$ BEGIN
  INSERT INTO prompt_list_items (list_key, value, sort_order)
  SELECT v.list_key, v.value, v.sort_order
  FROM (VALUES
    ('photo_bottom_scenes'::text, 'fitting_room'::text, 1::integer),
    ('photo_bottom_scenes'::text, 'flat_lay'::text,     2::integer),
    ('photo_bottom_scenes'::text, 'hotel'::text,        3::integer),
    ('photo_bottom_scenes'::text, 'mall'::text,         4::integer),
    ('photo_bottom_scenes'::text, 'sitting'::text,      5::integer),
    ('photo_bottom_scenes'::text, 'street'::text,       6::integer)
  ) AS v(list_key, value, sort_order)
  WHERE NOT EXISTS (
    SELECT 1 FROM prompt_list_items p
    WHERE p.list_key = v.list_key AND p.value = v.value
  );
END $$;

-- Новые общие переменные (skin_tone, upper_color/garment, shoes, bag, jewelry)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_skin_tone' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_skin_tone', 'light tan', 0),
    ('photo_shared_skin_tone', 'fair', 1),
    ('photo_shared_skin_tone', 'warm ivory', 2),
    ('photo_shared_skin_tone', 'golden', 3);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_upper_color' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_upper_color', 'white', 0),
    ('photo_shared_upper_color', 'lavender', 1),
    ('photo_shared_upper_color', 'pink', 2),
    ('photo_shared_upper_color', 'light blue', 3),
    ('photo_shared_upper_color', 'mint green', 4),
    ('photo_shared_upper_color', 'peach', 5),
    ('photo_shared_upper_color', 'light yellow', 6),
    ('photo_shared_upper_color', 'sky blue', 7),
    ('photo_shared_upper_color', 'soft coral', 8),
    ('photo_shared_upper_color', 'pale pink', 9),
    ('photo_shared_upper_color', 'beige', 10);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_upper_garment' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_upper_garment', 'blouse', 0),
    ('photo_shared_upper_garment', 'shirt', 1),
    ('photo_shared_upper_garment', 't-shirt', 2),
    ('photo_shared_upper_garment', 'tank top', 3),
    ('photo_shared_upper_garment', 'crop top', 4),
    ('photo_shared_upper_garment', 'sweater', 5),
    ('photo_shared_upper_garment', 'cardigan', 6),
    ('photo_shared_upper_garment', 'blazer', 7),
    ('photo_shared_upper_garment', 'hoodie', 8);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_shoes' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_shoes', 'white sneakers', 0),
    ('photo_shared_shoes', 'beige sandals', 1),
    ('photo_shared_shoes', 'black loafers', 2),
    ('photo_shared_shoes', 'white ballet flats', 3),
    ('photo_shared_shoes', 'chunky white sneakers', 4),
    ('photo_shared_shoes', 'nude heels', 5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_bag' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_bag', 'small red crossbody bag', 0),
    ('photo_shared_bag', 'beige tote bag', 1),
    ('photo_shared_bag', 'white mini bag', 2),
    ('photo_shared_bag', 'black shoulder bag', 3),
    ('photo_shared_bag', 'no bag', 4);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_jewelry' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_jewelry', 'wearing a pearl necklace and small stud earrings', 0),
    ('photo_shared_jewelry', 'wearing a delicate gold chain necklace', 1),
    ('photo_shared_jewelry', 'wearing layered thin gold chains', 2),
    ('photo_shared_jewelry', 'no jewelry', 3);
  END IF;
END $$;

-- ============================================================
-- Сцена: примерочная (fitting_room)
-- ============================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_bottom_fitting_room') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_bottom_fitting_room',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
taking a mirror selfie inside a fitting room.
She holds a {photo_shared_smartphone_color} smartphone at cheek level,
partially revealing her face.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair
and wears a {photo_shared_upper_color} {photo_shared_upper_garment}.

Use Image A as the exact bottom garment she is wearing —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not invent or substitute the bottom garment.

The setting is a compact fitting room cubicle with white walls,
a {photo_bottom_fitting_room_curtain_color} curtain partially drawn, a small bench,
metal hooks on the wall with {photo_bottom_fitting_room_hanging_items} hanging on them.
A frameless mirror on the wall reflects the scene.

{photo_shared_camera_block}

Keep the full body visible from head to toe.
No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «низ» — примерочная. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_smartphone_color, photo_shared_upper_*, photo_shared_camera_block, photo_bottom_fitting_room_curtain_color, photo_bottom_fitting_room_hanging_items.',
     1001);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_fitting_room_curtain_color' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_fitting_room_curtain_color', 'purple', 0),
    ('photo_bottom_fitting_room_curtain_color', 'white', 1),
    ('photo_bottom_fitting_room_curtain_color', 'beige', 2),
    ('photo_bottom_fitting_room_curtain_color', 'gray', 3),
    ('photo_bottom_fitting_room_curtain_color', 'black', 4),
    ('photo_bottom_fitting_room_curtain_color', 'dusty pink', 5),
    ('photo_bottom_fitting_room_curtain_color', 'navy', 6);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_fitting_room_hanging_items' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_fitting_room_hanging_items', 'a denim jacket and a tote bag', 0),
    ('photo_bottom_fitting_room_hanging_items', 'two blouses and a small handbag', 1),
    ('photo_bottom_fitting_room_hanging_items', 'a light cardigan and a shopping bag', 2),
    ('photo_bottom_fitting_room_hanging_items', 'one dress and a crossbody bag', 3),
    ('photo_bottom_fitting_room_hanging_items', 'just a shopping bag, hooks otherwise empty', 4);
  END IF;
END $$;

-- ============================================================
-- Сцена: флэтлэй (flat_lay)
-- ============================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_bottom_flat_lay') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_bottom_flat_lay',
     'Generate a flat lay photo shot from directly above.
Image A is the central garment of the composition —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not substitute or alter the garment.

The flat lay also includes a {photo_bottom_flat_lay_upper_color} {photo_bottom_flat_lay_upper_garment} neatly
folded or arranged beside the main garment. {photo_bottom_flat_lay_accessories}

{photo_bottom_flat_lay_surface_and_palette}

{photo_bottom_flat_lay_composition_style}

{photo_bottom_flat_lay_props}

Overhead shot, straight top-down angle, no human subject.
{photo_bottom_flat_lay_lighting}
No watermark. No text overlay.',
     'Lifestyle-фото «низ» — флэтлэй. Плейсхолдеры: photo_bottom_flat_lay_upper_color, photo_bottom_flat_lay_upper_garment, photo_bottom_flat_lay_accessories, photo_bottom_flat_lay_surface_and_palette, photo_bottom_flat_lay_composition_style, photo_bottom_flat_lay_props, photo_bottom_flat_lay_lighting. Без модели.',
     1002);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_flat_lay_upper_color' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_flat_lay_upper_color', 'white', 0),
    ('photo_bottom_flat_lay_upper_color', 'lavender', 1),
    ('photo_bottom_flat_lay_upper_color', 'pink', 2),
    ('photo_bottom_flat_lay_upper_color', 'light blue', 3),
    ('photo_bottom_flat_lay_upper_color', 'mint green', 4),
    ('photo_bottom_flat_lay_upper_color', 'peach', 5),
    ('photo_bottom_flat_lay_upper_color', 'light yellow', 6),
    ('photo_bottom_flat_lay_upper_color', 'sky blue', 7),
    ('photo_bottom_flat_lay_upper_color', 'soft coral', 8),
    ('photo_bottom_flat_lay_upper_color', 'pale pink', 9),
    ('photo_bottom_flat_lay_upper_color', 'beige', 10);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_flat_lay_upper_garment' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_flat_lay_upper_garment', 'blouse', 0),
    ('photo_bottom_flat_lay_upper_garment', 'shirt', 1),
    ('photo_bottom_flat_lay_upper_garment', 't-shirt', 2),
    ('photo_bottom_flat_lay_upper_garment', 'tank top', 3),
    ('photo_bottom_flat_lay_upper_garment', 'crop top', 4),
    ('photo_bottom_flat_lay_upper_garment', 'sweater', 5),
    ('photo_bottom_flat_lay_upper_garment', 'cardigan', 6),
    ('photo_bottom_flat_lay_upper_garment', 'blazer', 7),
    ('photo_bottom_flat_lay_upper_garment', 'hoodie', 8);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_flat_lay_accessories' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_flat_lay_accessories', 'A pair of white sneakers and a small white mini bag placed nearby', 0),
    ('photo_bottom_flat_lay_accessories', 'A pair of beige sandals and a beige tote bag placed nearby', 1),
    ('photo_bottom_flat_lay_accessories', 'A pair of nude heels and a black shoulder bag placed nearby', 2),
    ('photo_bottom_flat_lay_accessories', 'A pair of white ballet flats and a small red crossbody bag nearby', 3),
    ('photo_bottom_flat_lay_accessories', 'No shoes, only a delicate gold chain necklace and small earrings', 4),
    ('photo_bottom_flat_lay_accessories', 'No shoes, only a pearl necklace and stud earrings arranged neatly', 5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_flat_lay_surface_and_palette' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_flat_lay_surface_and_palette', 'Laid on a white marble surface with soft grey veining — light pastel and white tones, clean and fresh palette', 0),
    ('photo_bottom_flat_lay_surface_and_palette', 'Laid on a light oak wooden surface with natural grain — warm neutral tones, cream and beige palette', 1),
    ('photo_bottom_flat_lay_surface_and_palette', 'Laid on a white linen bedsheet with subtle fabric texture — soft white and ivory tones, airy minimal palette', 2),
    ('photo_bottom_flat_lay_surface_and_palette', 'Laid on a light beige linen fabric surface — warm pastel tones, soft and natural palette', 3),
    ('photo_bottom_flat_lay_surface_and_palette', 'Laid on a pale pink surface with smooth matte finish — blush and rose tones, feminine soft palette', 4),
    ('photo_bottom_flat_lay_surface_and_palette', 'Laid on a light grey concrete surface with fine texture — cool neutral tones, clean modern palette', 5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_flat_lay_composition_style' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_flat_lay_composition_style', 'Neatly arranged in a symmetrical flat lay, items evenly spaced with clear negative space around each piece', 0),
    ('photo_bottom_flat_lay_composition_style', 'Casually arranged in a relaxed organic layout, items slightly overlapping, natural effortless feel', 1),
    ('photo_bottom_flat_lay_composition_style', 'Styled in a structured grid composition, each item in its own visual zone, clean editorial look', 2),
    ('photo_bottom_flat_lay_composition_style', 'Arranged in a diagonal flowing composition, items leading the eye from top-left to bottom-right', 3);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_flat_lay_props' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_flat_lay_props', 'A small glass perfume bottle, two or three fresh white flowers, and a pair of delicate gold earrings scattered naturally', 0),
    ('photo_bottom_flat_lay_props', 'A few dried flowers, a small ceramic candle, and a folded kraft paper shopping bag', 1),
    ('photo_bottom_flat_lay_props', 'An open paperback book, a simple gold ring, and a small sprig of eucalyptus', 2),
    ('photo_bottom_flat_lay_props', 'A pair of sunglasses, a tube of lip gloss, and a few loose petals from a white flower', 3),
    ('photo_bottom_flat_lay_props', 'Minimal props — only a single fresh flower and one small earring, clean and uncluttered composition', 4),
    ('photo_bottom_flat_lay_props', 'A small woven pouch, a thin gold bracelet, and two or three small smooth stones', 5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_flat_lay_lighting' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_flat_lay_lighting', 'Soft diffused natural daylight from a nearby window, no harsh shadows, even and clean', 0),
    ('photo_bottom_flat_lay_lighting', 'Bright studio-style overhead light, crisp and high-key, white and airy feel', 1),
    ('photo_bottom_flat_lay_lighting', 'Warm soft ambient light, gentle shadows, cozy and intimate tone', 2);
  END IF;
END $$;

-- ============================================================
-- Сцена: отель (hotel)
-- ============================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_bottom_hotel') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_bottom_hotel',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
taking a mirror selfie in a hotel lobby.
She holds a {photo_shared_smartphone_color} smartphone at cheek level,
partially revealing her face.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair
and wears a {photo_shared_upper_color} {photo_shared_upper_garment}.

Use Image A as the exact bottom garment she is wearing —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not invent or substitute the bottom garment.

She is standing in front of a {photo_bottom_hotel_mirror_style} full-length mirror
in a {photo_bottom_hotel_style} hotel lobby with {photo_bottom_hotel_flooring_material} flooring.
{photo_bottom_hotel_lobby_details}

{photo_bottom_hotel_lighting}

{photo_shared_camera_block}

Keep the full body visible from head to toe.
No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «низ» — отель. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_smartphone_color, photo_shared_upper_*, photo_shared_camera_block, photo_bottom_hotel_mirror_style, photo_bottom_hotel_style, photo_bottom_hotel_flooring_material, photo_bottom_hotel_lobby_details, photo_bottom_hotel_lighting.',
     1003);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_hotel_mirror_style' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_hotel_mirror_style', 'gilded ornate', 0),
    ('photo_bottom_hotel_mirror_style', 'sleek frameless', 1),
    ('photo_bottom_hotel_mirror_style', 'black metal framed', 2),
    ('photo_bottom_hotel_mirror_style', 'marble-trimmed', 3),
    ('photo_bottom_hotel_mirror_style', 'brass-framed', 4),
    ('photo_bottom_hotel_mirror_style', 'minimalist wooden', 5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_hotel_style' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_hotel_style', 'luxury five-star', 0),
    ('photo_bottom_hotel_style', 'boutique designer', 1),
    ('photo_bottom_hotel_style', 'modern business', 2);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_hotel_flooring_material' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_hotel_flooring_material', 'polished white marble', 0),
    ('photo_bottom_hotel_flooring_material', 'dark herringbone parquet', 1),
    ('photo_bottom_hotel_flooring_material', 'large format stone tile', 2),
    ('photo_bottom_hotel_flooring_material', 'warm oak hardwood', 3),
    ('photo_bottom_hotel_flooring_material', 'black and white checkered marble', 4);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_hotel_lobby_details' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_hotel_lobby_details', 'In the mirror reflection: tall marble columns, crystal chandelier overhead, fresh white flower arrangement on a gold console table nearby', 0),
    ('photo_bottom_hotel_lobby_details', 'In the mirror reflection: grand curved staircase with brass railings, ornate ceiling moldings, warm ambient wall sconces', 1),
    ('photo_bottom_hotel_lobby_details', 'In the mirror reflection: eclectic velvet armchairs in rich jewel tones, abstract art on textured walls, sculptural floor lamp nearby', 2),
    ('photo_bottom_hotel_lobby_details', 'In the mirror reflection: exposed brick accent wall, hanging Edison bulbs, low designer sofa and curated coffee table books', 3),
    ('photo_bottom_hotel_lobby_details', 'In the mirror reflection: sleek reception desk with backlit panels, minimalist seating area, large potted tropical plant in the corner', 4),
    ('photo_bottom_hotel_lobby_details', 'In the mirror reflection: floor-to-ceiling windows with city view, clean concrete walls, geometric pendant lights overhead', 5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_hotel_lighting' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_hotel_lighting', 'Warm ambient hotel lighting, soft golden glow from wall sconces, no harsh shadows, intimate atmosphere', 0),
    ('photo_bottom_hotel_lighting', 'Bright even lobby lighting, clean white light, crisp and airy feel', 1),
    ('photo_bottom_hotel_lighting', 'Mixed natural and artificial light, soft daylight from nearby windows blending with warm interior lights', 2);
  END IF;
END $$;

-- ============================================================
-- Сцена: торговый центр (mall)
-- ============================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_bottom_mall') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_bottom_mall',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
{photo_bottom_mall_shot_type}.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair
and wears a {photo_shared_upper_color} {photo_shared_upper_garment}.

Use Image A as the exact bottom garment she is wearing —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not invent or substitute the bottom garment.

She wears {photo_shared_shoes} and carries {photo_shared_bag}. {photo_shared_jewelry}

{photo_bottom_mall_location} of a {photo_bottom_mall_style} shopping mall.
{photo_bottom_mall_details}

{photo_bottom_mall_lighting}

{photo_shared_camera_block}

Keep the full body visible from head to toe.
No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «низ» — ТЦ. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_upper_*, photo_shared_shoes, photo_shared_bag, photo_shared_jewelry, photo_shared_camera_block, photo_bottom_mall_shot_type, photo_bottom_mall_location, photo_bottom_mall_style, photo_bottom_mall_details, photo_bottom_mall_lighting.',
     1004);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_mall_shot_type' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_mall_shot_type', 'taking a mirror selfie in a fitting room, holding a black smartphone at cheek level, partially revealing her face', 0),
    ('photo_bottom_mall_shot_type', 'walking through the mall in a candid shot, looking ahead naturally', 1),
    ('photo_bottom_mall_shot_type', 'standing relaxed, looking slightly to the side', 2);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_mall_location' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_mall_location', 'inside a bright fitting room with a full-length mirror', 0),
    ('photo_bottom_mall_location', 'in the main corridor', 1),
    ('photo_bottom_mall_location', 'near a glass balustrade overlooking the atrium', 2),
    ('photo_bottom_mall_location', 'on an escalator landing with open mall floors visible behind her', 3),
    ('photo_bottom_mall_location', 'in front of a large store entrance', 4);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_mall_style' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_mall_style', 'mass-market with clean bright interiors, white walls, and simple signage', 0),
    ('photo_bottom_mall_style', 'premium luxury with marble floors, gold accents, and designer storefronts', 1),
    ('photo_bottom_mall_style', 'modern minimalist with concrete, glass, and monochrome palette', 2);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_mall_details' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_mall_details', 'Clean neutral walls, soft warm lighting from above, hook on the wall, shopping bags on the floor beside her', 0),
    ('photo_bottom_mall_details', 'Soft pink walls, ring light reflection visible in the mirror, branded hangers and tissue paper visible in background', 1),
    ('photo_bottom_mall_details', 'Wide bright corridor, blurred shoppers in the far background, polished floor reflecting ceiling lights, store windows on both sides', 2),
    ('photo_bottom_mall_details', 'Quiet section of the mall, no people, clean sightlines, large potted plants and a bench visible in background', 3),
    ('photo_bottom_mall_details', 'Open multi-level atrium visible behind her, soft skylight from above, glass railings and hanging planters on upper floors', 4),
    ('photo_bottom_mall_details', 'Escalator mid-ride, blurred mall floors above and below, warm ambient ceiling lights creating soft depth', 5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_mall_lighting' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_mall_lighting', 'Bright even mall lighting, clean white artificial light, crisp and airy', 0),
    ('photo_bottom_mall_lighting', 'Warm ambient lighting, soft golden tones, intimate feel', 1),
    ('photo_bottom_mall_lighting', 'Mixed natural skylight and artificial light, soft balanced exposure', 2);
  END IF;
END $$;

-- ============================================================
-- Сцена: сидя (sitting)
-- ============================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_bottom_sitting') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_bottom_sitting',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
sitting in a candid lifestyle photo.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair
and wears a {photo_shared_upper_color} {photo_shared_upper_garment}.

Use Image A as the exact bottom garment she is wearing —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not invent or substitute the bottom garment.

She wears {photo_shared_shoes} and carries {photo_shared_bag}. {photo_shared_jewelry}

{photo_bottom_sitting_pose_location}

{photo_bottom_sitting_lighting}

{photo_shared_camera_block}

Keep the full body visible from head to toe.
No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «низ» — сидя. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_upper_*, photo_shared_shoes, photo_shared_bag, photo_shared_jewelry, photo_shared_camera_block, photo_bottom_sitting_pose_location, photo_bottom_sitting_lighting.',
     1005);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_sitting_pose_location' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_sitting_pose_location', 'She is sitting on stone steps with legs together, slightly angled to the side, hands resting on her knees, looking softly ahead — at the steps of a neoclassical building with large white columns', 0),
    ('photo_bottom_sitting_pose_location', 'She is sitting on a wooden park bench with one leg crossed over the other, leaning back slightly, relaxed natural expression — on a shaded park path under tall trees with dappled light', 1),
    ('photo_bottom_sitting_pose_location', 'She is sitting on the edge of a low stone wall, legs dangling, hands resting beside her, looking down softly — along a quiet cobblestone European street with old facades', 2),
    ('photo_bottom_sitting_pose_location', 'She is sitting cross-legged on the ground, back straight, looking slightly to the side with a relaxed expression — in a botanical garden surrounded by lush greenery and soft light', 3),
    ('photo_bottom_sitting_pose_location', 'She is perched on a windowsill with legs to one side, leaning gently against the frame, looking outside — by a large window with sheer curtains and soft indoor daylight', 4),
    ('photo_bottom_sitting_pose_location', 'She is sitting on a low cafe ledge or step, legs together, relaxed candid pose, looking slightly away — at a bright cafe terrace with small round tables nearby', 5),
    ('photo_bottom_sitting_pose_location', 'She is sitting on a stone ledge of a city bridge, legs to the side, one hand resting on the railing, gazing at the view — on a city bridge with iron railings and soft river light behind her', 6);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_sitting_lighting' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_sitting_lighting', 'Overcast soft daylight, no harsh shadows, even diffused light', 0),
    ('photo_bottom_sitting_lighting', 'Golden hour warm sidelight, long soft shadows, rich warm tones', 1),
    ('photo_bottom_sitting_lighting', 'Bright midday sun, crisp light, slight high-contrast shadows', 2),
    ('photo_bottom_sitting_lighting', 'Soft natural window light, warm and diffused, indoor setting', 3);
  END IF;
END $$;

-- ============================================================
-- Сцена: улица (street)
-- ============================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_bottom_street') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_bottom_street',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
in a candid street style photo.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair.
She wears a {photo_shared_upper_color} {photo_shared_upper_garment} and uses Image A as her exact
bottom garment — reproduce its silhouette, fabric, color, texture,
and pattern precisely. Do not invent or substitute the bottom garment.
She wears {photo_shared_shoes} and carries {photo_shared_bag}. {photo_shared_jewelry}

She is {photo_bottom_street_pose} at {photo_bottom_street_location}.

{photo_bottom_street_lighting}

{photo_shared_camera_block}

No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «низ» — улица. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_upper_*, photo_shared_shoes, photo_shared_bag, photo_shared_jewelry, photo_shared_camera_block, photo_bottom_street_pose, photo_bottom_street_location, photo_bottom_street_lighting.',
     1006);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_street_pose' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_street_pose', 'standing slightly turned looking away from the camera', 0),
    ('photo_bottom_street_pose', 'walking naturally looking ahead', 1),
    ('photo_bottom_street_pose', 'leaning against a wall with a relaxed pose', 2),
    ('photo_bottom_street_pose', 'sitting on steps looking down softly', 3),
    ('photo_bottom_street_pose', 'standing looking over her shoulder', 4);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_street_location' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_street_location', 'the steps of a neoclassical building with large white classical columns', 0),
    ('photo_bottom_street_location', 'a cobblestone European street with old facades and warm storefronts', 1),
    ('photo_bottom_street_location', 'a shaded park alley with tall trees and dappled light on the path', 2),
    ('photo_bottom_street_location', 'a sunlit cafe terrace with small round tables and wicker chairs', 3),
    ('photo_bottom_street_location', 'an arched stone courtyard with climbing plants and warm stone walls', 4),
    ('photo_bottom_street_location', 'a city bridge with iron railings and soft river light in the background', 5),
    ('photo_bottom_street_location', 'a botanical garden path surrounded by lush greenery and soft light', 6),
    ('photo_bottom_street_location', 'an old European street with colorful building facades and flower boxes', 7);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_bottom_street_lighting' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_bottom_street_lighting', 'Overcast soft daylight, no harsh shadows, even diffused light', 0),
    ('photo_bottom_street_lighting', 'Golden hour warm sidelight, long soft shadows, rich warm tones', 1),
    ('photo_bottom_street_lighting', 'Bright midday sun, crisp light, slight high-contrast shadows', 2),
    ('photo_bottom_street_lighting', 'Cloudy diffused light, cool neutral tones, flat even exposure', 3);
  END IF;
END $$;

-- ============================================================
-- Lifestyle-фото: сцены и переменные для «верх» (photo_top)
-- ============================================================

-- Список сцен
DO $$ BEGIN
  INSERT INTO prompt_list_items (list_key, value, sort_order)
  SELECT v.list_key, v.value, v.sort_order
  FROM (VALUES
    ('photo_top_scenes'::text, 'room_mirror'::text,  0::integer),
    ('photo_top_scenes'::text, 'fitting_room'::text, 1::integer),
    ('photo_top_scenes'::text, 'flat_lay'::text,     2::integer),
    ('photo_top_scenes'::text, 'hotel'::text,        3::integer),
    ('photo_top_scenes'::text, 'mall'::text,         4::integer),
    ('photo_top_scenes'::text, 'sitting'::text,      5::integer),
    ('photo_top_scenes'::text, 'street'::text,       6::integer)
  ) AS v(list_key, value, sort_order)
  WHERE NOT EXISTS (
    SELECT 1 FROM prompt_list_items p
    WHERE p.list_key = v.list_key AND p.value = v.value
  );
END $$;

-- Общие переменные нижнего гардероба
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_lower_color' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_lower_color', 'white',      0),
    ('photo_shared_lower_color', 'black',      1),
    ('photo_shared_lower_color', 'beige',      2),
    ('photo_shared_lower_color', 'light blue', 3),
    ('photo_shared_lower_color', 'dark blue',  4),
    ('photo_shared_lower_color', 'khaki',      5),
    ('photo_shared_lower_color', 'grey',       6),
    ('photo_shared_lower_color', 'brown',      7),
    ('photo_shared_lower_color', 'cream',      8),
    ('photo_shared_lower_color', 'olive',      9);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_shared_lower_garment' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_shared_lower_garment', 'mini skirt',         0),
    ('photo_shared_lower_garment', 'midi skirt',         1),
    ('photo_shared_lower_garment', 'straight-leg jeans', 2),
    ('photo_shared_lower_garment', 'skinny jeans',       3),
    ('photo_shared_lower_garment', 'shorts',             4),
    ('photo_shared_lower_garment', 'tailored trousers',  5),
    ('photo_shared_lower_garment', 'wide-leg pants',     6),
    ('photo_shared_lower_garment', 'fitted trousers',    7),
    ('photo_shared_lower_garment', 'cargo trousers',     8),
    ('photo_shared_lower_garment', 'linen trousers',     9),
    ('photo_shared_lower_garment', 'sweatpants',         10),
    ('photo_shared_lower_garment', 'flowy skirt',        11);
  END IF;
END $$;

-- Шаблон: комната с зеркалом
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_top_room_mirror') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_top_room_mirror',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
taking a mirror selfie.
She holds a {photo_shared_smartphone_color} smartphone at cheek level,
partially revealing her face.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair
and wears a {photo_shared_lower_color} {photo_shared_lower_garment}.

Use Image A as the exact top garment she is wearing —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not invent or substitute the top garment.

The setting is a bright minimalist room with {photo_top_room_mirror_walls_color} walls,
{photo_top_room_mirror_flooring_material} hardwood floor, and a {photo_top_room_mirror_mirror_style} full-length mirror.
The room includes {photo_top_room_mirror_interior_details}.

{photo_shared_camera_block}

Keep the full body visible from head to toe.
No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «верх» — комната с зеркалом. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_smartphone_color, photo_shared_lower_color, photo_shared_lower_garment, photo_shared_camera_block, photo_top_room_mirror_walls_color, photo_top_room_mirror_flooring_material, photo_top_room_mirror_mirror_style, photo_top_room_mirror_interior_details.',
     2000);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_room_mirror_walls_color' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_room_mirror_walls_color', 'light gray',     0),
    ('photo_top_room_mirror_walls_color', 'white',          1),
    ('photo_top_room_mirror_walls_color', 'beige',          2),
    ('photo_top_room_mirror_walls_color', 'pale blue',      3),
    ('photo_top_room_mirror_walls_color', 'soft pink',      4),
    ('photo_top_room_mirror_walls_color', 'cream',          5),
    ('photo_top_room_mirror_walls_color', 'light taupe',    6),
    ('photo_top_room_mirror_walls_color', 'off-white',      7),
    ('photo_top_room_mirror_walls_color', 'light lavender', 8);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_room_mirror_flooring_material' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_room_mirror_flooring_material', 'oak',    0),
    ('photo_top_room_mirror_flooring_material', 'maple',  1),
    ('photo_top_room_mirror_flooring_material', 'walnut', 2),
    ('photo_top_room_mirror_flooring_material', 'cherry', 3),
    ('photo_top_room_mirror_flooring_material', 'bamboo', 4),
    ('photo_top_room_mirror_flooring_material', 'hickory',5),
    ('photo_top_room_mirror_flooring_material', 'pine',   6),
    ('photo_top_room_mirror_flooring_material', 'ash',    7),
    ('photo_top_room_mirror_flooring_material', 'beech',  8);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_room_mirror_mirror_style' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_room_mirror_mirror_style', 'wooden-framed', 0),
    ('photo_top_room_mirror_mirror_style', 'ornate',        1),
    ('photo_top_room_mirror_mirror_style', 'rustic',        2),
    ('photo_top_room_mirror_mirror_style', 'modern',        3),
    ('photo_top_room_mirror_mirror_style', 'vintage',       4),
    ('photo_top_room_mirror_mirror_style', 'minimalist',    5),
    ('photo_top_room_mirror_mirror_style', 'carved',        6),
    ('photo_top_room_mirror_mirror_style', 'gilded',        7),
    ('photo_top_room_mirror_mirror_style', 'simple',        8);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_room_mirror_interior_details' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_room_mirror_interior_details', 'a small white bedside table with a potted plant and a scented candle',                   0),
    ('photo_top_room_mirror_interior_details', 'a light wooden shelf with folded towels and a small vase of dried flowers',             1),
    ('photo_top_room_mirror_interior_details', 'a minimal desk with a laptop and a ceramic mug in the background',                      2),
    ('photo_top_room_mirror_interior_details', 'a soft beige armchair with a folded throw blanket in the corner',                       3),
    ('photo_top_room_mirror_interior_details', 'a low wooden bench with a woven basket and a few books beside the mirror',               4),
    ('photo_top_room_mirror_interior_details', 'a windowsill with sheer curtains, soft daylight casting gentle shadows',                 5),
    ('photo_top_room_mirror_interior_details', 'a coat rack near the wall with a tote bag and a light jacket hanging',                   6),
    ('photo_top_room_mirror_interior_details', 'a small round rug and a floor lamp with a warm-toned shade beside the mirror',           7);
  END IF;
END $$;

-- Шаблон: примерочная
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_top_fitting_room') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_top_fitting_room',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
taking a mirror selfie inside a fitting room.
She holds a {photo_shared_smartphone_color} smartphone at cheek level,
partially revealing her face.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair.

Use Image A as the exact top garment she is wearing —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not invent or substitute the top garment.

She wears a {photo_top_fitting_room_lower_garment}.

The setting is a compact fitting room cubicle with white walls,
a {photo_top_fitting_room_curtain_color} curtain partially drawn, a small bench,
metal hooks on the wall with {photo_top_fitting_room_hanging_items} hanging on them.
A frameless mirror on the wall reflects the scene.

{photo_shared_camera_block}

Keep the full body visible from head to toe.
No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «верх» — примерочная. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_smartphone_color, photo_shared_camera_block, photo_top_fitting_room_lower_garment, photo_top_fitting_room_curtain_color, photo_top_fitting_room_hanging_items.',
     2001);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_fitting_room_lower_garment' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_fitting_room_lower_garment', 'white pleated mini skirt',      0),
    ('photo_top_fitting_room_lower_garment', 'black A-line midi skirt',       1),
    ('photo_top_fitting_room_lower_garment', 'light blue straight-leg jeans', 2),
    ('photo_top_fitting_room_lower_garment', 'dark blue skinny jeans',        3),
    ('photo_top_fitting_room_lower_garment', 'denim shorts',                  4),
    ('photo_top_fitting_room_lower_garment', 'beige tailored trousers',       5),
    ('photo_top_fitting_room_lower_garment', 'white wide-leg pants',          6),
    ('photo_top_fitting_room_lower_garment', 'black fitted trousers',         7),
    ('photo_top_fitting_room_lower_garment', 'flowy floral midi skirt',       8),
    ('photo_top_fitting_room_lower_garment', 'khaki cargo trousers',          9),
    ('photo_top_fitting_room_lower_garment', 'light grey sweatpants',         10),
    ('photo_top_fitting_room_lower_garment', 'white linen trousers',          11);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_fitting_room_curtain_color' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_fitting_room_curtain_color', 'purple',    0),
    ('photo_top_fitting_room_curtain_color', 'white',     1),
    ('photo_top_fitting_room_curtain_color', 'beige',     2),
    ('photo_top_fitting_room_curtain_color', 'gray',      3),
    ('photo_top_fitting_room_curtain_color', 'black',     4),
    ('photo_top_fitting_room_curtain_color', 'dusty pink',5),
    ('photo_top_fitting_room_curtain_color', 'navy',      6);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_fitting_room_hanging_items' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_fitting_room_hanging_items', 'a denim jacket and a tote bag',              0),
    ('photo_top_fitting_room_hanging_items', 'two pairs of jeans and a small handbag',     1),
    ('photo_top_fitting_room_hanging_items', 'a light trench coat and a shopping bag',     2),
    ('photo_top_fitting_room_hanging_items', 'one skirt and a crossbody bag',              3),
    ('photo_top_fitting_room_hanging_items', 'just a shopping bag, hooks otherwise empty', 4);
  END IF;
END $$;

-- Шаблон: флэтлэй
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_top_flat_lay') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_top_flat_lay',
     'Generate a flat lay photo shot from directly above.
Image A is the central garment of the composition —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not substitute or alter the garment.

The flat lay also includes a {photo_shared_lower_color} {photo_shared_lower_garment} neatly
folded or arranged beside the main garment. {photo_top_flat_lay_accessories}

{photo_top_flat_lay_surface_and_palette}

{photo_top_flat_lay_composition_style}

{photo_top_flat_lay_props}

Overhead shot, straight top-down angle, no human subject.
{photo_top_flat_lay_lighting}
No watermark. No text overlay.',
     'Lifestyle-фото «верх» — флэтлэй. Плейсхолдеры: photo_shared_lower_color, photo_shared_lower_garment, photo_top_flat_lay_accessories, photo_top_flat_lay_surface_and_palette, photo_top_flat_lay_composition_style, photo_top_flat_lay_props, photo_top_flat_lay_lighting. Без модели.',
     2002);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_flat_lay_accessories' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_flat_lay_accessories', 'A pair of white sneakers and a small white mini bag placed nearby',  0),
    ('photo_top_flat_lay_accessories', 'A pair of beige sandals and a beige tote bag placed nearby',        1),
    ('photo_top_flat_lay_accessories', 'A pair of nude heels and a black shoulder bag placed nearby',       2),
    ('photo_top_flat_lay_accessories', 'A pair of white ballet flats and a small red crossbody bag nearby', 3),
    ('photo_top_flat_lay_accessories', 'No shoes, only a delicate gold chain necklace and small earrings',  4),
    ('photo_top_flat_lay_accessories', 'No shoes, only a pearl necklace and stud earrings arranged neatly', 5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_flat_lay_surface_and_palette' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_flat_lay_surface_and_palette', 'Laid on a white marble surface with soft grey veining — light pastel and white tones, clean and fresh palette',  0),
    ('photo_top_flat_lay_surface_and_palette', 'Laid on a light oak wooden surface with natural grain — warm neutral tones, cream and beige palette',           1),
    ('photo_top_flat_lay_surface_and_palette', 'Laid on a white linen bedsheet with subtle fabric texture — soft white and ivory tones, airy minimal palette',  2),
    ('photo_top_flat_lay_surface_and_palette', 'Laid on a light beige linen fabric surface — warm pastel tones, soft and natural palette',                      3),
    ('photo_top_flat_lay_surface_and_palette', 'Laid on a pale pink surface with smooth matte finish — blush and rose tones, feminine soft palette',            4),
    ('photo_top_flat_lay_surface_and_palette', 'Laid on a light grey concrete surface with fine texture — cool neutral tones, clean modern palette',            5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_flat_lay_composition_style' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_flat_lay_composition_style', 'Neatly arranged in a symmetrical flat lay, items evenly spaced with clear negative space around each piece', 0),
    ('photo_top_flat_lay_composition_style', 'Casually arranged in a relaxed organic layout, items slightly overlapping, natural effortless feel',          1),
    ('photo_top_flat_lay_composition_style', 'Styled in a structured grid composition, each item in its own visual zone, clean editorial look',            2),
    ('photo_top_flat_lay_composition_style', 'Arranged in a diagonal flowing composition, items leading the eye from top-left to bottom-right',            3);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_flat_lay_props' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_flat_lay_props', 'A small glass perfume bottle, two or three fresh white flowers, and a pair of delicate gold earrings scattered naturally', 0),
    ('photo_top_flat_lay_props', 'A few dried flowers, a small ceramic candle, and a folded kraft paper shopping bag',                                      1),
    ('photo_top_flat_lay_props', 'An open paperback book, a simple gold ring, and a small sprig of eucalyptus',                                             2),
    ('photo_top_flat_lay_props', 'A pair of sunglasses, a tube of lip gloss, and a few loose petals from a white flower',                                   3),
    ('photo_top_flat_lay_props', 'Minimal props — only a single fresh flower and one small earring, clean and uncluttered composition',                     4),
    ('photo_top_flat_lay_props', 'A small woven pouch, a thin gold bracelet, and two or three small smooth stones',                                         5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_flat_lay_lighting' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_flat_lay_lighting', 'Soft diffused natural daylight from a nearby window, no harsh shadows, even and clean', 0),
    ('photo_top_flat_lay_lighting', 'Bright studio-style overhead light, crisp and high-key, white and airy feel',           1),
    ('photo_top_flat_lay_lighting', 'Warm soft ambient light, gentle shadows, cozy and intimate tone',                       2);
  END IF;
END $$;

-- Шаблон: отель
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_top_hotel') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_top_hotel',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
taking a mirror selfie in a hotel lobby.
She holds a {photo_shared_smartphone_color} smartphone at cheek level,
partially revealing her face.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair.

Use Image A as the exact top garment she is wearing —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not invent or substitute the top garment.

She wears a {photo_shared_lower_color} {photo_shared_lower_garment}.

She is standing in front of a {photo_top_hotel_mirror_style} full-length mirror.
{photo_top_hotel_lobby_details}

{photo_top_hotel_lighting}

{photo_shared_camera_block}

Keep the full body visible from head to toe.
No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «верх» — отель. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_smartphone_color, photo_shared_lower_color, photo_shared_lower_garment, photo_shared_camera_block, photo_top_hotel_mirror_style, photo_top_hotel_lobby_details, photo_top_hotel_lighting.',
     2003);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_hotel_mirror_style' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_hotel_mirror_style', 'gilded ornate',      0),
    ('photo_top_hotel_mirror_style', 'sleek frameless',    1),
    ('photo_top_hotel_mirror_style', 'black metal framed', 2),
    ('photo_top_hotel_mirror_style', 'marble-trimmed',     3),
    ('photo_top_hotel_mirror_style', 'brass-framed',       4),
    ('photo_top_hotel_mirror_style', 'minimalist wooden',  5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_hotel_lobby_details' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_hotel_lobby_details', 'Luxury five-star hotel lobby with polished white marble flooring. In the mirror reflection: tall marble columns, crystal chandelier overhead, fresh white flower arrangement on a gold console table nearby',                         0),
    ('photo_top_hotel_lobby_details', 'Luxury five-star hotel lobby with black and white checkered marble flooring. In the mirror reflection: grand curved staircase with brass railings, ornate ceiling moldings, warm ambient wall sconces',                             1),
    ('photo_top_hotel_lobby_details', 'Boutique designer hotel lobby with dark herringbone parquet flooring. In the mirror reflection: eclectic velvet armchairs in rich jewel tones, abstract art on textured walls, sculptural floor lamp nearby',                       2),
    ('photo_top_hotel_lobby_details', 'Boutique designer hotel lobby with warm oak hardwood flooring. In the mirror reflection: exposed brick accent wall, hanging Edison bulbs, low designer sofa and curated coffee table books',                                        3),
    ('photo_top_hotel_lobby_details', 'Modern business hotel lobby with large format stone tile flooring. In the mirror reflection: sleek reception desk with backlit panels, minimalist seating area, large potted tropical plant in the corner',                         4),
    ('photo_top_hotel_lobby_details', 'Modern business hotel lobby with polished white marble flooring. In the mirror reflection: floor-to-ceiling windows with city view, clean concrete walls, geometric pendant lights overhead',                                       5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_hotel_lighting' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_hotel_lighting', 'Warm ambient hotel lighting, soft golden glow from wall sconces, no harsh shadows, intimate atmosphere', 0),
    ('photo_top_hotel_lighting', 'Bright even lobby lighting, clean white light, crisp and airy feel',                                     1),
    ('photo_top_hotel_lighting', 'Mixed natural and artificial light, soft daylight from nearby windows blending with warm interior lights',2);
  END IF;
END $$;

-- Шаблон: торговый центр
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_top_mall') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_top_mall',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
{photo_top_mall_shot_type}.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair
and wears a {photo_shared_lower_color} {photo_shared_lower_garment}.

Use Image A as the exact top garment she is wearing —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not invent or substitute the top garment.

She wears {photo_shared_shoes} and carries {photo_shared_bag}. {photo_shared_jewelry}

{photo_top_mall_location} of a {photo_top_mall_style} shopping mall.
{photo_top_mall_details}

{photo_top_mall_lighting}

{photo_shared_camera_block}

Keep the full body visible from head to toe.
No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «верх» — ТЦ. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_lower_color, photo_shared_lower_garment, photo_shared_shoes, photo_shared_bag, photo_shared_jewelry, photo_shared_camera_block, photo_top_mall_shot_type, photo_top_mall_location, photo_top_mall_style, photo_top_mall_details, photo_top_mall_lighting.',
     2004);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_mall_shot_type' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_mall_shot_type', 'taking a mirror selfie in a fitting room, holding a black smartphone at cheek level, partially revealing her face', 0),
    ('photo_top_mall_shot_type', 'walking through the mall in a candid shot, looking ahead naturally',                                                 1),
    ('photo_top_mall_shot_type', 'standing relaxed, looking slightly to the side',                                                                     2);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_mall_location' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_mall_location', 'inside a bright fitting room with a full-length mirror',               0),
    ('photo_top_mall_location', 'in the main corridor',                                                 1),
    ('photo_top_mall_location', 'near a glass balustrade overlooking the atrium',                       2),
    ('photo_top_mall_location', 'on an escalator landing with open mall floors visible behind her',     3),
    ('photo_top_mall_location', 'in front of a large store entrance',                                   4);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_mall_style' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_mall_style', 'mass-market with clean bright interiors, white walls, and simple signage',  0),
    ('photo_top_mall_style', 'premium luxury with marble floors, gold accents, and designer storefronts', 1),
    ('photo_top_mall_style', 'modern minimalist with concrete, glass, and monochrome palette',            2);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_mall_details' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_mall_details', 'Clean neutral walls, soft warm lighting from above, hook on the wall, shopping bags on the floor beside her',                                  0),
    ('photo_top_mall_details', 'Soft pink walls, ring light reflection visible in the mirror, branded hangers and tissue paper visible in background',                         1),
    ('photo_top_mall_details', 'Wide bright corridor, blurred shoppers in the far background, polished floor reflecting ceiling lights, store windows on both sides',          2),
    ('photo_top_mall_details', 'Quiet section of the mall, no people, clean sightlines, large potted plants and a bench visible in background',                               3),
    ('photo_top_mall_details', 'Open multi-level atrium visible behind her, soft skylight from above, glass railings and hanging planters on upper floors',                   4),
    ('photo_top_mall_details', 'Escalator mid-ride, blurred mall floors above and below, warm ambient ceiling lights creating soft depth',                                    5);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_mall_lighting' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_mall_lighting', 'Bright even mall lighting, clean white artificial light, crisp and airy', 0),
    ('photo_top_mall_lighting', 'Warm ambient lighting, soft golden tones, intimate feel',                  1),
    ('photo_top_mall_lighting', 'Mixed natural skylight and artificial light, soft balanced exposure',      2);
  END IF;
END $$;

-- Шаблон: сидя
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_top_sitting') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_top_sitting',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
sitting in a candid lifestyle photo.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair
and wears a {photo_shared_lower_color} {photo_shared_lower_garment}.

Use Image A as the exact top garment she is wearing —
reproduce its silhouette, fabric, color, texture, and pattern precisely.
Do not invent or substitute the top garment.

She wears {photo_shared_shoes} and carries {photo_shared_bag}. {photo_shared_jewelry}

{photo_top_sitting_pose_location}

{photo_top_sitting_lighting}

{photo_shared_camera_block}

Keep the full body visible from head to toe.
No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «верх» — сидя. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_lower_color, photo_shared_lower_garment, photo_shared_shoes, photo_shared_bag, photo_shared_jewelry, photo_shared_camera_block, photo_top_sitting_pose_location, photo_top_sitting_lighting.',
     2005);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_sitting_pose_location' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_sitting_pose_location', 'She is sitting on stone steps with legs together, slightly angled to the side, hands resting on her knees, looking softly ahead — at the steps of a neoclassical building with large white columns',         0),
    ('photo_top_sitting_pose_location', 'She is sitting on a wooden park bench with one leg crossed over the other, leaning back slightly, relaxed natural expression — on a shaded park path under tall trees with dappled light',                 1),
    ('photo_top_sitting_pose_location', 'She is sitting on the edge of a low stone wall, legs dangling, hands resting beside her, looking down softly — along a quiet cobblestone European street with old facades',                               2),
    ('photo_top_sitting_pose_location', 'She is sitting cross-legged on the ground, back straight, looking slightly to the side with a relaxed expression — in a botanical garden surrounded by lush greenery and soft light',                     3),
    ('photo_top_sitting_pose_location', 'She is perched on a windowsill with legs to one side, leaning gently against the frame, looking outside — by a large window with sheer curtains and soft indoor daylight',                               4),
    ('photo_top_sitting_pose_location', 'She is sitting on a low cafe ledge or step, legs together, relaxed candid pose, looking slightly away — at a bright cafe terrace with small round tables nearby',                                         5),
    ('photo_top_sitting_pose_location', 'She is sitting on a stone ledge of a city bridge, legs to the side, one hand resting on the railing, gazing at the view — on a city bridge with iron railings and soft river light behind her',           6);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_sitting_lighting' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_sitting_lighting', 'Overcast soft daylight, no harsh shadows, even diffused light',     0),
    ('photo_top_sitting_lighting', 'Golden hour warm sidelight, long soft shadows, rich warm tones',    1),
    ('photo_top_sitting_lighting', 'Bright midday sun, crisp light, slight high-contrast shadows',      2),
    ('photo_top_sitting_lighting', 'Soft natural window light, warm and diffused, indoor setting',      3);
  END IF;
END $$;

-- Шаблон: улица
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'photo_top_street') THEN
    INSERT INTO prompt_templates (key, template, description, sort_order) VALUES
    ('photo_top_street',
     'Generate an image of a young Slavic woman with {photo_shared_skin_tone} skin
in a candid street style photo.
She has {photo_shared_hair_length} {photo_shared_hair_texture} {photo_shared_hair_color} hair.
She wears a {photo_shared_lower_color} {photo_shared_lower_garment} and uses Image A as her exact
top garment — reproduce its silhouette, fabric, color, texture,
and pattern precisely. Do not invent or substitute the top garment.
She wears {photo_shared_shoes} and carries {photo_shared_bag}. {photo_shared_jewelry}

She is {photo_top_street_pose} at {photo_top_street_location}.

{photo_top_street_lighting}

{photo_shared_camera_block}

No watermark. No text overlay. No extra people.',
     'Lifestyle-фото «верх» — улица. Плейсхолдеры: photo_shared_skin_tone, photo_shared_hair_*, photo_shared_lower_color, photo_shared_lower_garment, photo_shared_shoes, photo_shared_bag, photo_shared_jewelry, photo_shared_camera_block, photo_top_street_pose, photo_top_street_location, photo_top_street_lighting.',
     2006);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_street_pose' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_street_pose', 'standing slightly turned looking away from the camera', 0),
    ('photo_top_street_pose', 'walking naturally looking ahead',                       1),
    ('photo_top_street_pose', 'leaning against a wall with a relaxed pose',            2),
    ('photo_top_street_pose', 'sitting on steps looking down softly',                  3),
    ('photo_top_street_pose', 'standing looking over her shoulder',                    4);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_street_location' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_street_location', 'the steps of a neoclassical building with large white classical columns', 0),
    ('photo_top_street_location', 'a cobblestone European street with old facades and warm storefronts',     1),
    ('photo_top_street_location', 'a shaded park alley with tall trees and dappled light on the path',       2),
    ('photo_top_street_location', 'a sunlit cafe terrace with small round tables and wicker chairs',         3),
    ('photo_top_street_location', 'an arched stone courtyard with climbing plants and warm stone walls',     4),
    ('photo_top_street_location', 'a city bridge with iron railings and soft river light in the background', 5),
    ('photo_top_street_location', 'a botanical garden path surrounded by lush greenery and soft light',      6),
    ('photo_top_street_location', 'an old European street with colorful building facades and flower boxes',  7);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'photo_top_street_lighting' LIMIT 1) THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('photo_top_street_lighting', 'Overcast soft daylight, no harsh shadows, even diffused light',     0),
    ('photo_top_street_lighting', 'Golden hour warm sidelight, long soft shadows, rich warm tones',    1),
    ('photo_top_street_lighting', 'Bright midday sun, crisp light, slight high-contrast shadows',      2),
    ('photo_top_street_lighting', 'Cloudy diffused light, cool neutral tones, flat even exposure',     3);
  END IF;
END $$;

-- Pinterest: префиксы заголовков
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'pinterest_title_prefixes') THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('pinterest_title_prefixes', 'Новинка',   1),
    ('pinterest_title_prefixes', 'Тренд',     2),
    ('pinterest_title_prefixes', 'Хит',       3),
    ('pinterest_title_prefixes', 'Must have', 4),
    ('pinterest_title_prefixes', 'Стиль',     5);
  END IF;
END $$;

-- Pinterest: стилевые фразы для описания
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'pinterest_style_phrases') THEN
    INSERT INTO prompt_list_items (list_key, value, sort_order) VALUES
    ('pinterest_style_phrases', 'Элегантный образ на каждый день.',       1),
    ('pinterest_style_phrases', 'Стильное решение для любого случая.',    2),
    ('pinterest_style_phrases', 'Комфорт и красота в одном.',             3),
    ('pinterest_style_phrases', 'Подчеркни свою индивидуальность.',       4),
    ('pinterest_style_phrases', 'Модный акцент вашего гардероба.',        5);
  END IF;
END $$;

-- Watermark: шаблон надписи артикула на изображении
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'watermark_article_label') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('watermark_article_label', 'арт. {article}', 'Формат надписи артикула на watermark-изображении');
  END IF;
END $$;

-- /watermark flow
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_watermark_all_done') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_watermark_all_done', 'Все ваши фото уже обработаны — артикул и название нанесены.', '/watermark — уже обработаны');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_watermark_confirm') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_watermark_confirm',
     E'Фото без текста: {count}\n\nНа каждое фото будет нанесено:\n• артикул товара (по диагонали)\n• название товара (по диагонали)\n\nОригиналы остаются без изменений.',
     '/watermark — запрос подтверждения; {count}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_watermark_processing') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_watermark_processing', 'Наношу текст на фото…', '/watermark — в процессе');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_watermark_done') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_watermark_done', 'Готово! Обработано фото: {done}', '/watermark — результат; {done}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_watermark_failed_line') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_watermark_failed_line', 'Не удалось обработать: {failed}', '/watermark — строка об ошибках; {failed}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_watermark_cancel') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_watermark_cancel', 'Отменено.', '/watermark — отмена');
  END IF;
END $$;

-- /pinterest flow
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_no_files') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_no_files',
     E'У вас нет медиафайлов для экспорта в Pinterest.\nСначала создайте фото или видео для ваших товаров.',
     '/pinterest — нет файлов для экспорта');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_ask_count') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_ask_count',
     E'Сколько строк сгенерировать для Pinterest CSV?\nВведите число от 10 до 200.\n\nДоступно файлов: {available}\nБаланс: {balance} руб. (до {max_rows} строк)\nСтоимость: {cost_per_row} руб./строка',
     '/pinterest — запрос количества строк; {available}, {balance}, {max_rows}, {cost_per_row}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_invalid_input') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_invalid_input', 'Пожалуйста, введите число от 10 до 200.', '/pinterest — некорректный ввод');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_out_of_range') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_out_of_range', 'Число должно быть от 10 до 200. Попробуйте ещё раз.', '/pinterest — число вне диапазона');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_insufficient_funds') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_insufficient_funds',
     E'Недостаточно средств.\nВаш баланс: {balance} руб. — хватает на {affordable} строк (минимум 10).\nПополните баланс и попробуйте снова.',
     '/pinterest — не хватает на минимум 10 строк; {balance}, {affordable}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_balance_low') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_balance_low',
     E'Баланс: {balance} руб. — не хватает на {count} строк ({cost} руб.).\nМожно создать {affordable} строк за {affordable_cost} руб.',
     '/pinterest — баланс ниже запрошенного; {balance}, {count}, {cost}, {affordable}, {affordable_cost}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_fewer_files') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_fewer_files',
     E'У вас {available} файлов, а вы запросили {requested}.\nСоздать CSV с {available} строками за {cost} руб.?',
     '/pinterest — файлов меньше запрошенного; {available}, {requested}, {cost}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_confirm') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_confirm',
     E'Баланс: {balance} руб.\nБудет списано: {cost} руб. за {count} строк.\nОстаток после: {after} руб.',
     '/pinterest — подтверждение; {balance}, {cost}, {count}, {after}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_cancel') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_cancel', 'Генерация отменена.', '/pinterest — отмена');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_generating') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_generating', 'Генерирую Pinterest CSV ({count} строк)…', '/pinterest — в процессе; {count}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_no_result') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_no_result', 'Не удалось сгенерировать строки.', '/pinterest — нет результата');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_done') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_done',
     E'Pinterest CSV готов — {count} строк\nСписано: {cost} руб. | Баланс: {balance} руб.',
     '/pinterest — результат готов; {count}, {cost}, {balance}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_errors_line') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_errors_line', 'Ошибок: {errors_count}', '/pinterest — строка с количеством ошибок; {errors_count}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_menu_overview') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_menu_overview',
     E'📌 Pinterest\n\nУ вас в базе есть:\n📸 Фото: {photos_count}\n🎬 Видео: {videos_count}\n\nС нанесённым артикулом:\n📸 Фото: {watermarked_photos}\n🎬 Видео: {watermarked_videos}\n\nВы можете сформировать CSV файл ваших товаров (до 100 за один раз), получить готовый файл и автоматически разместить их в Ваши аккаунты Pinterest.',
     'Pinterest меню — Шаг П1 обзор; {photos_count}, {videos_count}, {watermarked_photos}, {watermarked_videos}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_menu_count') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_menu_count',
     E'📌 Pinterest — Создание CSV\n\nС нанесённым артикулом доступно:\n📸 Фото: {watermarked_photos}\n🎬 Видео: {watermarked_videos}\n\n💳 Баланс: {balance}₽\nСтоимость: {cost_per_row}₽ за строку\n\nСколько строк сгенерировать? (максимум 100)',
     'Pinterest меню — Шаг П2 выбор количества; {watermarked_photos}, {watermarked_videos}, {balance}, {cost_per_row}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_menu_confirm') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_menu_confirm',
     E'📌 Pinterest — Подтверждение\n\nСтрок в CSV: {count}\n💰 Стоимость: {cost}₽\n💳 Баланс: {balance}₽\nОстаток после: {after}₽\n\nСоздать CSV?',
     'Pinterest меню — Шаг П3 подтверждение; {count}, {cost}, {balance}, {after}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_menu_insufficient') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_menu_insufficient',
     E'❌ Недостаточно средств.\n\n💰 Стоимость: {cost}₽\n💳 Ваш баланс: {balance}₽\n\nПополните баланс и попробуйте снова.',
     'Pinterest меню — недостаточно средств; {cost}, {balance}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_menu_no_files') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_menu_no_files',
     E'📌 Pinterest\n\nУ вас нет фото с нанесённым артикулом.\n\nСначала создайте фото и нанесите артикул через команду /watermark.',
     'Pinterest меню — нет файлов с вотермаркой');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_menu_generating') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_menu_generating',
     '⏳ Создаю Pinterest CSV ({count} строк)…',
     'Pinterest меню — в процессе генерации; {count}');
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM prompt_templates WHERE key = 'msg_pinterest_menu_done') THEN
    INSERT INTO prompt_templates (key, template, description) VALUES
    ('msg_pinterest_menu_done',
     E'✅ Pinterest CSV готов — {count} строк\n💰 Списано: {cost}₽ | 💳 Баланс: {balance}₽',
     'Pinterest меню — результат готов; {count}, {cost}, {balance}');
  END IF;
END $$;
