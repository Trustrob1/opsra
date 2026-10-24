-- WA-AUTO-4c: weekly refresh of website and Google Doc sources, and the list of questions the bot could not answer.
-- Safe to run more than once. Needs 4a and 4b.
ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS auto_refresh boolean NOT NULL DEFAULT true;
ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS content_hash text;
ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS last_refreshed_at timestamptz;
ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS refresh_error text;

CREATE TABLE IF NOT EXISTS knowledge_gaps (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  question    text NOT NULL,
  question_key text NOT NULL,                 -- the question in lower case without punctuation, to count repeats
  times_asked integer NOT NULL DEFAULT 1,
  status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'dismissed')),
  last_lead_id uuid,
  first_asked_at timestamptz NOT NULL DEFAULT now(),
  last_asked_at  timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
);
CREATE INDEX IF NOT EXISTS knowledge_gaps_org_idx ON knowledge_gaps (org_id, status, last_asked_at DESC);
ALTER TABLE knowledge_gaps ENABLE ROW LEVEL SECURITY;
