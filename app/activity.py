"""
Журнал событий (activity log) для ленты активности, уведомлений и «Журнала действий».

Хранение — в общей БД (SQLite локально, Supabase в облаке) через db_adapter.
События изолируются по владельцу (owner_email): обычный пользователь видит свои,
администратор — все.
"""

import logging
import time

try:
    from db_adapter import get_connection
except ImportError:
    import sqlite3
    from paths import DB_PATH, init_user_dirs

    def get_connection():
        init_user_dirs()
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

logger = logging.getLogger(__name__)

# тип события → (иконка, читаемый заголовок по умолчанию)
EVENT_META = {
    "profile_created":  ("📁", "Создан профиль"),
    "profile_updated":  ("✏️", "Изменён профиль"),
    "profile_deleted":  ("🗑️", "Удалён профиль"),
    "check_started":    ("▶️", "Запущена проверка"),
    "check_completed":  ("✅", "Проверка завершена"),
    "mark_found":       ("🔎", "Найден товарный знак"),
    "mark_reviewed":    ("⚖️", "Изменён статус знака"),
    "report_exported":  ("📄", "Экспортирован отчёт"),
    "role_changed":     ("🛡️", "Изменена роль"),
    "user_deleted":     ("👤", "Удалён пользователь"),
    "deadline_changed": ("⏳", "Изменён срок"),
}


def _exec(sql, params=()):
    conn = get_connection()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def ensure_events_schema():
    try:
        _exec("""CREATE TABLE IF NOT EXISTS activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            event_type TEXT NOT NULL,
            title TEXT,
            detail TEXT,
            user_email TEXT,
            owner_email TEXT
        )""")
    except Exception as e:
        logger.warning(f"Не удалось создать activity_events: {e}")


def log_event(event_type, title="", detail="", user_email="", owner_email=None):
    """Записывает событие. title пустой → берётся из EVENT_META."""
    if not title:
        title = EVENT_META.get(event_type, ("", event_type))[1]
    try:
        _exec(
            "INSERT INTO activity_events (created_at, event_type, title, detail, user_email, owner_email)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), event_type, title, detail or "",
             (user_email or "").strip().lower(),
             (owner_email or user_email or "").strip().lower() or None),
        )
    except Exception as e:
        logger.warning(f"Не удалось записать событие {event_type}: {e}")


def get_events(owner_email=None, limit=50, types=None):
    """
    Возвращает список событий (dict). owner_email=None → все (админ).
    types — список event_type для фильтра (например, только уведомления).
    """
    conn = get_connection()
    try:
        sql = ("SELECT created_at, event_type, title, detail, user_email "
               "FROM activity_events WHERE 1=1")
        params = []
        if owner_email is not None:
            sql += " AND owner_email = ?"
            params.append((owner_email or "").strip().lower())
        if types:
            ph = ",".join("?" * len(types))
            sql += f" AND event_type IN ({ph})"
            params.extend(types)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        rows = conn.execute(sql, params).fetchall()
    except Exception as e:
        logger.warning(f"Не удалось прочитать события: {e}")
        return []
    finally:
        conn.close()
    out = []
    for r in rows:
        ic = EVENT_META.get(r["event_type"], ("•", ""))[0]
        out.append({
            "created_at": r["created_at"], "event_type": r["event_type"],
            "icon": ic, "title": r["title"], "detail": r["detail"] or "",
            "user_email": r["user_email"] or "",
        })
    return out
