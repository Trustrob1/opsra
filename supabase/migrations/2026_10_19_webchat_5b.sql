-- WEBCHAT-5b: funnel can track orders, payments and link taps; paid events carry the amount.
alter table webchat_events drop constraint if exists webchat_events_kind_check;
alter table webchat_events add constraint webchat_events_kind_check
  check (kind in ('visit','started','contact','booked','handoff_sent','redirect_sent','order','paid','tap'));
alter table webchat_events add column if not exists ref text;
alter table webchat_events add column if not exists value_kobo bigint;
create index if not exists webchat_events_ref_idx on webchat_events (org_id, ref) where ref is not null;
