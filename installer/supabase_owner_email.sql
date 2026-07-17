-- ============================================================================
-- IP Watch KZ — изоляция данных между пользователями (Supabase / PostgreSQL)
-- Выполнить ОДИН РАЗ в Supabase → SQL Editor.
-- Добавляет владельца (owner_email) к профилям и найденным знакам.
-- Существующие записи остаются с owner_email = NULL — их видит только админ
-- (админ видит все данные). Локально (SQLite) колонки добавляются автоматически.
-- ============================================================================

ALTER TABLE monitoring_profiles ADD COLUMN IF NOT EXISTS owner_email TEXT;
ALTER TABLE found_marks         ADD COLUMN IF NOT EXISTS owner_email TEXT;

-- (необязательно) привязать все текущие данные к главному администратору,
-- чтобы они были «его», а не ничьи. Подставьте свою почту при необходимости:
-- UPDATE monitoring_profiles SET owner_email = 'l.kanzadayeva@sergekgroup.kz' WHERE owner_email IS NULL;
-- UPDATE found_marks         SET owner_email = 'l.kanzadayeva@sergekgroup.kz' WHERE owner_email IS NULL;

-- Индексы для быстрой фильтрации по владельцу
CREATE INDEX IF NOT EXISTS idx_profiles_owner ON monitoring_profiles (owner_email);
CREATE INDEX IF NOT EXISTS idx_found_marks_owner ON found_marks (owner_email);
