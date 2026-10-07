-- PARTNER-1A — Launch Partners (opsra_test project)
-- Run in the Supabase SQL editor BEFORE deploying PARTNER-1A.
-- Confirmed 7 Oct 2026: neither partner table exists. Create-only, guarded with IF NOT EXISTS.
-- Each partner is linked to a site_builders row (source 'manual', account_type 'builder') so the
-- existing brief form, notifications and site creation work unchanged.

CREATE TABLE IF NOT EXISTS public.site_partners (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        uuid NOT NULL REFERENCES public.organisations(id),
  builder_id    uuid NOT NULL REFERENCES public.site_builders(id),
  full_name     varchar(200) NOT NULL,
  phone_number  varchar(32)  NOT NULL,
  email         varchar(255),
  agency_name   varchar(200),
  partner_code  varchar(32)  NOT NULL,
  link_slug     varchar(64)  NOT NULL,
  status        varchar(20)  NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','suspended')),
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_site_partners_org_code ON public.site_partners (org_id, partner_code);
CREATE UNIQUE INDEX IF NOT EXISTS uq_site_partners_slug     ON public.site_partners (link_slug);
CREATE UNIQUE INDEX IF NOT EXISTS uq_site_partners_builder  ON public.site_partners (builder_id);
CREATE INDEX        IF NOT EXISTS idx_site_partners_org     ON public.site_partners (org_id);

ALTER TABLE public.site_partners ENABLE ROW LEVEL SECURITY;  -- backend uses the service role, same as site_builders
