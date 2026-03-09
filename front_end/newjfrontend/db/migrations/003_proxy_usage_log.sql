-- Migration 003: proxy_usage_log
-- Tracks token usage and cost for every LLM call proxied through model_proxy.py
-- Apply: docker exec -i pgsql psql -U pguser -d database < migrations/003_proxy_usage_log.sql

CREATE TABLE IF NOT EXISTS proxy_usage_log (
    id          BIGSERIAL PRIMARY KEY,
    model       TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    cost_usd    NUMERIC(12, 8) NOT NULL DEFAULT 0,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pul_ts    ON proxy_usage_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_pul_model ON proxy_usage_log(model, ts DESC);
