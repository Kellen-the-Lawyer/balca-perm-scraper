-- Entity index: every named thing a question can point at, resolved to corpus/source_id.
-- Built from tables that already exist; rebuild after ingests (REFRESH MATERIALIZED VIEW).
DROP MATERIALIZED VIEW IF EXISTS entity_index;
CREATE MATERIALIZED VIEW entity_index AS
WITH
-- 1. PERM-era BALCA decisions: employer name + docket
balca AS (
  SELECT 'case'::text AS etype, employer_name AS name, case_number AS alias,
         'balca'::text AS corpus, id::text AS source_id, decision_date::text AS edate, outcome
  FROM decisions WHERE employer_name IS NOT NULL
),
-- 2. INA-era BALCA decisions: employer name parsed from the caption in chunk 0
ina AS (
  SELECT 'case', TRIM(BOTH ' ,' FROM (regexp_match(chunk_text, 'In the Matter of:\s*\n?\s*([^\n]+?),?\s*\n\s*Employer', 'i'))[1]),
         source_id, 'ina_cases', source_id, source_date, source_outcome
  FROM rag_chunks WHERE corpus = 'ina_cases' AND chunk_index = 0
    AND chunk_text ~* 'In the Matter of:\s*\n?\s*[^\n]+,?\s*\n\s*Employer'
),
-- 3. AAO / BIA precedents ingested with a "Matter of X" label
prec AS (
  SELECT DISTINCT 'case', regexp_replace(source_label, '^Matter of\s+', '', 'i'), source_label,
         corpus, source_id, source_date, source_outcome
  FROM rag_chunks WHERE corpus = 'aao' AND source_label ILIKE 'matter of %'
),
-- 4. Precedent table (name -> I&N citation) even if not chunked, so we can say "not in corpus"
prec_tbl AS (
  SELECT 'case', party_name, citation, 'precedent_decisions', id::text, NULL::text, decision_type
  FROM precedent_decisions
),
-- 5. CFR sections present in the regulation corpus
cfr AS (
  SELECT DISTINCT 'cfr', cfr_citation, source_label, 'regulation', source_id, NULL::text, NULL::text
  FROM rag_chunks WHERE corpus = 'regulation' AND cfr_citation IS NOT NULL
),
-- 6. Employers and firms from disclosure data (for tool routing and spelling variants)
emp AS (
  SELECT DISTINCT 'employer', employer_name, NULL::text, 'oflc', NULL::text, NULL::text, NULL::text
  FROM mv_employer_representation
),
firm AS (
  SELECT DISTINCT 'law_firm', firm, NULL::text, 'oflc', NULL::text, NULL::text, NULL::text
  FROM mv_employer_representation WHERE firm IS NOT NULL
),
u AS (
  SELECT * FROM balca UNION ALL SELECT * FROM ina UNION ALL SELECT * FROM prec UNION ALL SELECT * FROM prec_tbl
  UNION ALL SELECT * FROM cfr UNION ALL SELECT * FROM emp UNION ALL SELECT * FROM firm
)
SELECT row_number() OVER () AS id, etype, name, alias, corpus, source_id, edate, outcome,
       lower(unaccent(regexp_replace(name, '[[:punct:]]|\m(inc|llc|l\.?l\.?c\.?|corp|corporation|co|ltd|lp|llp|plc|the|matter of|in re)\M', ' ', 'gi'))) AS norm
FROM u WHERE name IS NOT NULL AND length(name) >= 3;

CREATE INDEX entity_index_norm_trgm ON entity_index USING gin (norm gin_trgm_ops);
CREATE INDEX entity_index_alias ON entity_index (lower(alias));
CREATE INDEX entity_index_type ON entity_index (etype);
ANALYZE entity_index;
