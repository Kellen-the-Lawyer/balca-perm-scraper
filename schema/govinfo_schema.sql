-- GovInfo bulk-data catalog and search support.
--
-- Apply with:
--   psql "$DATABASE_URL" -f schema/govinfo_schema.sql

CREATE TABLE IF NOT EXISTS govinfo_docs (
    id               SERIAL PRIMARY KEY,
    package_id       TEXT NOT NULL UNIQUE,
    collection       TEXT NOT NULL,
    collection_label TEXT,
    title            TEXT NOT NULL,
    date_issued      DATE,
    congress         INTEGER,
    doc_class        TEXT,
    doc_number       TEXT,
    doc_version      TEXT,
    publisher        TEXT,
    source_url       TEXT,
    file_path        TEXT NOT NULL,
    file_format      TEXT,
    page_count       INTEGER,
    full_text        TEXT NOT NULL DEFAULT '',
    sections         JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    search_vector    TSVECTOR,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_govinfo_collection ON govinfo_docs(collection);
CREATE INDEX IF NOT EXISTS idx_govinfo_date ON govinfo_docs(date_issued);
CREATE INDEX IF NOT EXISTS idx_govinfo_congress ON govinfo_docs(congress);
CREATE INDEX IF NOT EXISTS idx_govinfo_doc_class ON govinfo_docs(doc_class);
CREATE INDEX IF NOT EXISTS idx_govinfo_search ON govinfo_docs USING gin(search_vector);

CREATE OR REPLACE FUNCTION update_govinfo_search_vector()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.collection_label, NEW.collection, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.package_id, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.full_text, '')), 'D');
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_govinfo_search ON govinfo_docs;
CREATE TRIGGER trg_govinfo_search
BEFORE INSERT OR UPDATE ON govinfo_docs
FOR EACH ROW EXECUTE FUNCTION update_govinfo_search_vector();

DO $$
DECLARE
    defn TEXT;
    values_sql TEXT;
BEGIN
    SELECT pg_get_constraintdef(oid)
      INTO defn
      FROM pg_constraint
     WHERE conname = 'rag_chunks_corpus_check';

    IF defn IS NULL THEN
        RETURN;
    END IF;

    IF position('govinfo' in defn) > 0 THEN
        RETURN;
    END IF;

    SELECT string_agg(quote_literal(value), ', ')
      INTO values_sql
      FROM (
        SELECT DISTINCT regexp_matches(defn, '''([^'']+)''::text', 'g') AS match
      ) s
      CROSS JOIN LATERAL (SELECT match[1] AS value) m;

    IF values_sql IS NULL OR values_sql = '' THEN
        values_sql := quote_literal('balca') || ', ' ||
                      quote_literal('aao') || ', ' ||
                      quote_literal('regulation') || ', ' ||
                      quote_literal('policy');
    END IF;

    values_sql := values_sql || ', ' || quote_literal('govinfo');

    ALTER TABLE rag_chunks DROP CONSTRAINT IF EXISTS rag_chunks_corpus_check;
    EXECUTE 'ALTER TABLE rag_chunks ADD CONSTRAINT rag_chunks_corpus_check ' ||
            'CHECK (corpus = ANY (ARRAY[' || values_sql || ']))';
END;
$$;
