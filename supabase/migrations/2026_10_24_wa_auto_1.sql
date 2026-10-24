-- WA-AUTO-1: what kind of customer an organisation is.
-- 'full' = the normal Opsra app. 'wa_automation' = WhatsApp automation only (inbox, bot, knowledge, billing; no CRM screens).
-- Safe to run more than once. Every existing organisation stays 'full'.
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS product_mode text NOT NULL DEFAULT 'full';
ALTER TABLE organisations DROP CONSTRAINT IF EXISTS organisations_product_mode_check;
ALTER TABLE organisations ADD CONSTRAINT organisations_product_mode_check CHECK (product_mode IN ('full', 'wa_automation'));
