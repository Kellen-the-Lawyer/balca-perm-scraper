-- Wage dashboard performance objects.
-- Re-run after re-ingesting OFLC wage or LCA data:
--   psql ... -f scripts/sql/wage_matviews.sql
-- or just refresh:
--   REFRESH MATERIALIZED VIEW mv_wage_yoy;
--   REFRESH MATERIALIZED VIEW mv_lca_soc_filings;
--   REFRESH MATERIALIZED VIEW mv_soc_titles;

-- 1. Matched Level I year-over-year comparison (alc, <350/hr sanity cap),
--    deduped per soc/area, joined on same geo_level.
DROP MATERIALIZED VIEW IF EXISTS mv_wage_yoy;
CREATE MATERIALIZED VIEW mv_wage_yoy AS
SELECT c.soc_code, c.soc_title, c.area_code, c.area_name, c.state_ab, c.geo_level,
       c.level_i AS cur_i, p.level_i AS prior_i,
       (c.level_i - p.level_i) / p.level_i * 100 AS chg
FROM (SELECT DISTINCT ON (soc_code, area_code)
             soc_code, soc_title, area_code, area_name, state_ab, geo_level, level_i
      FROM current_oews_wages
      WHERE collection_type = 'alc' AND level_i IS NOT NULL AND level_i < 350
      ORDER BY soc_code, area_code, county_name) c
JOIN (SELECT DISTINCT ON (soc_code, area_code)
             soc_code, area_code, geo_level, level_i
      FROM prior_oews_wages
      WHERE collection_type = 'alc' AND level_i IS NOT NULL AND level_i < 350
      ORDER BY soc_code, area_code, county_name) p
  ON p.soc_code = c.soc_code
 AND p.area_code = c.area_code
 AND p.geo_level = c.geo_level
WHERE p.level_i > 0;

CREATE INDEX idx_mv_yoy_soc   ON mv_wage_yoy (soc_code);
CREATE INDEX idx_mv_yoy_area  ON mv_wage_yoy (area_code);
CREATE INDEX idx_mv_yoy_state ON mv_wage_yoy (state_ab);

-- 2. Certified H-1B filings per base SOC code (top-SOC lists).
DROP MATERIALIZED VIEW IF EXISTS mv_lca_soc_filings;
CREATE MATERIALIZED VIEW mv_lca_soc_filings AS
SELECT REGEXP_REPLACE(soc_code, '\..*$', '') AS soc_base, COUNT(*) AS filings
FROM oflc_lca
WHERE visa_class = 'H-1B' AND case_status = 'Certified'
GROUP BY 1;

CREATE UNIQUE INDEX idx_mv_lca_soc ON mv_lca_soc_filings (soc_base);

-- 3. Distinct SOC code/title pairs present in current (2026-27) wage data.
DROP MATERIALIZED VIEW IF EXISTS mv_soc_titles;
CREATE MATERIALIZED VIEW mv_soc_titles AS
SELECT DISTINCT soc_code, soc_title
FROM current_oews_wages
WHERE collection_type = 'alc';

CREATE UNIQUE INDEX idx_mv_soc_titles ON mv_soc_titles (soc_code);

-- 4. Partial indexes for remaining live oflc_lca aggregates.
CREATE INDEX IF NOT EXISTS idx_lca_h1b_state
  ON oflc_lca (worksite_state)
  WHERE visa_class = 'H-1B' AND case_status = 'Certified';
CREATE INDEX IF NOT EXISTS idx_lca_h1b_city
  ON oflc_lca (worksite_city, worksite_state)
  WHERE visa_class = 'H-1B' AND case_status = 'Certified';
CREATE INDEX IF NOT EXISTS idx_lca_h1b_employer
  ON oflc_lca (employer_name)
  WHERE visa_class = 'H-1B' AND case_status = 'Certified';

-- 5. B-tree support for direct current/prior lookups (compare_area, areas list).
CREATE INDEX IF NOT EXISTS idx_cur_oews_ctype_soc_area
  ON current_oews_wages (collection_type, soc_code, area_code, county_name);
CREATE INDEX IF NOT EXISTS idx_cur_oews_ctype_area
  ON current_oews_wages (collection_type, area_code);
CREATE INDEX IF NOT EXISTS idx_pri_oews_ctype_soc_area
  ON prior_oews_wages (collection_type, soc_code, area_code, county_name);

ANALYZE current_oews_wages;
ANALYZE prior_oews_wages;
ANALYZE oflc_lca;
