-- SITE-ADDONS A1-3: the owner's private "My leads" link.
-- Additive and safe to re-run. Run in the Supabase SQL editor BEFORE deploying the A1-3 code.
-- One random token per client workspace. Whoever holds the link can read that site's enquiries (like the payment link),
-- so it is long and unguessable and is only shown to staff and sent to the site owner.
alter table public.site_workspaces add column if not exists leads_token text;
create unique index if not exists site_workspaces_leads_token_uq on public.site_workspaces (leads_token) where leads_token is not null;
