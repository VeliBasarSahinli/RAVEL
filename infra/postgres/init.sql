-- RAVEL — PostgreSQL initialization
-- Creates two logical databases (DB-1 static profile, DB-2 interaction logs)
-- and the tables described in CLAUDE.md.
--
-- This script runs exactly once, on first container start, when
-- /var/lib/postgresql/data is empty. To re-run: stop the stack and
--   docker volume rm ravel_postgres_data

-- =====================================================================
-- DB-1: students  (static profile)
-- =====================================================================
CREATE DATABASE ravel_db1;
\connect ravel_db1

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE students (
    student_id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    grade_level             INTEGER      NOT NULL CHECK (grade_level BETWEEN 5 AND 8),
    learning_style_vector   REAL[]       NOT NULL DEFAULT ARRAY[0.5, 0.5]::REAL[],
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT learning_style_vector_len
        CHECK (array_length(learning_style_vector, 1) = 2)
);

CREATE INDEX students_grade_idx ON students (grade_level);

COMMENT ON TABLE  students                       IS 'Static student profile (DB-1).';
COMMENT ON COLUMN students.learning_style_vector IS '[visual_weight, verbal_weight], default [0.5, 0.5] (Cold Start).';

-- =====================================================================
-- DB-1: llm_configs  (per-agent LLM provider configuration, Adım 7)
-- One active config per agent_name; api_key is AES-256-GCM ciphertext
-- (nonce(12) || ciphertext || tag(16)) bound to ENCRYPTION_KEY env var.
-- Never log api_key in plaintext.
-- =====================================================================
CREATE TABLE llm_configs (
    config_id      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name     TEXT         NOT NULL UNIQUE,
    provider       TEXT         NOT NULL CHECK (provider IN
                                  ('anthropic','openai','gemini','openrouter','ollama','custom')),
    model_name     TEXT         NOT NULL,
    api_key        BYTEA,                     -- AES-256-GCM ciphertext, NULL for ollama (no key)
    endpoint_url   TEXT,                      -- required for ollama/custom, NULL otherwise
    max_tokens     INTEGER      NOT NULL DEFAULT 1024 CHECK (max_tokens > 0),
    temperature    REAL         NOT NULL DEFAULT 0.7 CHECK (temperature BETWEEN 0.0 AND 2.0),
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX llm_configs_active_idx ON llm_configs (agent_name) WHERE is_active;

COMMENT ON TABLE  llm_configs IS
  'Per-agent LLM provider configuration. agent_name is canonical (e.g. '
  '"orchestrator_text", "orchestrator_manim", "orchestrator_correction"). '
  'api_key is AES-256-GCM encrypted; only the orchestrator (knowing '
  'ENCRYPTION_KEY) can decrypt at request time.';
COMMENT ON COLUMN llm_configs.api_key      IS 'AES-256-GCM: 12B nonce || ciphertext || 16B tag.';
COMMENT ON COLUMN llm_configs.endpoint_url IS 'Required for ollama/custom; ignored for managed APIs.';

-- =====================================================================
-- DB-2: interaction_logs  (append-only event log / event sourcing)
-- See CLAUDE.md: "DB-2'ye asla UPDATE veya DELETE yapılmaz."
-- =====================================================================
\connect postgres
CREATE DATABASE ravel_db2;
\connect ravel_db2

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE interaction_logs (
    log_id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id          UUID         NOT NULL,
    topic_id            TEXT         NOT NULL,                      -- e.g. "math_6_uslu_ifadeler"
    taxonomic_level     TEXT         NOT NULL,                      -- "A1" .. "C2" (Bloom)
    action_taken        TEXT         NOT NULL CHECK (action_taken IN ('text', 'step_by_step', 'video')),
    is_correct          BOOLEAN      NOT NULL,
    time_spent_seconds  INTEGER      NOT NULL CHECK (time_spent_seconds >= 0),
    frustration_index   REAL         NOT NULL CHECK (frustration_index BETWEEN 0.0 AND 1.0),
    reward_signal       REAL         NOT NULL,
    "timestamp"         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Common query patterns: per-student timeline, per-topic taxonomy slicing
CREATE INDEX interaction_logs_student_time_idx
    ON interaction_logs (student_id, "timestamp" DESC);

CREATE INDEX interaction_logs_topic_taxon_idx
    ON interaction_logs (topic_id, taxonomic_level);

COMMENT ON TABLE interaction_logs IS
  'Append-only event log (DB-2). UPDATE/DELETE blocked at the DB level: the only role '
  'authorized to write here is ravel_app, and its grants exclude UPDATE/DELETE. '
  'See init_app_role.sh for the role + grant definitions.';

-- =====================================================================
-- Application role (ravel_app) is created in init_app_role.sh, which
-- runs immediately after this script (alphabetically next in
-- /docker-entrypoint-initdb.d/). The shell script is needed instead of
-- inlining here because we read the role's password from the
-- POSTGRES_APP_PASSWORD env var, which .sql files cannot interpolate.
-- =====================================================================
