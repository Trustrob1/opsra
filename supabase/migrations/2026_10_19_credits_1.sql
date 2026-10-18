-- CREDITS-1 — prepaid credits wallet, append-only ledger, dynamic rates and
-- automation-fee rules, Meta rate cards, cost-logging columns.
-- Additive and idempotent: safe to run twice. No existing column is changed or dropped.
-- All money is stored in kobo (integer). Service-role only (RLS on, no policies).

-- ── Wallet ────────────────────────────────────────────────────────────────
create table if not exists credit_wallets (
    org_id               uuid primary key references organisations(id) on delete cascade,
    balance_kobo         bigint  not null default 0 check (balance_kobo >= 0),
    ai_monthly_budget_kobo bigint check (ai_monthly_budget_kobo is null or ai_monthly_budget_kobo >= 0),
    low_balance_kobo     bigint  not null default 0 check (low_balance_kobo >= 0),
    meta_billing         text    not null default 'client_direct'
                         check (meta_billing in ('client_direct','opsra_credit_line')),
    metering_enabled     boolean not null default false,  -- off until Trust switches an org on
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);

-- ── Lots (so each top-up can expire 12 months after purchase) ─────────────
create table if not exists credit_lots (
    id              uuid primary key default gen_random_uuid(),
    org_id          uuid not null references organisations(id) on delete cascade,
    original_kobo   bigint not null check (original_kobo > 0),
    remaining_kobo  bigint not null check (remaining_kobo >= 0),
    expires_at      timestamptz not null,
    ref             text,
    created_at      timestamptz not null default now()
);
create index if not exists credit_lots_org_exp_idx
    on credit_lots (org_id, expires_at) where remaining_kobo > 0;

-- ── Ledger (append-only) ──────────────────────────────────────────────────
create table if not exists credit_ledger (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references organisations(id) on delete cascade,
    kind                text not null
                        check (kind in ('topup','ai','meta','fee','adjust','refund','expiry')),
    amount_kobo         bigint not null,              -- signed: + adds credit, - spends
    balance_after_kobo  bigint not null,
    unit                text,                          -- e.g. 'ai_turn', 'wa_service', 'wa_utility'
    ref                 text,                          -- idempotency key
    meta                jsonb not null default '{}'::jsonb,
    created_at          timestamptz not null default now()
);
create unique index if not exists credit_ledger_org_ref_uidx
    on credit_ledger (org_id, ref) where ref is not null;
create index if not exists credit_ledger_org_time_idx
    on credit_ledger (org_id, created_at desc);

create or replace function credit_ledger_block_change() returns trigger
language plpgsql as $$
begin
    raise exception 'credit_ledger is append-only';
end $$;

drop trigger if exists credit_ledger_no_update on credit_ledger;
create trigger credit_ledger_no_update
    before update or delete on credit_ledger
    for each row execute function credit_ledger_block_change();

-- ── Rates (effective-dated; newest row with effective_from <= now wins) ───
create table if not exists credit_rates (
    id              uuid primary key default gen_random_uuid(),
    effective_from  timestamptz not null default now(),
    fx_ngn_per_usd  numeric(12,4) not null check (fx_ngn_per_usd > 0),
    ai_markup_pct   numeric(6,2)  not null default 50 check (ai_markup_pct >= 0),
    meta_markup_pct numeric(6,2)  not null default 0  check (meta_markup_pct >= 0),
    min_charge_kobo bigint not null default 0 check (min_charge_kobo >= 0),
    rounding_kobo   bigint not null default 1 check (rounding_kobo >= 1),
    note            text,
    created_at      timestamptz not null default now()
);

-- ── Automation fee rules (dynamic; none seeded, so the default fee is zero) ─
create table if not exists automation_fee_rules (
    id                    uuid primary key default gen_random_uuid(),
    scope                 text not null default 'default' check (scope in ('default','org')),
    org_id                uuid references organisations(id) on delete cascade,
    event_type            text not null,               -- 'wa_service','wa_utility','wa_marketing','wa_auth','ai_turn','email','any'
    mode                  text not null check (mode in ('flat_kobo','percent_of_meta_cost','percent_of_ai_cost')),
    value                 numeric(14,4) not null check (value >= 0),
    min_kobo              bigint not null default 0 check (min_kobo >= 0),
    max_kobo              bigint check (max_kobo is null or max_kobo >= min_kobo),
    free_units_per_month  integer not null default 0 check (free_units_per_month >= 0),
    effective_from        timestamptz not null default now(),
    effective_to          timestamptz,
    enabled               boolean not null default false,
    note                  text,
    created_at            timestamptz not null default now(),
    check ((scope = 'org') = (org_id is not null))
);
create index if not exists automation_fee_rules_lookup_idx
    on automation_fee_rules (event_type, scope, org_id) where enabled;

-- ── Meta rate cards ───────────────────────────────────────────────────────
create table if not exists meta_rate_cards (
    id               uuid primary key default gen_random_uuid(),
    country          text not null default 'NG',
    category         text not null check (category in ('service','utility','marketing','authentication')),
    usd_per_message  numeric(10,6) not null check (usd_per_message >= 0),
    effective_from   timestamptz not null,
    source           text,
    created_at       timestamptz not null default now(),
    unique (country, category, effective_from)
);

-- ── Packs and orders (used by CREDITS-2; created now so the schema is whole) ─
create table if not exists credit_packs (
    id            uuid primary key default gen_random_uuid(),
    name          text not null,
    price_kobo    bigint not null check (price_kobo > 0),
    credit_kobo   bigint not null check (credit_kobo > 0),
    active        boolean not null default true,
    sort_order    integer not null default 0,
    created_at    timestamptz not null default now()
);

create table if not exists credit_orders (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references organisations(id) on delete cascade,
    pack_id             uuid references credit_packs(id),
    amount_kobo         bigint not null check (amount_kobo > 0),
    credit_kobo         bigint not null check (credit_kobo > 0),
    status              text not null default 'pending' check (status in ('pending','paid','failed','refunded')),
    paystack_reference  text unique,
    created_at          timestamptz not null default now(),
    paid_at             timestamptz
);

-- ── Additive columns on existing tables ───────────────────────────────────
alter table claude_usage_log add column if not exists cache_read_tokens     integer not null default 0;
alter table claude_usage_log add column if not exists cache_creation_tokens integer not null default 0;
alter table claude_usage_log add column if not exists charged_kobo          bigint;

alter table whatsapp_messages add column if not exists meta_category text;
alter table whatsapp_messages add column if not exists meta_billable boolean;
create index if not exists whatsapp_messages_meta_billable_idx
    on whatsapp_messages (org_id, created_at) where meta_billable is true;

-- ── RLS: service role only ────────────────────────────────────────────────
alter table credit_wallets        enable row level security;
alter table credit_lots           enable row level security;
alter table credit_ledger         enable row level security;
alter table credit_rates          enable row level security;
alter table automation_fee_rules  enable row level security;
alter table meta_rate_cards       enable row level security;
alter table credit_packs          enable row level security;
alter table credit_orders         enable row level security;

-- ── credit_credit: add credit (top-up, refund, adjust+). Idempotent on ref. ─
create or replace function credit_credit(
    p_org uuid, p_amount bigint, p_kind text, p_ref text,
    p_unit text default null, p_meta jsonb default '{}'::jsonb,
    p_expires_at timestamptz default null
) returns table (applied boolean, balance_kobo bigint)
language plpgsql as $$
declare
    v_bal bigint;
    v_exp timestamptz := coalesce(p_expires_at, now() + interval '12 months');
begin
    if p_amount <= 0 then raise exception 'credit amount must be positive'; end if;
    if p_kind not in ('topup','refund','adjust') then raise exception 'bad kind %', p_kind; end if;

    insert into credit_wallets (org_id) values (p_org) on conflict (org_id) do nothing;
    select w.balance_kobo into v_bal from credit_wallets w where w.org_id = p_org for update;

    if p_ref is not null and exists (
        select 1 from credit_ledger l where l.org_id = p_org and l.ref = p_ref
    ) then
        return query select false, v_bal;
        return;
    end if;

    v_bal := v_bal + p_amount;
    update credit_wallets set balance_kobo = v_bal, updated_at = now() where org_id = p_org;
    insert into credit_lots (org_id, original_kobo, remaining_kobo, expires_at, ref)
        values (p_org, p_amount, p_amount, v_exp, p_ref);
    insert into credit_ledger (org_id, kind, amount_kobo, balance_after_kobo, unit, ref, meta)
        values (p_org, p_kind, p_amount, v_bal, p_unit, p_ref, coalesce(p_meta,'{}'::jsonb));
    return query select true, v_bal;
end $$;

-- ── credit_debit: spend credit. Never goes below zero; reports any shortfall. ─
create or replace function credit_debit(
    p_org uuid, p_amount bigint, p_kind text, p_ref text,
    p_unit text default null, p_meta jsonb default '{}'::jsonb
) returns table (applied boolean, charged_kobo bigint, shortfall_kobo bigint, balance_kobo bigint)
language plpgsql as $$
declare
    v_bal bigint;
    v_take bigint;
    v_left bigint;
    v_lot record;
    v_use bigint;
begin
    if p_amount < 0 then raise exception 'debit amount must not be negative'; end if;
    if p_kind not in ('ai','meta','fee','adjust','expiry') then raise exception 'bad kind %', p_kind; end if;

    insert into credit_wallets (org_id) values (p_org) on conflict (org_id) do nothing;
    select w.balance_kobo into v_bal from credit_wallets w where w.org_id = p_org for update;

    if p_ref is not null and exists (
        select 1 from credit_ledger l where l.org_id = p_org and l.ref = p_ref
    ) then
        return query select false, 0::bigint, 0::bigint, v_bal;
        return;
    end if;

    v_take := least(p_amount, v_bal);
    v_left := v_take;
    for v_lot in
        select id, remaining_kobo from credit_lots
        where org_id = p_org and remaining_kobo > 0
        order by expires_at asc, created_at asc
        for update
    loop
        exit when v_left <= 0;
        v_use := least(v_left, v_lot.remaining_kobo);
        update credit_lots set remaining_kobo = remaining_kobo - v_use where id = v_lot.id;
        v_left := v_left - v_use;
    end loop;

    v_bal := v_bal - v_take;
    update credit_wallets set balance_kobo = v_bal, updated_at = now() where org_id = p_org;
    insert into credit_ledger (org_id, kind, amount_kobo, balance_after_kobo, unit, ref, meta)
        values (p_org, p_kind, -v_take, v_bal, p_unit, p_ref,
                coalesce(p_meta,'{}'::jsonb) || jsonb_build_object('requested_kobo', p_amount));
    return query select true, v_take, (p_amount - v_take), v_bal;
end $$;

-- ── credit_expire: write off lots past their expiry. Returns lots expired. ─
create or replace function credit_expire(p_dry_run boolean default false)
returns integer
language plpgsql as $$
declare
    v_lot record;
    v_n integer := 0;
    v_bal bigint;
begin
    for v_lot in
        select id, org_id, remaining_kobo from credit_lots
        where remaining_kobo > 0 and expires_at <= now()
        order by org_id, expires_at
    loop
        v_n := v_n + 1;
        continue when p_dry_run;
        select balance_kobo into v_bal from credit_wallets where org_id = v_lot.org_id for update;
        update credit_lots set remaining_kobo = 0 where id = v_lot.id;
        v_bal := greatest(v_bal - v_lot.remaining_kobo, 0);
        update credit_wallets set balance_kobo = v_bal, updated_at = now() where org_id = v_lot.org_id;
        insert into credit_ledger (org_id, kind, amount_kobo, balance_after_kobo, unit, ref, meta)
            values (v_lot.org_id, 'expiry', -v_lot.remaining_kobo, v_bal, 'lot_expiry',
                    'expiry:' || v_lot.id::text, jsonb_build_object('lot_id', v_lot.id));
    end loop;
    return v_n;
end $$;

revoke all on function credit_credit(uuid,bigint,text,text,text,jsonb,timestamptz) from public, anon, authenticated;
revoke all on function credit_debit(uuid,bigint,text,text,text,jsonb) from public, anon, authenticated;
revoke all on function credit_expire(boolean) from public, anon, authenticated;

-- ── Seed: one starting rate row and the Nigeria Meta rate cards ───────────
-- Nigeria figures come from secondary sources (service/utility ~US$0.0101,
-- marketing ~US$0.062); confirm against Meta's rate card before billing anyone.
insert into credit_rates (fx_ngn_per_usd, ai_markup_pct, meta_markup_pct, note)
select 1340, 50, 0, 'CREDITS-1 starting rate (FX approximate; update before go-live)'
where not exists (select 1 from credit_rates);

insert into meta_rate_cards (country, category, usd_per_message, effective_from, source) values
    ('NG','service',   0.0101, '2026-10-01', 'secondary source — confirm'),
    ('NG','utility',   0.0101, '2026-10-01', 'secondary source — confirm'),
    ('NG','marketing', 0.0620, '2026-10-01', 'secondary source — confirm')
on conflict (country, category, effective_from) do nothing;
