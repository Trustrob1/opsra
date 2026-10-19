-- CREDITS-2 — credit packs and the order columns the Buy credits screen needs.
-- Additive and idempotent: safe to run twice. Packs give exactly what they cost (no bonus).
-- Prices are kobo: 500000 = N5,000.

alter table credit_orders add column if not exists checkout_url text;
alter table credit_orders add column if not exists pack_name text;
create index if not exists credit_orders_org_idx on credit_orders (org_id, created_at desc);

insert into credit_packs (name, price_kobo, credit_kobo, sort_order)
select v.name, v.price_kobo, v.price_kobo, v.sort_order
from (values
    ('N5,000',  500000::bigint,  1),
    ('N10,000', 1000000::bigint, 2),
    ('N25,000', 2500000::bigint, 3),
    ('N50,000', 5000000::bigint, 4)
) as v(name, price_kobo, sort_order)
where not exists (select 1 from credit_packs p where p.price_kobo = v.price_kobo);
