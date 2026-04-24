-- OFLC Disclosure Data Schema
-- PERM, LCA, and Prevailing Wage programs FY2020-FY2026
-- Loads into perm_decisions database alongside BALCA, AAO, regulations

-- ── PERM ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS oflc_perm (
  id                        SERIAL PRIMARY KEY,
  case_number               TEXT NOT NULL,
  fiscal_year               TEXT NOT NULL,
  source_file               TEXT NOT NULL,
  case_status               TEXT,
  received_date             DATE,
  decision_date             DATE,
  occupation_type           TEXT,
  -- Employer
  employer_name             TEXT,
  employer_state            TEXT,
  employer_city             TEXT,
  employer_postal_code      TEXT,
  employer_fein             TEXT,
  employer_naics            TEXT,
  employer_num_payroll      INTEGER,
  employer_year_commenced   INTEGER,
  -- Attorney/Agent
  atty_law_firm             TEXT,
  atty_last_name            TEXT,
  atty_first_name           TEXT,
  atty_state                TEXT,
  -- Job opportunity
  job_title                 TEXT,
  soc_code                  TEXT,
  soc_title                 TEXT,
  wage_from                 NUMERIC,
  wage_to                   NUMERIC,
  wage_per                  TEXT,
  -- Worksite
  worksite_city             TEXT,
  worksite_state            TEXT,
  worksite_postal_code      TEXT,
  worksite_bls_area         TEXT,
  -- PWD
  pwd_number                TEXT,
  -- Flags
  fw_currently_employed     TEXT,
  is_multiple_locations     TEXT,
  employer_layoff           TEXT,
  ingested_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_oflc_perm_case_fy
  ON oflc_perm(case_number, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_oflc_perm_status      ON oflc_perm(case_status);
CREATE INDEX IF NOT EXISTS idx_oflc_perm_decision     ON oflc_perm(decision_date);
CREATE INDEX IF NOT EXISTS idx_oflc_perm_employer     ON oflc_perm(employer_name);
CREATE INDEX IF NOT EXISTS idx_oflc_perm_fein         ON oflc_perm(employer_fein);
CREATE INDEX IF NOT EXISTS idx_oflc_perm_state        ON oflc_perm(employer_state);
CREATE INDEX IF NOT EXISTS idx_oflc_perm_soc          ON oflc_perm(soc_code);
CREATE INDEX IF NOT EXISTS idx_oflc_perm_fy           ON oflc_perm(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_oflc_perm_naics        ON oflc_perm(employer_naics);
CREATE INDEX IF NOT EXISTS idx_oflc_perm_firm         ON oflc_perm(atty_law_firm);

-- ── LCA (H-1B, H-1B1, E-3) ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS oflc_lca (
  id                        SERIAL PRIMARY KEY,
  case_number               TEXT NOT NULL,
  fiscal_year               TEXT NOT NULL,
  source_file               TEXT NOT NULL,
  case_status               TEXT,
  visa_class                TEXT,
  received_date             DATE,
  decision_date             DATE,
  begin_date                DATE,
  end_date                  DATE,
  -- Employer
  employer_name             TEXT,
  employer_state            TEXT,
  employer_city             TEXT,
  employer_postal_code      TEXT,
  employer_fein             TEXT,
  naics_code                TEXT,
  -- Attorney/Agent
  law_firm_name             TEXT,
  agent_last_name           TEXT,
  agent_first_name          TEXT,
  agent_state               TEXT,
  -- Job
  job_title                 TEXT,
  soc_code                  TEXT,
  soc_title                 TEXT,
  full_time_position        TEXT,
  total_worker_positions    INTEGER,
  -- Wages
  wage_from                 NUMERIC,
  wage_to                   NUMERIC,
  wage_unit                 TEXT,
  prevailing_wage           NUMERIC,
  pw_unit                   TEXT,
  pw_wage_level             TEXT,
  pw_oes_year               TEXT,
  -- Worksite
  worksite_city             TEXT,
  worksite_state            TEXT,
  worksite_postal_code      TEXT,
  -- Compliance flags
  h1b_dependent             TEXT,
  willful_violator          TEXT,
  ingested_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_oflc_lca_case_fy
  ON oflc_lca(case_number, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_status        ON oflc_lca(case_status);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_visa          ON oflc_lca(visa_class);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_decision      ON oflc_lca(decision_date);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_employer      ON oflc_lca(employer_name);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_fein          ON oflc_lca(employer_fein);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_state         ON oflc_lca(employer_state);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_soc           ON oflc_lca(soc_code);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_fy            ON oflc_lca(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_naics         ON oflc_lca(naics_code);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_firm          ON oflc_lca(law_firm_name);
CREATE INDEX IF NOT EXISTS idx_oflc_lca_pw_level      ON oflc_lca(pw_wage_level);

-- ── Prevailing Wage ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS oflc_pw (
  id                        SERIAL PRIMARY KEY,
  case_number               TEXT NOT NULL,
  fiscal_year               TEXT NOT NULL,
  source_file               TEXT NOT NULL,
  case_status               TEXT,
  visa_class                TEXT,
  received_date             DATE,
  determination_date        DATE,
  -- Employer
  employer_name             TEXT,
  employer_state            TEXT,
  employer_city             TEXT,
  employer_postal_code      TEXT,
  employer_fein             TEXT,
  naics_code                TEXT,
  -- Attorney/Agent
  law_firm_name             TEXT,
  agent_last_name           TEXT,
  agent_first_name          TEXT,
  -- Job
  job_title                 TEXT,
  soc_code                  TEXT,
  soc_title                 TEXT,
  -- PWD
  pwd_wage_rate             NUMERIC,
  pwd_unit                  TEXT,
  pw_wage_level             TEXT,
  wage_source               TEXT,
  bls_area                  TEXT,
  pwd_wage_expiration_date  DATE,
  -- Worksite
  worksite_city             TEXT,
  worksite_state            TEXT,
  worksite_postal_code      TEXT,
  ingested_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_oflc_pw_case_fy
  ON oflc_pw(case_number, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_status         ON oflc_pw(case_status);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_visa           ON oflc_pw(visa_class);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_determination  ON oflc_pw(determination_date);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_employer       ON oflc_pw(employer_name);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_fein           ON oflc_pw(employer_fein);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_state          ON oflc_pw(employer_state);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_soc            ON oflc_pw(soc_code);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_fy             ON oflc_pw(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_naics          ON oflc_pw(naics_code);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_bls            ON oflc_pw(bls_area);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_firm           ON oflc_pw(law_firm_name);
CREATE INDEX IF NOT EXISTS idx_oflc_pw_level          ON oflc_pw(pw_wage_level);

SELECT 'OFLC schema ready' AS status;
