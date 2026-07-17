"""
Регистрация и вход пользователей с подтверждением почты.

Хранилище — база данных (через db_adapter.get_connection): SQLite локально,
Supabase/PostgreSQL в облаке. Данные переживают перезапуски Streamlit Cloud.

Таблицы: app_users, pending_registrations, user_sessions.
Пароли хэшируются bcrypt. Код подтверждения отправляется на почту через SMTP
(блок "smtp" в credentials.json локально или в st.secrets в облаке).
"""

import logging
import random
import re
import secrets
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import bcrypt

from config_manager import load_credentials

try:
    from db_adapter import get_connection
except ImportError:  # запуск вне пакета
    import sqlite3
    from paths import DB_PATH, init_user_dirs

    def get_connection():
        init_user_dirs()
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_LEGACY_USERS_FILE = _CONFIG_DIR / "users.yaml"

CODE_TTL_SECONDS = 15 * 60  # код действует 15 минут
REMEMBER_DAYS = 30          # срок cookie «Запомнить меня»
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Роли доступа
ROLES = ["standard", "premium", "admin"]
ROLE_LABELS = {"standard": "Стандарт", "premium": "Премиум", "admin": "Администратор"}
DEFAULT_ROLE = "standard"


# ─── Низкоуровневый доступ к БД ───────────────────────────────────────────────

def _fetchone(sql: str, params=()):
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        return cur.fetchone()
    finally:
        conn.close()


def _fetchall(sql: str, params=()):
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def _exec(sql: str, params=()):
    conn = get_connection()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS app_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        verified INTEGER NOT NULL DEFAULT 1,
        created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS pending_registrations (
        email TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        code TEXT NOT NULL,
        expires DOUBLE PRECISION NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS user_sessions (
        token TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        expires DOUBLE PRECISION NOT NULL
    )""",
]


def ensure_auth_schema():
    """Создаёт таблицы (best-effort) и переносит старых пользователей из users.yaml."""
    for stmt in _SCHEMA:
        try:
            _exec(stmt)
        except Exception as e:
            logger.warning(f"Не удалось создать таблицу авторизации: {e}")
    # Миграция старой роли 'user' → 'standard'
    try:
        _exec("UPDATE app_users SET role = 'standard' WHERE role = 'user'")
    except Exception:
        pass
    _seed_legacy_users()


def _seed_legacy_users():
    """Если app_users пуста — переносит пользователей из users.yaml / st.secrets."""
    try:
        if _fetchone("SELECT 1 FROM app_users LIMIT 1"):
            return
    except Exception:
        return  # таблицы ещё нет (облако без выполненного SQL)

    legacy = {}

    # 1) локальный users.yaml
    if _LEGACY_USERS_FILE.exists():
        try:
            import yaml
            with open(_LEGACY_USERS_FILE, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            legacy.update(cfg.get("credentials", {}).get("usernames", {}))
        except Exception as e:
            logger.warning(f"users.yaml не прочитан: {e}")

    # 2) Streamlit Secrets (облако)
    try:
        import streamlit as st
        sec = st.secrets.get("credentials", {})
        usernames = sec.get("usernames", {}) if hasattr(sec, "get") else {}
        for k, v in dict(usernames).items():
            legacy.setdefault(k, dict(v))
    except Exception:
        pass

    for _, u in legacy.items():
        email = str(u.get("email", "")).strip().lower()
        pwd = u.get("password", "")
        if not email or not pwd:
            continue
        try:
            _exec(
                "INSERT INTO app_users (email, name, password_hash, role, verified, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (email, u.get("name", email), pwd, u.get("role", "user"), 1,
                 time.strftime("%Y-%m-%d %H:%M:%S")),
            )
            logger.info(f"Перенесён пользователь из legacy: {email}")
        except Exception as e:
            logger.warning(f"Не удалось перенести {email}: {e}")


# ─── Пользователи ─────────────────────────────────────────────────────────────

def _row_to_user(row) -> dict:
    return {
        "username": row["email"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "verified": bool(row["verified"]),
        "created_at": row["created_at"] or "",
    }


def _get_user_row(email: str):
    email = (email or "").strip().lower()
    return _fetchone(
        "SELECT email, name, password_hash, role, verified, created_at"
        " FROM app_users WHERE LOWER(email) = ?",
        (email,),
    )


def email_exists(email: str) -> bool:
    return _get_user_row(email) is not None


# ─── Пароли ──────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ─── Вход ────────────────────────────────────────────────────────────────────

def verify_login(email: str, password: str):
    """Проверяет email+пароль. Возвращает user_dict либо None."""
    row = _get_user_row(email)
    if not row:
        return None
    if not _check_password(password, row["password_hash"]):
        return None
    if not bool(row["verified"]):
        return None
    return _row_to_user(row)


# ─── Отправка письма ─────────────────────────────────────────────────────────

def _get_smtp_config() -> dict:
    cfg = load_credentials().get("smtp", {})
    if cfg.get("host") and cfg.get("user") and cfg.get("password"):
        return cfg
    # Облако: берём из Streamlit Secrets
    try:
        import streamlit as st
        sec = st.secrets.get("smtp", {})
        if sec:
            return dict(sec)
    except Exception:
        pass
    return cfg


def smtp_configured() -> bool:
    cfg = _get_smtp_config()
    return bool(cfg.get("host") and cfg.get("user") and cfg.get("password"))


def _send_email(to_email: str, code: str) -> None:
    cfg = _get_smtp_config()
    host = cfg.get("host", "smtp.gmail.com")
    port = int(cfg.get("port", 465))
    user = cfg["user"]
    password = cfg["password"]
    from_name = cfg.get("from_name", "IP Watch KZ")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"IP Watch KZ — код подтверждения: {code}"
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = to_email

    text = (
        f"Ваш код подтверждения для регистрации в IP Watch KZ: {code}\n\n"
        f"Код действует 15 минут. Если вы не регистрировались — проигнорируйте это письмо."
    )
    html = f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;max-width:440px;margin:0 auto;">
      <h2 style="color:#1E3A8A;">⚖️ IP Watch KZ</h2>
      <p>Ваш код подтверждения регистрации:</p>
      <div style="font-size:32px;font-weight:800;letter-spacing:6px;color:#2563EB;
                  background:#F0F7FF;border:1px solid #BFDBFE;border-radius:10px;
                  padding:16px;text-align:center;margin:16px 0;">{code}</div>
      <p style="color:#64748B;font-size:13px;">Код действует 15 минут.
      Если вы не регистрировались — проигнорируйте это письмо.</p>
    </div>
    """
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
            server.login(user, password)
            server.sendmail(user, to_email, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.sendmail(user, to_email, msg.as_string())


# ─── Регистрация ─────────────────────────────────────────────────────────────

def register_start(name: str, email: str, password: str) -> dict:
    name = (name or "").strip()
    email = (email or "").strip().lower()

    if len(name) < 2:
        return {"ok": False, "error": "Укажите имя (минимум 2 символа)."}
    if not EMAIL_RE.match(email):
        return {"ok": False, "error": "Некорректный адрес электронной почты."}
    if len(password or "") < 6:
        return {"ok": False, "error": "Пароль должен быть не короче 6 символов."}
    if email_exists(email):
        return {"ok": False, "error": "Пользователь с такой почтой уже зарегистрирован. Войдите."}

    code = f"{random.randint(0, 999999):06d}"
    _exec("DELETE FROM pending_registrations WHERE email = ?", (email,))
    _exec(
        "INSERT INTO pending_registrations (email, name, password_hash, code, expires)"
        " VALUES (?, ?, ?, ?, ?)",
        (email, name, hash_password(password), code, time.time() + CODE_TTL_SECONDS),
    )

    if not smtp_configured():
        logger.warning("SMTP не настроен — код показывается в интерфейсе (dev-режим).")
        return {"ok": True, "error": "", "dev_code": code}
    try:
        _send_email(email, code)
        return {"ok": True, "error": "", "dev_code": None}
    except Exception as e:
        logger.error(f"Ошибка отправки письма: {e}")
        return {"ok": False, "error": f"Не удалось отправить письмо: {e}"}


def _get_pending(email: str):
    return _fetchone(
        "SELECT email, name, password_hash, code, expires"
        " FROM pending_registrations WHERE email = ?",
        (email,),
    )


def register_confirm(email: str, code: str) -> dict:
    email = (email or "").strip().lower()
    code = (code or "").strip()

    row = _get_pending(email)
    if not row or float(row["expires"]) <= time.time():
        if row:
            _exec("DELETE FROM pending_registrations WHERE email = ?", (email,))
        return {"ok": False, "error": "Код истёк или регистрация не начата. Начните заново."}
    if code != row["code"]:
        return {"ok": False, "error": "Неверный код подтверждения."}

    _exec(
        "INSERT INTO app_users (email, name, password_hash, role, verified, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (email, row["name"], row["password_hash"], DEFAULT_ROLE, 1,
         time.strftime("%Y-%m-%d %H:%M:%S")),
    )
    _exec("DELETE FROM pending_registrations WHERE email = ?", (email,))
    logger.info(f"Зарегистрирован пользователь: {email}")

    user_row = _get_user_row(email)
    return {"ok": True, "error": "", "user": _row_to_user(user_row)}


def resend_code(email: str) -> dict:
    email = (email or "").strip().lower()
    row = _get_pending(email)
    if not row:
        return {"ok": False, "error": "Регистрация не начата. Заполните форму заново."}
    _exec("UPDATE pending_registrations SET expires = ? WHERE email = ?",
          (time.time() + CODE_TTL_SECONDS, email))
    if not smtp_configured():
        return {"ok": True, "error": "", "dev_code": row["code"]}
    try:
        _send_email(email, row["code"])
        return {"ok": True, "error": "", "dev_code": None}
    except Exception as e:
        return {"ok": False, "error": f"Не удалось отправить письмо: {e}"}


# ─── Постоянные сессии («Запомнить меня») ────────────────────────────────────

def create_session(email: str, days: int = REMEMBER_DAYS) -> str:
    email = (email or "").strip().lower()
    token = secrets.token_urlsafe(32)
    _exec("DELETE FROM user_sessions WHERE expires <= ?", (time.time(),))
    _exec("INSERT INTO user_sessions (token, email, expires) VALUES (?, ?, ?)",
          (token, email, time.time() + days * 86400))
    return token


def get_session_user(token: str):
    if not token:
        return None
    row = _fetchone("SELECT email, expires FROM user_sessions WHERE token = ?", (token,))
    if not row or float(row["expires"]) <= time.time():
        if row:
            _exec("DELETE FROM user_sessions WHERE token = ?", (token,))
        return None
    user_row = _get_user_row(row["email"])
    return _row_to_user(user_row) if user_row else None


def destroy_session(token: str) -> None:
    if not token:
        return
    _exec("DELETE FROM user_sessions WHERE token = ?", (token,))


def _destroy_sessions_for_email(email: str) -> None:
    _exec("DELETE FROM user_sessions WHERE LOWER(email) = ?", ((email or "").strip().lower(),))


# ─── Управление пользователями (админ) ───────────────────────────────────────

def list_users() -> list:
    rows = _fetchall(
        "SELECT email, name, role, verified, created_at FROM app_users"
        " ORDER BY created_at"
    )
    return [{
        "username": r["email"],
        "name": r["name"],
        "email": r["email"],
        "role": r["role"],
        "verified": bool(r["verified"]),
        "created_at": r["created_at"] or "",
    } for r in rows]


def set_role(email: str, role: str) -> dict:
    if role not in ROLES:
        return {"ok": False, "error": "Недопустимая роль."}
    if not email_exists(email):
        return {"ok": False, "error": "Пользователь не найден."}
    _exec("UPDATE app_users SET role = ? WHERE LOWER(email) = ?",
          (role, (email or "").strip().lower()))
    return {"ok": True, "error": ""}


def delete_user(email: str) -> dict:
    if not email_exists(email):
        return {"ok": False, "error": "Пользователь не найден."}
    _exec("DELETE FROM app_users WHERE LOWER(email) = ?", ((email or "").strip().lower(),))
    _destroy_sessions_for_email(email)
    return {"ok": True, "error": ""}


def count_admins() -> int:
    row = _fetchone("SELECT COUNT(*) AS n FROM app_users WHERE role = 'admin'")
    return int(row["n"]) if row else 0
