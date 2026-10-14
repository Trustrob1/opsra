-- SITE-OPTIONS OPT-3b: each version on a shared link has its own name (label) and its own price for the client.
-- price_ngn NULL = use the system price (the Premium total fee in Sites settings). Additive and safe to re-run.
alter table public.site_version_items add column if not exists price_ngn integer check (price_ngn is null or price_ngn >= 0);
