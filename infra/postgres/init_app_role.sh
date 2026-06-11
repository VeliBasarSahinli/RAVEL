#!/bin/bash
# RAVEL — application role creation
# Runs after init.sql (alphabetical order in /docker-entrypoint-initdb.d/).
# Creates ravel_app: the restricted role that every Python service uses.
#
# Privilege model:
#   DB-1 / students          → SELECT, INSERT, UPDATE  (no DELETE)
#   DB-2 / interaction_logs  → SELECT, INSERT only     (append-only enforcement)
#
# The superuser (POSTGRES_USER) is reserved for migrations and ops only.

set -euo pipefail

if [ -z "${POSTGRES_APP_PASSWORD:-}" ]; then
  echo "✗ POSTGRES_APP_PASSWORD env var is empty. Aborting role creation." >&2
  exit 1
fi

# Escape single quotes for safe SQL string literal embedding.
APP_PW_ESCAPED="${POSTGRES_APP_PASSWORD//\'/\'\'}"

echo "→ Creating ravel_app role…"

# Role itself is a cluster-level object — created once.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-SQL
    CREATE ROLE ravel_app WITH LOGIN PASSWORD '${APP_PW_ESCAPED}';
SQL

# ── DB-1: students ──────────────────────────────────────────────────
# UPDATE is granted because Bandit may update learning_style_vector as the
# learner profile evolves. DELETE is intentionally withheld.
#
# llm_configs (Adım 7): SELECT/INSERT/UPDATE/DELETE — admin paneli üzerinden
# yönetildiği için DELETE de gerekli (config silme akışı). Tablo bir admin
# konfigürasyon objesi; append-only DB-2 kuralının dışındadır.
echo "→ Granting DB-1 privileges (students + llm_configs)…"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "ravel_db1" <<-'SQL'
    GRANT CONNECT ON DATABASE ravel_db1 TO ravel_app;
    GRANT USAGE   ON SCHEMA public      TO ravel_app;
    GRANT SELECT, INSERT, UPDATE         ON students    TO ravel_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON llm_configs TO ravel_app;
SQL

# ── DB-2: interaction_logs ──────────────────────────────────────────
# Strict append-only: UPDATE and DELETE are NOT granted, deliberately.
# This is the DB-level enforcement of CLAUDE.md's event-sourcing rule.
echo "→ Granting DB-2 privileges (SELECT, INSERT on interaction_logs)…"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "ravel_db2" <<-'SQL'
    GRANT CONNECT ON DATABASE ravel_db2 TO ravel_app;
    GRANT USAGE   ON SCHEMA public      TO ravel_app;
    GRANT SELECT, INSERT ON interaction_logs TO ravel_app;
SQL

echo "✓ ravel_app role created and privileges granted."
