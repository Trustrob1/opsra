-- WA-AUTO-4a: knowledge sources and searchable chunks for the bot. Safe to run more than once.
-- A source is one thing the owner added (an uploaded file, or typed answers). Its text is cut into small chunks once,
-- when it is added; the bot searches the chunks with Postgres full-text search and reads only the best few.
CREATE TABLE IF NOT EXISTS knowledge_sources (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  kind          text NOT NULL CHECK (kind IN ('file', 'text')),
  title         text NOT NULL,
  file_name     text,
  status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'failed')),
  chunk_count   integer NOT NULL DEFAULT 0,
  char_count    integer NOT NULL DEFAULT 0,
  error         text,
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  activated_at  timestamptz
);
CREATE INDEX IF NOT EXISTS knowledge_sources_org_idx ON knowledge_sources (org_id, created_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  source_id   uuid NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
  position    integer NOT NULL,
  content     text NOT NULL,
  fts         tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS knowledge_chunks_fts_idx ON knowledge_chunks USING gin (fts);
CREATE INDEX IF NOT EXISTS knowledge_chunks_source_idx ON knowledge_chunks (source_id, position);
ALTER TABLE knowledge_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;

-- The best chunks of an organisation's ACTIVE sources for a search expression such as 'price:* | delivery:*'.
-- p_query is built by the application from letters and digits only.
CREATE OR REPLACE FUNCTION knowledge_search(p_org uuid, p_query text, p_limit integer DEFAULT 5)
RETURNS TABLE (id uuid, source_id uuid, title text, content text, rank real)
LANGUAGE sql STABLE AS $$
  SELECT c.id, c.source_id, s.title, c.content, ts_rank(c.fts, q.query) AS rank
  FROM knowledge_chunks c
  JOIN knowledge_sources s ON s.id = c.source_id
  CROSS JOIN (SELECT to_tsquery('simple', p_query) AS query) q
  WHERE c.org_id = p_org AND s.status = 'active' AND c.fts @@ q.query
  ORDER BY rank DESC
  LIMIT LEAST(GREATEST(p_limit, 1), 10)
$$;
