-- STORE-7: count when a tagged catalog link is opened (no cart needed), so Insights can show visits per tag.
-- Adds one more allowed event kind. Safe to run twice. Nothing else changes.
alter table webchat_events drop constraint if exists webchat_events_kind_check;
alter table webchat_events add constraint webchat_events_kind_check
  check (kind in ('visit','started','contact','booked','handoff_sent','redirect_sent','order','paid','tap','catalog_visit'));
