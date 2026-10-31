-- BOOKING-3C: Calendly intake. Idempotent, additive.
-- Calendly owns the double-booking check for its own bookings, so they carry guard_scope 'ext' (outside both Opsra guards)
-- but still have slot_end, so they block Opsra's open slots.
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS external_meta jsonb;
ALTER TABLE lead_demos DROP CONSTRAINT IF EXISTS lead_demos_guard_scope_chk;
ALTER TABLE lead_demos ADD CONSTRAINT lead_demos_guard_scope_chk CHECK (guard_scope IN ('org','rep','ext'));
CREATE UNIQUE INDEX IF NOT EXISTS lead_demos_calendly_external_uq ON lead_demos(org_id, external_id)
  WHERE source = 'calendly' AND external_id IS NOT NULL;
