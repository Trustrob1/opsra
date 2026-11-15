-- WEBCHAT-EMBED-2: which websites have loaded the chat bubble (shown in Settings as "installed on ...").
-- One row per business and website host. Written by the public widget endpoint (at most every 30 min per host and worker).
CREATE TABLE IF NOT EXISTS public.webchat_widget_seen (
  org_id        uuid NOT NULL,
  host          text NOT NULL,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, host)
);
ALTER TABLE public.webchat_widget_seen ENABLE ROW LEVEL SECURITY;
