-- Миграция: удаление ref_type из article_references
-- Эталон теперь один на артикул (общий для фото и видео)

-- 1. Удаляем столбец ref_type
ALTER TABLE article_references DROP COLUMN IF EXISTS ref_type;

-- 2. Добавляем UNIQUE ограничение
CREATE UNIQUE INDEX IF NOT EXISTS idx_article_references_unique
    ON article_references (user_id, articul);

-- 3. Удаляем старый индекс (если существует)
DROP INDEX IF EXISTS idx_article_references_user_articul;
