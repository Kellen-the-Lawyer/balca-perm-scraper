-- Historical agency processing-time observations and related workload context.
-- DOL case-level durations remain calculated directly from oflc_* tables.

CREATE TABLE IF NOT EXISTS processing_time_observations (
    id                  BIGSERIAL PRIMARY KEY,
    stable_id           TEXT NOT NULL UNIQUE,
    agency              TEXT NOT NULL CHECK (agency IN ('USCIS', 'DOL')),
    series_key          TEXT NOT NULL,
    series_label        TEXT NOT NULL,
    program             TEXT,
    form_type           TEXT,
    classification      TEXT,
    office              TEXT,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    period_granularity  TEXT NOT NULL CHECK (period_granularity IN ('snapshot', 'month', 'quarter', 'fiscal_year')),
    metric_name         TEXT NOT NULL,
    statistic           TEXT NOT NULL,
    value               NUMERIC NOT NULL,
    lower_value         NUMERIC,
    upper_value         NUMERIC,
    unit                TEXT NOT NULL,
    case_count          INTEGER,
    source_name         TEXT NOT NULL,
    source_url          TEXT,
    source_report_id    INTEGER REFERENCES uscis_report_catalog(id) ON DELETE SET NULL,
    source_file         TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pto_agency_metric
    ON processing_time_observations (agency, metric_name);
CREATE INDEX IF NOT EXISTS idx_pto_series_period
    ON processing_time_observations (series_key, period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_pto_form_class
    ON processing_time_observations (form_type, classification);

