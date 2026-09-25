-- =====================================================================
-- FUNNEL-1A — Event Funnel (webinar attendees)          25 Sept 2026
-- Spec: Opsra Context/website-business/FUNNEL-1_Spec.md §3
-- All tables are NEW. Run in Supabase SQL Editor (production), in order.
-- STEP 0 first: check the whatsapp_numbers CHECK constraint (see bottom).
-- =====================================================================

-- ── 1. event_funnels ─────────────────────────────────────────────────
create table if not exists public.event_funnels (
  id                      uuid primary key default gen_random_uuid(),
  org_id                  uuid not null references public.organisations(id) on delete cascade,
  name                    text not null,
  status                  text not null default 'draft'
                            check (status in ('draft','active','closed')),
  whatsapp_number_id      uuid references public.whatsapp_numbers(id) on delete set null,
  event_title             text not null,
  event_starts_at         timestamptz not null,
  registration_closes_at  timestamptz not null,
  pricing_mode            text not null default 'window'
                            check (pricing_mode in ('window','deadline')),
  window_hours            integer not null default 24 check (window_hours between 1 and 168),
  early_deadline_at       timestamptz,
  early_price             numeric(12,2) not null check (early_price > 0),
  regular_price           numeric(12,2) not null check (regular_price > 0),
  group_size              integer check (group_size between 2 and 20),
  group_price             numeric(12,2) check (group_price > 0),
  currency                text not null default 'NGN',
  paid_group_link         text,
  prep_group_link         text,
  bonus_link              text,
  ad_codes                jsonb not null default '[]'::jsonb,
  messages                jsonb not null default '{}'::jsonb,
  sequence                jsonb not null default '[]'::jsonb,
  settings                jsonb not null default '{}'::jsonb,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  constraint event_funnels_deadline_mode_chk
    check (pricing_mode <> 'deadline' or early_deadline_at is not null),
  constraint event_funnels_close_before_event_chk
    check (registration_closes_at <= event_starts_at)
);
create index if not exists event_funnels_org_idx on public.event_funnels(org_id);
-- one ACTIVE funnel per WhatsApp number
create unique index if not exists event_funnels_one_active_per_number
  on public.event_funnels(whatsapp_number_id) where status = 'active';

-- ── 2. funnel_registrations ──────────────────────────────────────────
create table if not exists public.funnel_registrations (
  id                    uuid primary key default gen_random_uuid(),
  org_id                uuid not null references public.organisations(id) on delete cascade,
  funnel_id             uuid not null references public.event_funnels(id) on delete cascade,
  lead_id               uuid references public.leads(id) on delete set null,
  phone                 text not null,
  name                  text,
  email                 text,
  ad_code               text,
  ctwa_clid             text,
  ad_headline           text,
  referred_by_id        uuid references public.funnel_registrations(id) on delete set null,
  ref_code              text not null,
  pay_token             text not null,
  status                text not null default 'new'
                          check (status in ('new','paid','closed_unpaid','opted_out')),
  seats                 integer not null default 1,
  amount_paid           numeric(12,2) not null default 0,
  paid_at               timestamptz,
  payment_reference     text,
  price_tier_paid       text,
  first_message_at      timestamptz not null default now(),
  last_inbound_at       timestamptz,
  early_override_until  timestamptz,
  paused_until          timestamptz,
  needs_human           boolean not null default false,
  done_steps            jsonb not null default '[]'::jsonb,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  constraint funnel_registrations_phone_uniq unique (funnel_id, phone),
  constraint funnel_registrations_ref_uniq   unique (funnel_id, ref_code),
  constraint funnel_registrations_token_uniq unique (pay_token)
);
create index if not exists funnel_registrations_org_funnel_idx
  on public.funnel_registrations(org_id, funnel_id, status);
create index if not exists funnel_registrations_lead_idx on public.funnel_registrations(lead_id);

-- ── 3. funnel_payments ───────────────────────────────────────────────
create table if not exists public.funnel_payments (
  id               uuid primary key default gen_random_uuid(),
  org_id           uuid not null references public.organisations(id) on delete cascade,
  funnel_id        uuid not null references public.event_funnels(id) on delete cascade,
  registration_id  uuid not null references public.funnel_registrations(id) on delete cascade,
  reference        text not null unique,
  checkout_url     text,
  amount           numeric(12,2) not null,
  tier             text,
  seats            integer not null default 1,
  status           text not null default 'pending'
                     check (status in ('pending','paid','mismatch')),
  created_at       timestamptz not null default now(),
  paid_at          timestamptz
);
create index if not exists funnel_payments_reg_idx on public.funnel_payments(registration_id, status);
create index if not exists funnel_payments_org_ref_idx on public.funnel_payments(org_id, reference);

-- ── 4. funnel_events (audit + idempotency) ───────────────────────────
create table if not exists public.funnel_events (
  id               uuid primary key default gen_random_uuid(),
  org_id           uuid not null references public.organisations(id) on delete cascade,
  funnel_id        uuid not null references public.event_funnels(id) on delete cascade,
  registration_id  uuid references public.funnel_registrations(id) on delete cascade,
  type             text not null,
  step_key         text,
  detail           jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now()
);
-- a sequence step can never be sent (or skipped) twice for the same registration
create unique index if not exists funnel_events_step_once
  on public.funnel_events(registration_id, step_key) where step_key is not null;
create index if not exists funnel_events_funnel_type_idx
  on public.funnel_events(funnel_id, type, created_at);
create index if not exists funnel_events_reg_type_idx
  on public.funnel_events(registration_id, type, created_at);

-- ── 5. RLS (standard org_id isolation — 9E-H pattern) ────────────────
do $$
declare t text;
begin
  foreach t in array array['event_funnels','funnel_registrations','funnel_payments','funnel_events'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_org_select', t);
    execute format('drop policy if exists %I on public.%I', t || '_org_insert', t);
    execute format('drop policy if exists %I on public.%I', t || '_org_update', t);
    execute format($p$create policy %I on public.%I for select
                      using (org_id = ((auth.jwt() ->> 'org_id'::text))::uuid)$p$, t || '_org_select', t);
    execute format($p$create policy %I on public.%I for insert
                      with check (org_id = ((auth.jwt() ->> 'org_id'::text))::uuid)$p$, t || '_org_insert', t);
    execute format($p$create policy %I on public.%I for update
                      using (org_id = ((auth.jwt() ->> 'org_id'::text))::uuid)$p$, t || '_org_update', t);
  end loop;
end $$;

-- ── 6. whatsapp_numbers.wa_sales_mode ────────────────────────────────
-- STEP 0 — run this first and look at the result:
--   select conname, pg_get_constraintdef(oid) from pg_constraint
--   where conrelid = 'public.whatsapp_numbers'::regclass and contype = 'c';
-- If a constraint lists the allowed wa_sales_mode values (e.g. 'human','bot','ai_agent'),
-- replace it (use the real constraint name from STEP 0):
--   alter table public.whatsapp_numbers drop constraint <name>;
--   alter table public.whatsapp_numbers add constraint whatsapp_numbers_wa_sales_mode_check
--     check (wa_sales_mode in ('human','bot','ai_agent','event_funnel'));
-- If STEP 0 returns nothing about wa_sales_mode, no change is needed.

-- ── Verify (both must return 0 rows) ─────────────────────────────────
-- SELECT t.tablename FROM pg_tables t
-- LEFT JOIN pg_policies p ON p.tablename = t.tablename AND p.schemaname = 'public'
-- WHERE t.schemaname = 'public' AND t.rowsecurity = true AND p.policyname IS NULL;
-- SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND rowsecurity = false;
