-- =============================================================================
-- USCIS Statistical Data Schema
-- =============================================================================
-- Three layers:
--   1. uscis_report_catalog   -- metadata for every entry in the Data Library
--   2. uscis_report_files     -- downloaded files keyed to catalog entries
--   3. uscis_stat_rows        -- normalized, typed rows extracted from each file
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Catalog -- one row per Data Library entry (1,728 entries)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uscis_report_catalog (
    id              SERIAL PRIMARY KEY,
    stable_id       TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    description     TEXT,
    published_date  DATE,
    file_url        TEXT NOT NULL,
    file_type       TEXT NOT NULL CHECK (file_type IN ('xlsx','csv','pdf','xls','zip','other')),
    file_size_kb    NUMERIC,
    categories      TEXT[],
    fiscal_year     INTEGER,
    quarter         INTEGER,
    form_type       TEXT,
    scraped_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_catalog_fiscal_year  ON uscis_report_catalog (fiscal_year);
CREATE INDEX IF NOT EXISTS idx_catalog_form_type    ON uscis_report_catalog (form_type);
CREATE INDEX IF NOT EXISTS idx_catalog_file_type    ON uscis_report_catalog (file_type);
CREATE INDEX IF NOT EXISTS idx_catalog_published    ON uscis_report_catalog (published_date);
CREATE INDEX IF NOT EXISTS idx_catalog_categories   ON uscis_report_catalog USING GIN (categories);

-- ---------------------------------------------------------------------------
-- 2. Files -- tracks download state for each catalog entry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uscis_report_files (
    id              SERIAL PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES uscis_report_catalog(id) ON DELETE CASCADE,
    local_path      TEXT,
    file_size_bytes BIGINT,
    sha256          TEXT,
    download_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (download_status IN ('pending','downloading','done','failed','skipped')),
    error_message   TEXT,
    downloaded_at   TIMESTAMPTZ,
    ingested_at     TIMESTAMPTZ,
    UNIQUE (report_id)
);

CREATE INDEX IF NOT EXISTS idx_files_status  ON uscis_report_files (download_status);
CREATE INDEX IF NOT EXISTS idx_files_report  ON uscis_report_files (report_id);

-- ---------------------------------------------------------------------------
-- 3. Stat rows -- one row per observation extracted from a file
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uscis_stat_rows (
    id              BIGSERIAL PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES uscis_report_catalog(id) ON DELETE CASCADE,
    sheet_name      TEXT,
    row_index       INTEGER,
    metric_name     TEXT,
    metric_category TEXT,
    fiscal_year     INTEGER,
    fiscal_quarter  INTEGER,
    period_label    TEXT,
    period_start    DATE,
    period_end      DATE,
    country_of_birth TEXT,
    state_code      TEXT,
    uscis_office    TEXT,
    form_type       TEXT,
    case_status     TEXT,
    eligibility_category TEXT,
    naics_code      TEXT,
    soc_code        TEXT,
    numeric_value   NUMERIC,
    text_value      TEXT,
    unit            TEXT,
    stable_id       TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (stable_id)
);

CREATE INDEX IF NOT EXISTS idx_stat_report      ON uscis_stat_rows (report_id);
CREATE INDEX IF NOT EXISTS idx_stat_metric      ON uscis_stat_rows (metric_name);
CREATE INDEX IF NOT EXISTS idx_stat_form        ON uscis_stat_rows (form_type);
CREATE INDEX IF NOT EXISTS idx_stat_fy          ON uscis_stat_rows (fiscal_year);
CREATE INDEX IF NOT EXISTS idx_stat_period      ON uscis_stat_rows (period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_stat_status      ON uscis_stat_rows (case_status);
CREATE INDEX IF NOT EXISTS idx_stat_country     ON uscis_stat_rows (country_of_birth);
CREATE INDEX IF NOT EXISTS idx_stat_state       ON uscis_stat_rows (state_code);
CREATE INDEX IF NOT EXISTS idx_stat_category    ON uscis_stat_rows (metric_category);
