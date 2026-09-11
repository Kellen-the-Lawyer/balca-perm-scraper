-- Partial FTS index over the authority corpora so a corpus predicate can use it directly
-- (a plain corpus IN (...) alongside the full FTS index makes the planner BitmapAND a 1M-row scan).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rag_chunks_fts_authority ON rag_chunks
  USING gin (to_tsvector('english', chunk_text))
  WHERE corpus IN ('regulation','policy','ina','govinfo','dol_faqs','final_rules','form_instructions',
                   'form_instructions_dol','uscis_checklists','cbp_ifm');
