-- Migration 001: Add reference_image_url to article_references
-- Date: 2026-04-07
-- Purpose: Store public URL of reference image for I2I API usage

ALTER TABLE article_references ADD COLUMN IF NOT EXISTS reference_image_url TEXT;
