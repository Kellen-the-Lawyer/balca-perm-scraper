-- =============================================================================
-- USCIS Electronic Reading Room (FOIA) Schema
-- =============================================================================
-- Catalog + file tracking for FOIA documents from
-- https://www.uscis.gov/records/electronic-reading-room
--
-- These are text documents (policy memos, RAIO lesson plans, procedures
-- manuals, leadership guidance) worth ingesting into rag_chunks under a
-- new 'uscis_foia' corpus for legal research -- unlike the statistical
-- spreadsheets, which live in uscis_stat_rows.
-- =============================================================================

CREATE TABLE IF NOT EXISTS uscis_foia_documents (
    id              SERIAL PRIMARY KEY,
    stable_id       TEXT NOT NULL UNIQUE,        -- derived from URL path
    title           TEXT NOT NULL,
    description     TEXT,
    published_date  DATE,
    file_url        TEXT NOT NULL,
    file_type       TEXT NOT NULL CHECK (file_type IN ('pdf','xlsx','xls','csv','doc','docx','zip','html','other')),
    file_size_kb    NUMERIC,
    doc_category    TEXT,                        -- foia / guides / lesson-plans / etc (from URL path)

    -- Download + ingest tracking
    local_path      TEXT,
    file_size_bytes BIGINT,
    sha256          TEXT,
    download_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (download_status IN ('pending','downloading','done','failed','skipped')),
    error_message   TEXT,
    downloaded_at   TIMESTAMPTZ,
    ingested_at     TIMESTAMPTZ,                 -- set when chunked into rag_chunks

    scraped_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_foia_status     ON uscis_foia_documents (download_status);
CREATE INDEX IF NOT EXISTS idx_foia_category   ON uscis_foia_documents (doc_category);
CREATE INDEX IF NOT EXISTS idx_foia_file_type  ON uscis_foia_documents (file_type);
CREATE INDEX IF NOT EXISTS idx_foia_published  ON uscis_foia_documents (published_date);
