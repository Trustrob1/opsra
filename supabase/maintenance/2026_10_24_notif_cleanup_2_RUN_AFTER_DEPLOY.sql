-- NOTIF-CLEANUP 2 - run ONCE in the Supabase SQL editor, AFTER the code from cleanup 1 is deployed and live
-- (otherwise the old worker fills the table again). Best at a quiet hour.
--
-- Why not DELETE: removing ~9.5 million rows with DELETE would itself use up the disk I/O budget (no index on created_at, so every
-- batch scans the whole table). Instead: keep what is worth keeping in a temporary copy, empty the table (TRUNCATE is almost free),
-- and put the kept rows back. notifications has no tables pointing at it, no triggers and is not in a publication, so this is safe.
-- Everything is in one transaction: if anything fails, nothing changes. New notifications wait a few seconds while the table is locked.
--
-- Kept: every notification that is NOT an SLA alert or aging alert, and any SLA/aging alert from the last 3 days.

BEGIN;
SET LOCAL statement_timeout = 0;
LOCK TABLE public.notifications IN EXCLUSIVE MODE;

CREATE TEMP TABLE notifications_keep ON COMMIT DROP AS
  SELECT * FROM public.notifications
   WHERE type NOT IN ('lead_sla_breach', 'lead_sla_escalation', 'lead_aging')
      OR created_at > now() - interval '3 days';

SELECT (SELECT count(*) FROM public.notifications) AS rows_before, (SELECT count(*) FROM notifications_keep) AS rows_kept;

TRUNCATE public.notifications;
INSERT INTO public.notifications SELECT * FROM notifications_keep;
COMMIT;

-- The "unread" lookups: a small partial index that matches them, replacing the one that was never used.
DROP INDEX IF EXISTS public.idx_notifications_user_id;
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON public.notifications (user_id, org_id, created_at DESC) WHERE is_read = false;
ANALYZE public.notifications;

SELECT count(*) AS rows_now, pg_size_pretty(pg_total_relation_size('public.notifications')) AS total_size FROM public.notifications;
