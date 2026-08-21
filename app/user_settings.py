"""
Персональные настройки пользователя (хранятся в базе, а не в файле —
на Streamlit Cloud файлы не переживают перезапуск).

Сейчас используется для Telegram-уведомлений: каждый юрист подключает
свой чат и получает только свои совпадения.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "telegram_chat_id": "",
    "telegram_bot_token": "",   # пусто = общий бот приложения
    "telegram_enabled": 0,
}


def ensure_user_settings_schema() -> None:
    """Создаёт таблицу (best-effort; работает и в SQLite, и в Supabase)."""
    try:
        from database import get_connection
        conn = get_connection()
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS user_settings (
                    email TEXT PRIMARY KEY,
                    telegram_chat_id TEXT DEFAULT '',
                    telegram_bot_token TEXT DEFAULT '',
                    telegram_enabled INTEGER DEFAULT 0,
                    updated_at TEXT
                )"""
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Не удалось создать таблицу user_settings: {e}")


def get_settings(email: str) -> dict:
    email = (email or "").strip().lower()
    if not email:
        return dict(_DEFAULTS)
    try:
        from database import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT telegram_chat_id, telegram_bot_token, telegram_enabled
                   FROM user_settings WHERE email = ?""",
                (email,),
            ).fetchone()
        finally:
            conn.close()
        if row:
            return {
                "telegram_chat_id": row["telegram_chat_id"] or "",
                "telegram_bot_token": row["telegram_bot_token"] or "",
                "telegram_enabled": int(row["telegram_enabled"] or 0),
            }
    except Exception as e:
        logger.debug(f"Настройки пользователя недоступны: {e}")
    return dict(_DEFAULTS)


def save_settings(email: str, **values) -> None:
    email = (email or "").strip().lower()
    if not email:
        return
    ensure_user_settings_schema()
    allowed = {k: v for k, v in values.items() if k in _DEFAULTS}
    if not allowed:
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    from database import get_connection
    conn = get_connection()
    try:
        exists = conn.execute(
            "SELECT email FROM user_settings WHERE email = ?", (email,)).fetchone()
        if exists:
            sets = ", ".join(f"{k} = ?" for k in allowed)
            conn.execute(
                f"UPDATE user_settings SET {sets}, updated_at = ? WHERE email = ?",
                list(allowed.values()) + [now, email],
            )
        else:
            merged = {**_DEFAULTS, **allowed}
            conn.execute(
                """INSERT INTO user_settings
                   (email, telegram_chat_id, telegram_bot_token, telegram_enabled, updated_at)
                   VALUES (?,?,?,?,?)""",
                (email, merged["telegram_chat_id"], merged["telegram_bot_token"],
                 int(merged["telegram_enabled"]), now),
            )
        conn.commit()
    finally:
        conn.close()


def telegram_config_for(email: str) -> dict:
    """
    Готовый конфиг для отправки: {bot_token, chat_id} или {} если выключено.
    Токен берётся личный, а если не указан — общий бот приложения.
    """
    st_ = get_settings(email)
    if not st_["telegram_enabled"] or not st_["telegram_chat_id"]:
        return {}
    token = st_["telegram_bot_token"] or _shared_bot_token()
    if not token:
        return {}
    return {"bot_token": token, "chat_id": st_["telegram_chat_id"]}


def _shared_bot_token() -> str:
    """Общий бот приложения: из credentials.json или st.secrets."""
    try:
        from config_manager import get_telegram_config
        token = (get_telegram_config() or {}).get("bot_token", "")
        if token:
            return token
    except Exception:
        pass
    try:
        import streamlit as st
        return str(st.secrets.get("telegram", {}).get("bot_token", ""))
    except Exception:
        return ""
