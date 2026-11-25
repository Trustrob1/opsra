-- ONLINE-ALL (25 Nov 2026): the website can sell from every location. When on (the default), the website, web chat
-- shop and AI show the total across all active locations, and a website order holds each item wherever the stock is.
alter table public.stock_settings
  add column if not exists online_all boolean not null default true;

-- check: should return 1 row with online_all = true for Royal Rest
select o.name, s.online_all from public.stock_settings s join public.organisations o on o.id = s.org_id;
