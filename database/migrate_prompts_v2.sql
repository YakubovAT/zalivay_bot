-- migrate_prompts_v2.sql
-- Обновление промптов до профессиональных версий (v2).
-- Запускать вручную на сервере:
--   psql -U zalivai -d zalivai_db -f migrate_prompts_v2.sql

-- ============================================================
-- 1. Шаблоны промптов
-- ============================================================

UPDATE prompt_templates SET
    template = 'Fashion lifestyle editorial photograph. A stylish young woman wearing {description}, paired with {item_color} {bottom_item}. Setting: {location}. Confident, natural relaxed pose. Soft diffused natural light, warm tones, shallow depth of field with blurred bokeh background. Sharp focus on the top garment — fabric texture, fit, and drape clearly visible. Photorealistic commercial photography, high resolution, no distortion.',
    updated_at = NOW()
WHERE key = 'photo_top';

UPDATE prompt_templates SET
    template = 'Fashion lifestyle editorial photograph. A stylish young woman wearing {description}, paired with {item_color} {top_item}. Setting: {location}. Natural relaxed stance, elongated silhouette. Soft diffused natural light, warm tones, shallow depth of field with blurred bokeh background. Sharp focus on the bottom garment — fabric texture, fit, and leg line clearly visible. Photorealistic commercial photography, high resolution, no distortion.',
    updated_at = NOW()
WHERE key = 'photo_bottom';

UPDATE prompt_templates SET
    template = 'Fashion lifestyle editorial photograph. A stylish young woman wearing {description}. Outfit: {neutral_outfit}. Setting: {location}. Natural pose with footwear prominent in frame, slight low-angle view to feature the shoes. Soft side natural lighting, shallow depth of field. Sharp focus on the footwear — material texture, construction, and sole detail clearly visible. Photorealistic commercial photography, high resolution, no distortion.',
    updated_at = NOW()
WHERE key = 'photo_shoes';

UPDATE prompt_templates SET
    template = 'Fashion lifestyle editorial photograph. A stylish young woman wearing {description}. Outfit: {neutral_outfit}. Setting: {location}. Natural confident pose, upper body and headwear in clean frame. Soft diffused natural light, warm tones. Sharp focus on the headwear — fabric, structure, and brim detail clearly visible. Photorealistic commercial photography, high resolution, no distortion.',
    updated_at = NOW()
WHERE key = 'photo_hat';

UPDATE prompt_templates SET
    template = 'Smooth cinematic fashion lifestyle video. A stylish young woman wearing {description}, paired with {item_color} {item}. Location: {location}. The model is {motion}. Slow gliding camera captures the fabric drape and flow of the garment. Warm soft natural lighting, cinematic color grading, shallow depth of field. The top garment stays in sharp focus throughout the motion. Professional e-commerce fashion footage, no camera shake, fluid movement.',
    updated_at = NOW()
WHERE key = 'video_top';

UPDATE prompt_templates SET
    template = 'Smooth cinematic fashion lifestyle video. A stylish young woman wearing {description}, paired with {item_color} {item}. Location: {location}. The model is {motion}. Slow tracking camera at mid-height captures the drape and movement of the bottom garment. Warm soft natural lighting, cinematic color grading, shallow depth of field. The garment stays in sharp focus throughout the motion. Professional e-commerce fashion footage, no camera shake, fluid movement.',
    updated_at = NOW()
WHERE key = 'video_bottom';

UPDATE prompt_templates SET
    template = 'Smooth cinematic fashion lifestyle video. A stylish young woman wearing {description}, styled with a {outfit}. Location: {location}. The model is {motion}. Camera alternates between full-body and waist-down close-up angles, highlighting the footwear in motion. Warm directional natural lighting, cinematic color grading. Material texture and movement of the shoes clearly visible throughout. Professional e-commerce fashion footage, no camera shake, fluid movement.',
    updated_at = NOW()
WHERE key = 'video_shoes';

UPDATE prompt_templates SET
    template = 'Smooth cinematic fashion lifestyle video. A stylish young woman wearing {description}, styled with a {outfit}. Location: {location}. The model is {motion}. Camera frames from shoulders up, with the headwear prominently featured. Soft golden-hour or studio lighting, cinematic color grading. Fabric texture, structure, and movement of the headwear clearly visible. Professional e-commerce fashion footage, no camera shake, fluid movement.',
    updated_at = NOW()
WHERE key = 'video_hat';

-- ============================================================
-- 2. Локации для видео — обновляем motion-описания
-- ============================================================

UPDATE prompt_list_items SET value2 = 'walking confidently forward, hair gently moving',          updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a sunny city street';
UPDATE prompt_list_items SET value2 = 'sitting gracefully and glancing up at the camera',          updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a modern coffee shop';
UPDATE prompt_list_items SET value2 = 'strolling leisurely, light breeze in the air',              updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a lush green park';
UPDATE prompt_list_items SET value2 = 'rotating slowly with arms slightly extended',               updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a bright minimalist studio';
UPDATE prompt_list_items SET value2 = 'walking along the waterfront with a relaxed stride',        updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a seaside promenade';
UPDATE prompt_list_items SET value  = 'a stylish rooftop terrace with city skyline',
                             value2 = 'standing and gazing into the distance',                     updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a stylish rooftop terrace';
UPDATE prompt_list_items SET value  = 'a cozy warmly lit café interior',
                             value2 = 'reaching for a cup and smiling slightly',                   updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a cozy indoor café';
UPDATE prompt_list_items SET value  = 'a vibrant outdoor flower market',
                             value2 = 'walking through the stalls, glancing at flowers',           updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a vibrant flower market';
UPDATE prompt_list_items SET value  = 'a clean white studio with soft fill light',
                             value2 = 'posing and turning to show all angles',                     updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a clean white studio backdrop';
UPDATE prompt_list_items SET value2 = 'walking toward the camera with a confident gait',           updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'an urban pedestrian bridge';
UPDATE prompt_list_items SET value  = 'a forest path with autumn foliage',
                             value2 = 'walking through softly falling leaves',                     updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a forest path in autumn';
UPDATE prompt_list_items SET value  = 'an elegant marble hotel lobby',
                             value2 = 'walking through the entrance with a graceful stride',       updated_at = NOW() WHERE list_key = 'video_locations' AND value = 'a luxury hotel lobby';

-- Добавляем две новые локации (только если ещё нет)
INSERT INTO prompt_list_items (list_key, value, value2, sort_order)
SELECT 'video_locations', 'a sunlit courtyard with stone architecture', 'stepping forward and pausing naturally', 12
WHERE NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'video_locations' AND value = 'a sunlit courtyard with stone architecture');

INSERT INTO prompt_list_items (list_key, value, value2, sort_order)
SELECT 'video_locations', 'a glass-front boutique street', 'walking past storefronts, window reflection visible', 13
WHERE NOT EXISTS (SELECT 1 FROM prompt_list_items WHERE list_key = 'video_locations' AND value = 'a glass-front boutique street');

-- ============================================================
-- 3. Нейтральные образы для видео — добавляем новые позиции
-- ============================================================

INSERT INTO prompt_list_items (list_key, value, sort_order)
SELECT 'video_neutral_outfits', v.value, v.sort_order
FROM (VALUES
    ('simple all-black monochrome look',                                 2),
    ('soft cream knit and wide-leg ivory trousers',                      3),
    ('light denim jacket over a white linen shirt and straight trousers', 4),
    ('camel turtleneck and tailored sand-colored trousers',              5),
    ('pastel lavender blouse and white straight-leg pants',              6)
) AS v(value, sort_order)
WHERE NOT EXISTS (
    SELECT 1 FROM prompt_list_items
    WHERE list_key = 'video_neutral_outfits' AND value = v.value
);

-- Обновляем старую запись 'simple monochrome look' → актуальное название
UPDATE prompt_list_items
SET value = 'simple all-black monochrome look', updated_at = NOW()
WHERE list_key = 'video_neutral_outfits' AND value = 'simple monochrome look';
