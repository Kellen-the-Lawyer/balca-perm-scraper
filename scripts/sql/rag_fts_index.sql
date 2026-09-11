CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rag_chunks_fts ON rag_chunks USING gin (to_tsvector('english', chunk_text));
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rag_chunks_label_trgm ON rag_chunks USING gin (lower(source_label) gin_trgm_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_decisions_employer_trgm ON decisions USING gin (lower(employer_name) gin_trgm_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rag_chunks_corpus_date ON rag_chunks (corpus, source_date);
