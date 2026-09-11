-- Employer representation across PERM / LCA / PWD disclosure data.
-- Collapses the year-dependent attorney/firm columns into one shape so
-- Ask AI can answer "who represents X" with a single fast lookup.
-- Refresh: REFRESH MATERIALIZED VIEW CONCURRENTLY mv_employer_representation;
-- (concurrent refresh needs the unique index below)

DROP MATERIALIZED VIEW IF EXISTS mv_employer_representation;

CREATE MATERIALIZED VIEW mv_employer_representation AS
WITH perm AS (
  SELECT 'PERM'::text AS program, NULL::text AS visa_class,
         employer_name,
         NULLIF(TRIM(COALESCE(atty_law_firm, agent_firm_name)), '') AS firm,
         NULLIF(TRIM(COALESCE(
             NULLIF(TRIM(COALESCE(atty_first_name,'') || ' ' || COALESCE(atty_last_name,'')), ''),
             agent_attorney_name)), '') AS attorney,
         fiscal_year, case_status, received_date, decision_date AS decided
  FROM oflc_perm
), lca AS (
  SELECT 'LCA', visa_class, employer_name,
         NULLIF(TRIM(law_firm_name), ''),
         NULLIF(TRIM(COALESCE(agent_attorney_first_name,'') || ' ' || COALESCE(agent_attorney_last_name,'')), ''),
         fiscal_year, case_status, received_date, decision_date
  FROM oflc_lca
), pw AS (
  SELECT 'PWD', visa_class, employer_name,
         NULLIF(TRIM(law_firm_name), ''),
         NULLIF(TRIM(COALESCE(agent_attorney_first_name,'') || ' ' || COALESCE(agent_attorney_last_name,'')), ''),
         fiscal_year, case_status, received_date, determination_date
  FROM oflc_pw
), u AS (
  SELECT * FROM perm UNION ALL SELECT * FROM lca UNION ALL SELECT * FROM pw
)
SELECT program, visa_class, employer_name,
       lower(unaccent(regexp_replace(employer_name,
             '[[:punct:]]|\m(inc|llc|l\.?l\.?c\.?|corp|corporation|co|ltd|lp|llp|plc|the)\M', ' ', 'gi'))) AS employer_norm,
       firm, attorney, fiscal_year,
       COUNT(*)::int                                            AS filings,
       COUNT(*) FILTER (WHERE case_status ILIKE 'Certified%')::int AS certified,
       COUNT(*) FILTER (WHERE case_status ILIKE 'Denied%')::int    AS denied,
       MIN(COALESCE(received_date, decided))                    AS first_date,
       MAX(COALESCE(decided, received_date))                    AS last_date
FROM u
WHERE employer_name IS NOT NULL
GROUP BY 1,2,3,4,5,6,7;

CREATE UNIQUE INDEX mv_emp_rep_uniq ON mv_employer_representation
  (program, COALESCE(visa_class,''), employer_name, COALESCE(firm,''), COALESCE(attorney,''), fiscal_year);
CREATE INDEX mv_emp_rep_norm_trgm ON mv_employer_representation USING gin (employer_norm gin_trgm_ops);
CREATE INDEX mv_emp_rep_firm_trgm ON mv_employer_representation USING gin (lower(firm) gin_trgm_ops);
CREATE INDEX mv_emp_rep_atty_trgm ON mv_employer_representation USING gin (lower(attorney) gin_trgm_ops);
ANALYZE mv_employer_representation;
