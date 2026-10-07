-- PARTNER-1B: Launch Partner applications (apply on the website, verify email, staff approve)
create table if not exists public.site_partner_applications (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null references public.organisations(id) on delete cascade,
  full_name     text not null,
  email         text not null,
  phone_number  text not null,
  agency_name   text,
  code_hash     text not null,
  attempts      integer not null default 0,
  status        text not null default 'pending_code'
                check (status in ('pending_code','applied','approved','declined','blocked')),
  ip_hash       text,
  expires_at    timestamptz not null,
  verified_at   timestamptz,
  decided_at    timestamptz,
  partner_id    uuid references public.site_partners(id) on delete set null,
  created_at    timestamptz not null default now()
);
create index if not exists site_partner_applications_org_status_idx
  on public.site_partner_applications (org_id, status, created_at desc);
create index if not exists site_partner_applications_ip_idx
  on public.site_partner_applications (org_id, ip_hash, created_at);
create index if not exists site_partner_applications_email_idx
  on public.site_partner_applications (org_id, email, created_at);
create index if not exists site_partner_applications_phone_idx
  on public.site_partner_applications (org_id, phone_number, created_at);
alter table public.site_partner_applications enable row level security;
