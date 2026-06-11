-- RAVEL — Migration 002 (Adım 8a)
-- Adds username/password_hash/display_name/role to students (DB-1).
-- Idempotent: ADD COLUMN IF NOT EXISTS + partial UNIQUE index.
--
-- Mevcut row'lar etkilenmez: yeni kolonlar NULLable. Auth opt-in:
--   - eski "anonim öğrenci" (LoginRequest.grade_level only) akışı korunur
--   - yeni /auth/register endpoint username/password ekler
--
-- Apply:
--   docker compose exec -T postgres psql -U ravel_admin -d ravel_db1 \
--       -f /tmp/002_auth.sql

ALTER TABLE students
    ADD COLUMN IF NOT EXISTS username      TEXT,
    ADD COLUMN IF NOT EXISTS password_hash TEXT,
    ADD COLUMN IF NOT EXISTS display_name  TEXT,
    ADD COLUMN IF NOT EXISTS role          TEXT NOT NULL DEFAULT 'student'
        CHECK (role IN ('student', 'admin'));

-- Partial unique: yalnızca username dolu olduğunda (anonim öğrenciler etkilenmez)
CREATE UNIQUE INDEX IF NOT EXISTS students_username_key
    ON students (username) WHERE username IS NOT NULL;

-- Username'le hızlı login lookup
CREATE INDEX IF NOT EXISTS students_role_idx ON students (role);

COMMENT ON COLUMN students.username      IS 'Auth identifier; NULL for anonymous students (legacy login flow).';
COMMENT ON COLUMN students.password_hash IS 'bcrypt $2a$/$2b$ hash; NULL means anonymous (no password login).';
COMMENT ON COLUMN students.role          IS 'Authorization role: student (default) | admin.';

-- ravel_app already has SELECT/INSERT/UPDATE on students; new columns inherit grants.
