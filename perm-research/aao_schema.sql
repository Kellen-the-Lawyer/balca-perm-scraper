-- AAO Decisions table
CREATE TABLE aao_decisions (
  id              SERIAL PRIMARY KEY,
  filename        TEXT NOT NULL UNIQUE,
  pdf_path        TEXT NOT NULL,
  title           TEXT,
  decision_date   DATE,
  form_type       TEXT,
  regulation      TEXT,
  outcome         TEXT CHECK (outcome IN ('Dismissed','Sustained','Remanded','Withdrawn','Unknown')),
  full_text       TEXT NOT NULL DEFAULT '',
  search_vector   TSVECTOR,
  text_extracted  BOOLEAN DEFAULT FALSE,
  ingested_at     TIMESTAMPTZ DEFAULT NOW(),
  parse_errors    TEXT
);

CREATE INDEX idx_aao_search     ON aao_decisions USING GIN(search_vector);
CREATE INDEX idx_aao_date       ON aao_decisions(decision_date);
CREATE INDEX idx_aao_form       ON aao_decisions(form_type);
CREATE INDEX idx_aao_regulation ON aao_decisions(regulation);
CREATE INDEX idx_aao_outcome    ON aao_decisions(outcome);
CREATE INDEX idx_aao_filename   ON aao_decisions(filename);

CREATE OR REPLACE FUNCTION update_aao_search_vector() RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.form_type, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.regulation, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.full_text, '')), 'D');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_aao_search
  BEFORE INSERT OR UPDATE ON aao_decisions
  FOR EACH ROW EXECUTE FUNCTION update_aao_search_vector();

-- Update project_cases for cross-corpus support
ALTER TABLE project_cases ADD COLUMN source TEXT NOT NULL DEFAULT 'balca';
ALTER TABLE project_cases DROP CONSTRAINT project_cases_project_id_decision_id_key;
ALTER TABLE project_cases ALTER COLUMN decision_id DROP NOT NULL;
ALTER TABLE project_cases ADD COLUMN aao_decision_id INTEGER REFERENCES aao_decisions(id) ON DELETE CASCADE;
CREATE UNIQUE INDEX idx_pc_balca ON project_cases(project_id, decision_id) WHERE decision_id IS NOT NULL;
CREATE UNIQUE INDEX idx_pc_aao   ON project_cases(project_id, aao_decision_id) WHERE aao_decision_id IS NOT NULL;

-- Update project_notes for cross-corpus support
ALTER TABLE project_notes ADD COLUMN source TEXT NOT NULL DEFAULT 'balca';
ALTER TABLE project_notes ADD COLUMN aao_decision_id INTEGER REFERENCES aao_decisions(id) ON DELETE SET NULL;

SELECT 'Casebase schema ready' AS status;
