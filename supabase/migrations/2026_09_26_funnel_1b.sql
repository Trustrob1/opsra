-- =====================================================================
-- FUNNEL-1B — ad spend + ad-hoc broadcasts                 25 Sept 2026
-- Spec: Opsra Context/website-business/FUNNEL-1_Spec.md §15.1
-- Both tables are NEW. Safe to re-run.
-- =====================================================================

-- ── 1. funnel_ad_spend (one row per funnel × day × ad code) ─────────
create table if not exists public.funnel_ad_spend (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null references public.organisations(id) on delete cascade,
  funnel_id   uuid not null references public.event_funnels(id) on delete cascade,
  spend_date  date not null,
  ad_code     text not null,
  amount      numeric(12,2) not null default 0 check (amount >= 0),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint funnel_ad_spend_day_code_uniq unique (funnel_id, spend_date, ad_code)
);
create index if not exists funnel_ad_spend_org_funnel_idx on public.funnel_ad_spend(org_id, funnel_id, spend_date);

-- ── 2. funnel_broadcasts ─────────────────────────────────────────────
create table if not exists public.funnel_broadcasts (
  id               uuid primary key default gen_random_uuid(),
  org_id           uuid not null references public.organisations(id) on delete cascade,
  funnel_id        uuid not null references public.event_funnels(id) on delete cascade,
  template_name    text not null,
  template_params  jsonb not null default '[]'::jsonb,
  language         text not null default 'en',
  audience         text not null check (audience in ('unpaid','paid','all')),
  ad_code          text,
  status           text not null default 'queued'
                     check (status in ('queued','sending','done','cancelled','capped')),
  total            integer not null default 0,
  sent             integer not null default 0,
  failed           integer not null default 0,
  created_by       uuid,
  created_at       timestamptz not null default now(),
  finished_at      timestamptz
);
create index if not exists funnel_broadcasts_funnel_status_idx on public.funnel_broadcasts(funnel_id, status);

-- ── 3. RLS (standard org_id isolation) ──────────────────────────────
do $$
declare t text;
begin
  foreach t in array array['funnel_ad_spend','funnel_broadcasts'] loop
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

-- ── Verify: expect 2 rows, policies = 3 ─────────────────────────────
-- select tablename, count(*) as policies from pg_policies
-- where schemaname = 'public' and tablename in ('funnel_ad_spend','funnel_broadcasts') group by tablename;
