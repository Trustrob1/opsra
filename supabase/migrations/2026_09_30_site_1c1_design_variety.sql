-- SITE-1C-1 — design variety (spec: website-business/SITE-1C_Spec.md)
-- Additive and idempotent. Run BEFORE deploying the SITE-1C-1 code.
-- 1) two new columns on site_presets (empty = every option allowed)
ALTER TABLE site_presets ADD COLUMN IF NOT EXISTS allowed_fonts text[] NOT NULL DEFAULT '{}';
ALTER TABLE site_presets ADD COLUMN IF NOT EXISTS token_options jsonb NOT NULL DEFAULT '{}'::jsonb;

-- 2) widen default_palettes to the palettes tagged for each launch niche, but ONLY where the
--    preset still has the original three (berry, cobalt, sage) — a preset staff already edited is left alone.
--    The first palette in every list is one of the original three, so the previous code stays safe
--    if this SQL runs before the new code is deployed.
UPDATE site_presets SET default_palettes = ARRAY['berry', 'cobalt', 'sage', 'terracotta', 'midnight', 'gold', 'blush', 'plum', 'coral', 'mustard', 'charcoal', 'royal', 'sky', 'rose_gold', 'sunset', 'mist', 'cocoa']::text[], updated_at = now()
 WHERE key = 'boutique' AND default_palettes = ARRAY['berry','cobalt','sage']::text[];
UPDATE site_presets SET default_palettes = ARRAY['cobalt', 'terracotta', 'emerald', 'gold', 'blush', 'coral', 'teal', 'mustard', 'royal', 'forest', 'rose_gold', 'sunset', 'olive', 'cocoa']::text[], updated_at = now()
 WHERE key = 'restaurant' AND default_palettes = ARRAY['berry','cobalt','sage']::text[];
UPDATE site_presets SET default_palettes = ARRAY['berry', 'sage', 'terracotta', 'midnight', 'emerald', 'gold', 'blush', 'plum', 'coral', 'teal', 'charcoal', 'forest', 'sky', 'rose_gold', 'sunset', 'olive', 'mist', 'cocoa']::text[], updated_at = now()
 WHERE key = 'salon' AND default_palettes = ARRAY['berry','cobalt','sage']::text[];
UPDATE site_presets SET default_palettes = ARRAY['cobalt', 'sage', 'midnight', 'emerald', 'plum', 'teal', 'mustard', 'charcoal', 'royal', 'forest', 'sky', 'olive', 'mist']::text[], updated_at = now()
 WHERE key = 'services' AND default_palettes = ARRAY['berry','cobalt','sage']::text[];
