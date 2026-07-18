-- ============================================================================
-- IP Watch KZ — журнал событий (лента активности, уведомления, журнал действий)
-- Выполнить ОДИН РАЗ в Supabase → SQL Editor.
-- Локально (SQLite) таблица создаётся автоматически.
-- ============================================================================

CREATE TABLE IF NOT EXISTS activity_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  TEXT,
    event_type  TEXT NOT NULL,
    title       TEXT,
    detail      TEXT,
    user_email  TEXT,
    owner_email TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_owner ON activity_events (owner_email);
CREATE INDEX IF NOT EXISTS idx_events_created ON activity_events (created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON activity_events TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
