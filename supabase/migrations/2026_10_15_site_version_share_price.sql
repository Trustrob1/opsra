-- SITE-OPTIONS OPT-3b: the builder's price for the site on a shared versions link.
-- NULL = use the system price (the Premium total fee in Sites settings). Additive and safe to re-run.
alter table public.site_version_shares add column if not exists client_price_ngn integer check (client_price_ngn is null or client_price_ngn >= 0);
