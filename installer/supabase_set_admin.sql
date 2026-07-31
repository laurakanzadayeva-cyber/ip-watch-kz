-- ============================================================================
-- Назначить роль администратора пользователю в Supabase.
-- Вставьте свой email в строку ниже и выполните в SQL Editor.
-- ============================================================================

-- Шаг 1: Посмотреть всех пользователей (что есть в БД)
SELECT id, email, name, role, verified, created_at FROM app_users ORDER BY created_at;

-- Шаг 2: Назначить admin (замените email на свой)
UPDATE app_users
SET role = 'admin'
WHERE LOWER(email) = 'l.kanzadayeva@sergekgroup.kz';

-- Шаг 3: Проверить результат
SELECT email, name, role FROM app_users WHERE role = 'admin';
