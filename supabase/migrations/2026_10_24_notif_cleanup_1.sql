-- NOTIF-CLEANUP 1 (run BEFORE deploying the code): stop the same alert being sent over and over.
-- The SLA worker (every 5 minutes) and the daily aging check used to insert a new notification for the same lead every run
-- (about 9.5 million rows). The lead now remembers when it was alerted. Safe to run more than once.

ALTER TABLE leads ADD COLUMN IF NOT EXISTS sla_breach_notified_at timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS sla_escalated_at       timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS aging_notified_at      timestamptz;

-- Leads that are already overdue HAVE been alerted (many times): mark them so deploying does not send a fresh round.
UPDATE leads SET sla_breach_notified_at = now()
 WHERE sla_breach_notified_at IS NULL AND first_contacted_at IS NULL AND deleted_at IS NULL AND assigned_to IS NOT NULL
   AND score NOT IN ('unscored', 'converted', 'lost');
UPDATE leads SET aging_notified_at = now()
 WHERE aging_notified_at IS NULL AND stage NOT IN ('won', 'lost') AND last_activity_at <= now() - interval '3 days';

-- Daily retention (called by the notification_retention worker): read notifications after 90 days, any after 180 days.
CREATE OR REPLACE FUNCTION purge_old_notifications(p_batch integer DEFAULT 5000)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE n integer;
BEGIN
  WITH doomed AS (
    SELECT id FROM notifications
     WHERE (is_read AND created_at < now() - interval '90 days') OR created_at < now() - interval '180 days'
     LIMIT LEAST(GREATEST(p_batch, 1), 20000)
  )
  DELETE FROM notifications x USING doomed d WHERE x.id = d.id;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;
REVOKE ALL ON FUNCTION purge_old_notifications(integer) FROM PUBLIC, anon, authenticated;
