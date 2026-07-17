-- ============================================================================
-- IP Watch KZ — таблицы авторизации для Supabase (PostgreSQL)
-- Выполнить ОДИН РАЗ в Supabase → SQL Editor.
-- Локально (SQLite) эти таблицы создаются автоматически.
-- ============================================================================

CREATE TABLE IF NOT EXISTS app_users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',
    verified      INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS pending_registrations (
    email         TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    code          TEXT NOT NULL,
    expires       DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS user_sessions (
    token   TEXT PRIMARY KEY,
    email   TEXT NOT NULL,
    expires DOUBLE PRECISION NOT NULL
);

-- Права для RPC-функций приложения (run_query / run_exec)
GRANT SELECT, INSERT, UPDATE, DELETE ON app_users, pending_registrations, user_sessions TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
