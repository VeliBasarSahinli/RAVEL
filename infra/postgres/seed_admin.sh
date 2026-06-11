#!/bin/bash
# RAVEL — default admin seeder (Adım 8a)
#
# Runs after init.sql + init_app_role.sh (alphabetical order in
# /docker-entrypoint-initdb.d/). Reads ADMIN_DEFAULT_USERNAME /
# ADMIN_DEFAULT_PASSWORD from env, hashes the password with pgcrypto's
# bcrypt (gen_salt('bf', 12) → $2a$12$...), and inserts the admin row
# IFF no user with that username already exists. Idempotent.
#
# pgcrypto bcrypt is wire-compatible with passlib (Gateway) — both
# accept $2a$/$2b$/$2y$ prefixes.

set -euo pipefail

ADMIN_USER="${ADMIN_DEFAULT_USERNAME:-admin}"
ADMIN_PASS="${ADMIN_DEFAULT_PASSWORD:-ravel_admin_2025}"

echo "→ Seeding default admin user '${ADMIN_USER}'…"

# pgcrypto extension already loaded by init.sql.
# Single-quote escape for safe SQL embedding.
ADMIN_USER_ESC="${ADMIN_USER//\'/\'\'}"
ADMIN_PASS_ESC="${ADMIN_PASS//\'/\'\'}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "ravel_db1" <<-SQL
    INSERT INTO students (username, password_hash, role, grade_level, display_name)
    SELECT '${ADMIN_USER_ESC}',
           crypt('${ADMIN_PASS_ESC}', gen_salt('bf', 12)),
           'admin',
           8,                       -- placeholder; admin grade_level not used in workflow
           'Yönetici'
    WHERE NOT EXISTS (
        SELECT 1 FROM students WHERE username = '${ADMIN_USER_ESC}'
    );
SQL

echo "✓ Admin user seed completed."
