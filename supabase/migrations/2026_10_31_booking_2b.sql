-- BOOKING-2B: per-staff calendars and round-robin. Safe to run more than once. Additive; existing orgs keep Phase 1 behaviour.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Per-org switch: 'single' = one calendar for the business (Phase 1), 'per_staff' = each person has their own.
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS calendar_mode text NOT NULL DEFAULT 'single';
DO $$ BEGIN
  ALTER TABLE booking_settings ADD CONSTRAINT booking_settings_calendar_mode_chk CHECK (calendar_mode IN ('single','per_staff'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Which services a person serves: anyone | specific people | the lead's owner first.
ALTER TABLE booking_services ADD COLUMN IF NOT EXISTS assignment_mode text NOT NULL DEFAULT 'anyone';
DO $$ BEGIN
  ALTER TABLE booking_services ADD CONSTRAINT booking_services_assignment_mode_chk CHECK (assignment_mode IN ('anyone','specific','lead_owner_first'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- People who take bookings. uses_org_hours = follow the business weekly hours until they set their own.
CREATE TABLE IF NOT EXISTS booking_staff (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  accepts_bookings boolean NOT NULL DEFAULT true,
  uses_org_hours boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, user_id)
);

CREATE TABLE IF NOT EXISTS booking_staff_availability (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  weekday smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),  -- 0 = Monday, org timezone
  start_time time NOT NULL,
  end_time time NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (end_time > start_time)
);
CREATE INDEX IF NOT EXISTS booking_staff_availability_user ON booking_staff_availability(org_id, user_id, weekday);

CREATE TABLE IF NOT EXISTS booking_staff_blocks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_at > starts_at)
);
CREATE INDEX IF NOT EXISTS booking_staff_blocks_user ON booking_staff_blocks(org_id, user_id, starts_at);

CREATE TABLE IF NOT EXISTS booking_service_staff (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  service_id uuid NOT NULL REFERENCES booking_services(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (service_id, user_id)
);

-- Double-booking guard. 'org' rows (every booking made before this, and every single-calendar org) keep the
-- business-wide rule. 'rep' rows are checked per person, so two people can be booked at the same time.
ALTER TABLE lead_demos ADD COLUMN IF NOT EXISTS guard_scope text NOT NULL DEFAULT 'org';
DO $$ BEGIN
  ALTER TABLE lead_demos ADD CONSTRAINT lead_demos_guard_scope_chk CHECK (guard_scope IN ('org','rep'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'lead_demos_no_overlap'
                 AND pg_get_constraintdef(oid) LIKE '%guard_scope%') THEN
    ALTER TABLE lead_demos DROP CONSTRAINT IF EXISTS lead_demos_no_overlap;
    ALTER TABLE lead_demos ADD CONSTRAINT lead_demos_no_overlap
      EXCLUDE USING gist (org_id WITH =, tstzrange(scheduled_at, slot_end) WITH &&)
      WHERE (slot_end IS NOT NULL AND scheduled_at IS NOT NULL AND deleted_at IS NULL
             AND status IN ('pending_assignment','confirmed') AND guard_scope = 'org');
  END IF;
END $$;

DO $$ BEGIN
  ALTER TABLE lead_demos ADD CONSTRAINT lead_demos_rep_no_overlap
    EXCLUDE USING gist (org_id WITH =, assigned_to WITH =, tstzrange(scheduled_at, slot_end) WITH &&)
    WHERE (slot_end IS NOT NULL AND scheduled_at IS NOT NULL AND assigned_to IS NOT NULL AND deleted_at IS NULL
           AND status IN ('pending_assignment','confirmed') AND guard_scope = 'rep');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- RLS: same posture as the other booking tables (backend uses the service role).
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['booking_staff','booking_staff_availability','booking_staff_blocks','booking_service_staff'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = t::regclass AND polname = 'service_role_bypass') THEN
      EXECUTE format('CREATE POLICY service_role_bypass ON %I TO service_role USING (true) WITH CHECK (true)', t);
    END IF;
  END LOOP;
END $$;
