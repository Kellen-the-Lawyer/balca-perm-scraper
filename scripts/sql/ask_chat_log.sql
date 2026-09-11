-- Per-turn log for Ask AI (multi-turn). One row per /api/ask call.
CREATE TABLE IF NOT EXISTS ask_chat_log (
    id                BIGSERIAL PRIMARY KEY,
    conversation_id   UUID,
    turn_index        INT NOT NULL DEFAULT 1,
    raw_question      TEXT NOT NULL,
    condensed_question TEXT,
    condense_ms       INT,
    corpus_filter     TEXT[],
    chunk_ids         BIGINT[],
    retrieve_ms       INT,
    tool_calls        JSONB,          -- [{name, input, result_chars, ms}]
    answer            TEXT,
    model             TEXT,
    rounds            INT,
    generate_ms       INT,
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ask_chat_log_conv_idx ON ask_chat_log (conversation_id, turn_index);
CREATE INDEX IF NOT EXISTS ask_chat_log_created_idx ON ask_chat_log (created_at DESC);
ALTER TABLE ask_chat_log ADD COLUMN IF NOT EXISTS plan JSONB;    -- planner output
ALTER TABLE ask_chat_log ADD COLUMN IF NOT EXISTS verify JSONB;  -- source-sufficiency check
