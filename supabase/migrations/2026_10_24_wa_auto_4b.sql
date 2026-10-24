-- WA-AUTO-4b: knowledge from a website address or a public Google Doc. Safe to run more than once.
ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS page_count integer NOT NULL DEFAULT 0;
ALTER TABLE knowledge_sources DROP CONSTRAINT IF EXISTS knowledge_sources_kind_check;
ALTER TABLE knowledge_sources ADD CONSTRAINT knowledge_sources_kind_check CHECK (kind IN ('file', 'text', 'url', 'gdoc'));
ALTER TABLE knowledge_sources DROP CONSTRAINT IF EXISTS knowledge_sources_status_check;
ALTER TABLE knowledge_sources ADD CONSTRAINT knowledge_sources_status_check CHECK (status IN ('processing', 'draft', 'active', 'failed'));
