-- SITE-PREMIUM P5b: staff can switch "charge the Premium price at go-live" on for a Premium site made before payment existed.
-- Run once in the Supabase SQL editor. Safe to run twice.
ALTER TABLE public.sites ADD COLUMN IF NOT EXISTS premium_charge_at_golive boolean NOT NULL DEFAULT false;
