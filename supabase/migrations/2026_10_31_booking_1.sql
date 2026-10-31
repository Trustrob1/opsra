-- BOOKING-1: native booking (Phase 1). Safe to run more than once. Additive only.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Per-org settings (one row per org). native_enabled is the per-org switch; default off.
CREATE TABLE IF NOT EXISTS booking_settings (
  org_id uuid PRIMARY KEY REFERENCES organisations(id) ON DELETE CASCADE,
  native_enabled boolean NOT NULL DEFAULT false,
  label text NOT NULL DEFAULT 'consultation',
  cancel_cutoff_hours integer NOT NULL DEFAULT 24 CHECK (cancel_cutoff_hours >= 0),
  auto_send_link boolean NOT NULL DEFAULT false,
  default_rep_id uuid REFERENCES users(id),
  rr_cursor integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS booking_services (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  name text NOT NULL,
  slug text NOT NULL,
  description text,
  duration_minutes integer NOT NULL DEFAULT 30 CHECK (duration_minutes BETWEEN 5 AND 480),
  buffer_after_minutes integer NOT NULL DEFAULT 0 CHECK (buffer_after_minutes BETWEEN 0 AND 240),
  medium text NOT NULL DEFAULT 'virtual' CHECK (medium IN ('virtual','in_person','phone')),
  location_text text,
  requires_approval boolean NOT NULL DEFAULT false,
  min_notice_hours integer NOT NULL DEFAULT 2 CHECK (min_notice_hours >= 0),
  window_days integer NOT NULL DEFAULT 30 CHECK (window_days BETWEEN 1 AND 365),
  active boolean NOT NULL DEFAULT true,
  sort_order integer NOT NULL DEFAULT 0,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS booking_services_org_slug ON booking_services(org_id, slug) WHERE deleted_at IS NULL;

-- Weekly hours, interpreted in the org timezone. service_id NULL = applies to every service.
CREATE TABLE IF NOT EXISTS booking_availability (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  service_id uuid REFERENCES booking_services(id) ON DELETE CASCADE,
  weekday smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),  -- 0 = Monday
  start_time time NOT NULL,
  end_time time NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (end_time > start_time)
);
CREATE INDEX IF NOT EXISTS booking_availability_org ON booking_availability(org_id, weekday);

CREATE TABLE IF NOT EXISTS booking_blocks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_at > starts_at)
);
CREATE INDEX IF NOT EXISTS booking_blocks_org ON booking_blocks(org_id, starts_at);

-- Signed link tied to one lead. Only the hash is stored.
CREATE TABLE IF NOT EXISTS booking_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  service_id uuid REFERENCES booking_services(id) ON DELETE SET NULL,
  demo_id uuid REFERENCES lead_demos(id) ON DELETE SET NULL,
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS booking_links_lead ON booking_links(lead_id);

-- lead_demos: additive columns
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS service_id uuid REFERENCES booking_services(id) ON DELETE SET NULL;
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'manual';   -- manual | bot | native | calendly
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS external_id text;
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS slot_end timestamptz;   -- scheduled_at + duration + buffer (native bookings only)
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS cancelled_at timestamptz;
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS cancel_reason text;
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS cancelled_by text;      -- lead | staff
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS reschedule_count integer NOT NULL DEFAULT 0;
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS lead_timezone text;

-- No two live native bookings may overlap inside one org (database-level double-booking guard).
DO $$ BEGIN
  ALTER TABLE lead_demos ADD CONSTRAINT lead_demos_no_overlap
    EXCLUDE USING gist (org_id WITH =, tstzrange(scheduled_at, slot_end) WITH &&)
    WHERE (slot_end IS NOT NULL AND scheduled_at IS NOT NULL AND deleted_at IS NULL
           AND status IN ('pending_assignment','confirmed'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- RLS: same posture as other server-only tables (backend uses the service role).
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['booking_settings','booking_services','booking_availability','booking_blocks','booking_links'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = t::regclass AND polname = 'service_role_bypass') THEN
      EXECUTE format('CREATE POLICY service_role_bypass ON %I TO service_role USING (true) WITH CHECK (true)', t);
    END IF;
  END LOOP;
END $$;
