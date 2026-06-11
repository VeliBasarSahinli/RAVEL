-- RAVEL — Migration 001 (Adım 7a)
-- Adds llm_configs table to DB-1 + grants for ravel_app.
-- Idempotent (IF NOT EXISTS / DO blocks) → safe to re-run.
--
-- Apply:
--   docker compose exec -T postgres psql -U ravel_admin -d ravel_db1 \
--       -f /tmp/001_llm_configs.sql
-- (script copies this file into the container before apply)

-- 1. Schema --------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS llm_configs (
    config_id      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name     TEXT         NOT NULL UNIQUE,
    provider       TEXT         NOT NULL CHECK (provider IN
                                  ('anthropic','openai','gemini','openrouter','ollama','custom')),
    model_name     TEXT         NOT NULL,
    api_key        BYTEA,
    endpoint_url   TEXT,
    max_tokens     INTEGER      NOT NULL DEFAULT 1024 CHECK (max_tokens > 0),
    temperature    REAL         NOT NULL DEFAULT 0.7 CHECK (temperature BETWEEN 0.0 AND 2.0),
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS llm_configs_active_idx
    ON llm_configs (agent_name) WHERE is_active;

COMMENT ON TABLE  llm_configs IS
  'Per-agent LLM provider configuration. api_key is AES-256-GCM ciphertext '
  '(12B nonce || ciphertext || 16B tag), bound to ENCRYPTION_KEY env.';

-- 2. Grants for ravel_app -----------------------------------------------
-- Admin paneli config CRUD yapacağı için DELETE de açık.
GRANT SELECT, INSERT, UPDATE, DELETE ON llm_configs TO ravel_app;

-- 3. updated_at trigger -------------------------------------------------
CREATE OR REPLACE FUNCTION llm_configs_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS llm_configs_updated_at ON llm_configs;
CREATE TRIGGER llm_configs_updated_at
    BEFORE UPDATE ON llm_configs
    FOR EACH ROW EXECUTE FUNCTION llm_configs_set_updated_at();
