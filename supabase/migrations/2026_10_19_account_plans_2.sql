-- ACCOUNT-PLANS AP-2: orders for an organisation's own Capture / Convert / Grow plan.
-- Additive and safe to re-run. Run in the Supabase SQL editor BEFORE deploying the AP-2 code.
-- Nothing here changes an existing business: no row is created until an owner starts a payment.

create table if not exists public.org_plan_orders (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null references public.organisations(id) on delete cascade,
  plan_key      text not null,
  change_kind   text not null default 'new'
                  check (change_kind in ('new', 'renewal', 'upgrade', 'switch', 'downgrade_renewal')),
  amount_kobo   bigint not null check (amount_kobo > 0),
  quote         jsonb not null default '{}'::jsonb,
  reference     text not null unique,
  checkout_url  text,
  status        text not null default 'pending'
                  check (status in ('pending', 'paid', 'failed', 'expired')),
  payer_email   text,
  created_by    uuid,
  paid_kobo     bigint,
  paid_at       timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists org_plan_orders_org_idx on public.org_plan_orders (org_id, created_at desc);
create index if not exists org_plan_orders_open_idx on public.org_plan_orders (org_id, status);

-- Backend-only (service role). RLS on with no policies = no direct client access.
alter table public.org_plan_orders enable row level security;
