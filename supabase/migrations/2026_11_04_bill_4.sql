-- BILL-4: invoice-style pay link. One active link per business; the token itself is never stored (only its SHA-256).
create table if not exists billing_pay_links (
    id               uuid primary key default gen_random_uuid(),
    org_id           uuid not null references organisations(id) on delete cascade,
    token_hash       text not null unique,
    payer_email      text,
    created_by       uuid,
    created_by_label text,
    expires_at       timestamptz not null,
    revoked_at       timestamptz,
    use_count        integer not null default 0,
    last_used_at     timestamptz,
    created_at       timestamptz not null default now()
);
create index if not exists billing_pay_links_org_idx on billing_pay_links (org_id, created_at desc);
alter table billing_pay_links enable row level security;   -- no policies: the backend (service role) only
