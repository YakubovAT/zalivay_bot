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
    task_type   TEXT NOT NULL CHECK (task_type IN ('photo', 'video')),
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
