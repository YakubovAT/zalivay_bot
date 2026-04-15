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
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
     'Professional lifestyle fashion photograph. A model wearing {description}, paired with {item_color} {bottom_item}. Location: {location}. Natural relaxed pose, high-quality e-commerce photography, realistic lighting, sharp focus on the clothing.',
     'Фото — категория «верх». Переменные: {description}, {item_color}, {bottom_item}, {location}'),
    ('photo_bottom',
     'Professional lifestyle fashion photograph. A model wearing {description}, paired with {item_color} {top_item}. Location: {location}. Natural relaxed pose, high-quality e-commerce photography, realistic lighting, sharp focus on the clothing.',
     'Фото — категория «низ». Переменные: {description}, {item_color}, {top_item}, {location}'),
    ('photo_shoes',
     'Professional lifestyle fashion photograph. A model wearing {description}. Outfit: {neutral_outfit}. Location: {location}. Natural relaxed pose, high-quality e-commerce photography, realistic lighting, focus on the footwear.',
     'Фото — категория «обувь». Переменные: {description}, {neutral_outfit}, {location}'),
    ('photo_hat',
     'Professional lifestyle fashion photograph. A model wearing {description}. Outfit: {neutral_outfit}. Location: {location}. Natural relaxed pose, high-quality e-commerce photography, realistic lighting, focus on the headwear.',
     'Фото — категория «головной убор». Переменные: {description}, {neutral_outfit}, {location}'),
    ('video_top',
     'A fashion lifestyle video. A model wearing {description}, paired with {item_color} {item}. Location: {location}. The model is {motion}. Smooth cinematic camera movement, natural lighting, sharp focus on the clothing, professional e-commerce fashion video.',
     'Видео — категория «верх». Переменные: {description}, {item_color}, {item}, {location}, {motion}'),
    ('video_bottom',
     'A fashion lifestyle video. A model wearing {description}, paired with {item_color} {item}. Location: {location}. The model is {motion}. Smooth cinematic camera movement, natural lighting, sharp focus on the clothing, professional e-commerce fashion video.',
     'Видео — категория «низ». Переменные: {description}, {item_color}, {item}, {location}, {motion}'),
    ('video_shoes',
     'A fashion lifestyle video. A model wearing {description}, styled with a {outfit}. Location: {location}. The model is {motion}, with camera focus on the footwear. Smooth cinematic camera movement, natural lighting, sharp focus on the shoes, professional e-commerce fashion video.',
     'Видео — категория «обувь». Переменные: {description}, {outfit}, {location}, {motion}'),
    ('video_hat',
     'A fashion lifestyle video. A model wearing {description}, styled with a {outfit}. Location: {location}. The model is {motion}, with camera focus on the headwear. Smooth cinematic camera movement, natural lighting, sharp focus on the hat, professional e-commerce fashion video.',
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
    ('video_locations', 'a sunny city street', 'walking confidently', 0),
    ('video_locations', 'a modern coffee shop', 'sitting down gracefully', 1),
    ('video_locations', 'a lush green park', 'strolling leisurely', 2),
    ('video_locations', 'a bright minimalist studio', 'turning slowly', 3),
    ('video_locations', 'a seaside promenade', 'walking along the waterfront', 4),
    ('video_locations', 'a stylish rooftop terrace', 'standing and looking into the distance', 5),
    ('video_locations', 'a cozy indoor café', 'picking up a cup', 6),
    ('video_locations', 'a vibrant flower market', 'walking through the stalls', 7),
    ('video_locations', 'a clean white studio backdrop', 'posing and turning', 8),
    ('video_locations', 'an urban pedestrian bridge', 'walking toward the camera', 9),
    ('video_locations', 'a forest path in autumn', 'walking through falling leaves', 10),
    ('video_locations', 'a luxury hotel lobby', 'walking through the entrance', 11);
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
    ('video_neutral_outfits', 'simple monochrome look', 2);
  END IF;
END $$;
