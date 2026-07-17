"""
Регистрация и вход пользователей с подтверждением почты.

Хранилище пользователей — config/users.yaml (совместимо со старым форматом
streamlit_authenticator: credentials.usernames.<key> = {email, name, password, role}).
Пароли хэшируются bcrypt. Код подтверждения отправляется на почту через SMTP
(настройки — блок "smtp" в credentials.json). Ожидающие подтверждения регистрации
хранятся в config/pending.json с TTL.
"""

import json
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

import yaml
import bcrypt

from config_manager import load_credentials

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_USERS_FILE = _CONFIG_DIR / "users.yaml"
_PENDING_FILE = _CONFIG_DIR / "pending.json"
_SESSIONS_FILE = _CONFIG_DIR / "sessions.json"

REMEMBER_DAYS = 30  # срок действия cookie «Запомнить меня»

CODE_TTL_SECONDS = 15 * 60  # код действует 15 минут
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ─── Хранилище пользователей ─────────────────────────────────────────────────

def _default_config() -> dict:
    return {
        "cookie": {
            "expiry_days": 30,
            "key": "ipwatch_sergek_secret_key_2024",
            "name": "ipwatch_auth",
        },
        "credentials": {"usernames": {}},
    }


def load_users() -> dict:
    if _USERS_FILE.exists():
        with open(_USERS_FILE, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = _default_config()
    cfg.setdefault("credentials", {}).setdefault("usernames", {})
    return cfg


def save_users(cfg: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_USERS_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _find_user_by_email(cfg: dict, email: str):
    """Возвращает (username_key, user_dict) или (None, None)."""
    email = email.strip().lower()
    for key, u in cfg["credentials"]["usernames"].items():
        if str(u.get("email", "")).strip().lower() == email:
            return key, u
    return None, None


def email_exists(email: str) -> bool:
    key, _ = _find_user_by_email(load_users(), email)
    return key is not None


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
    """
    Проверяет пару email+пароль.
    Возвращает user_dict (с добавленным ключом 'username') либо None.
    """
    cfg = load_users()
    key, user = _find_user_by_email(cfg, email)
    if not user:
        return None
    if not _check_password(password, user.get("password", "")):
        return None
    if not user.get("verified", True):  # старые записи считаем подтверждёнными
        return None
    return {**user, "username": key}


# ─── Ожидающие подтверждения ─────────────────────────────────────────────────

def _load_pending() -> dict:
    if _PENDING_FILE.exists():
        try:
            with open(_PENDING_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_pending(data: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _purge_expired(pending: dict) -> dict:
    now = time.time()
    return {e: v for e, v in pending.items() if v.get("expires", 0) > now}


# ─── Отправка письма ─────────────────────────────────────────────────────────

def _get_smtp_config() -> dict:
    return load_credentials().get("smtp", {})


def smtp_configured() -> bool:
    cfg = _get_smtp_config()
    return bool(cfg.get("host") and cfg.get("user") and cfg.get("password"))


def _send_email(to_email: str, code: str) -> None:
    """Отправляет письмо с кодом. Бросает исключение при ошибке SMTP."""
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
    else:  # 587 / STARTTLS
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.sendmail(user, to_email, msg.as_string())


# ─── Регистрация ─────────────────────────────────────────────────────────────

def register_start(name: str, email: str, password: str) -> dict:
    """
    Шаг 1 регистрации: валидация, генерация кода, отправка письма.
    Возвращает {"ok": bool, "error": str, "dev_code": str|None}.
    dev_code заполняется, только если SMTP не настроен (режим разработки).
    """
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
    pending = _purge_expired(_load_pending())
    pending[email] = {
        "name": name,
        "password_hash": hash_password(password),
        "code": code,
        "expires": time.time() + CODE_TTL_SECONDS,
    }
    _save_pending(pending)

    if not smtp_configured():
        logger.warning("SMTP не настроен — код показывается в интерфейсе (dev-режим).")
        return {"ok": True, "error": "", "dev_code": code}

    try:
        _send_email(email, code)
        return {"ok": True, "error": "", "dev_code": None}
    except Exception as e:
        logger.error(f"Ошибка отправки письма: {e}")
        return {"ok": False, "error": f"Не удалось отправить письмо: {e}"}


def register_confirm(email: str, code: str) -> dict:
    """
    Шаг 2 регистрации: проверка кода, создание пользователя в users.yaml.
    Возвращает {"ok": bool, "error": str, "user": dict|None}.
    """
    email = (email or "").strip().lower()
    code = (code or "").strip()

    pending = _purge_expired(_load_pending())
    entry = pending.get(email)
    if not entry:
        return {"ok": False, "error": "Код истёк или регистрация не начата. Начните заново."}
    if code != entry["code"]:
        return {"ok": False, "error": "Неверный код подтверждения."}

    cfg = load_users()
    username = email  # ключ = почта (уникально)
    cfg["credentials"]["usernames"][username] = {
        "email": email,
        "name": entry["name"],
        "password": entry["password_hash"],
        "role": "user",
        "verified": True,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_users(cfg)

    del pending[email]
    _save_pending(pending)

    logger.info(f"Зарегистрирован пользователь: {email}")
    user = cfg["credentials"]["usernames"][username]
    return {"ok": True, "error": "", "user": {**user, "username": username}}


def resend_code(email: str) -> dict:
    """Повторно отправляет код для уже начатой регистрации."""
    email = (email or "").strip().lower()
    pending = _purge_expired(_load_pending())
    entry = pending.get(email)
    if not entry:
        return {"ok": False, "error": "Регистрация не начата. Заполните форму заново."}
    entry["expires"] = time.time() + CODE_TTL_SECONDS
    _save_pending(pending)
    if not smtp_configured():
        return {"ok": True, "error": "", "dev_code": entry["code"]}
    try:
        _send_email(email, entry["code"])
        return {"ok": True, "error": "", "dev_code": None}
    except Exception as e:
        return {"ok": False, "error": f"Не удалось отправить письмо: {e}"}


# ─── Постоянные сессии («Запомнить меня») ────────────────────────────────────

def _load_sessions() -> dict:
    if _SESSIONS_FILE.exists():
        try:
            with open(_SESSIONS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_sessions(data: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_session(email: str, days: int = REMEMBER_DAYS) -> str:
    """Создаёт токен долгой сессии, возвращает его (для записи в cookie)."""
    email = (email or "").strip().lower()
    token = secrets.token_urlsafe(32)
    sessions = {t: v for t, v in _load_sessions().items() if v.get("expires", 0) > time.time()}
    sessions[token] = {"email": email, "expires": time.time() + days * 86400}
    _save_sessions(sessions)
    return token


def get_session_user(token: str):
    """По токену cookie возвращает user_dict (с 'username') либо None."""
    if not token:
        return None
    sessions = _load_sessions()
    entry = sessions.get(token)
    if not entry or entry.get("expires", 0) <= time.time():
        if token in sessions:
            del sessions[token]
            _save_sessions(sessions)
        return None
    cfg = load_users()
    key, user = _find_user_by_email(cfg, entry["email"])
    if not user:
        return None
    return {**user, "username": key}


def destroy_session(token: str) -> None:
    """Удаляет токен сессии (при выходе)."""
    if not token:
        return
    sessions = _load_sessions()
    if token in sessions:
        del sessions[token]
        _save_sessions(sessions)


def _destroy_sessions_for_email(email: str) -> None:
    """Аннулирует все долгие сессии пользователя (например, при удалении/блокировке)."""
    email = (email or "").strip().lower()
    sessions = _load_sessions()
    remaining = {t: v for t, v in sessions.items() if v.get("email") != email}
    if len(remaining) != len(sessions):
        _save_sessions(remaining)


# ─── Управление пользователями (админ) ───────────────────────────────────────

def list_users() -> list:
    """Список всех пользователей для отображения (без хэшей паролей)."""
    cfg = load_users()
    out = []
    for key, u in cfg["credentials"]["usernames"].items():
        out.append({
            "username": key,
            "name": u.get("name", ""),
            "email": u.get("email", ""),
            "role": u.get("role", "user"),
            "verified": u.get("verified", True),
            "created_at": u.get("created_at", ""),
        })
    out.sort(key=lambda x: x.get("created_at", ""))
    return out


def set_role(email: str, role: str) -> dict:
    """Меняет роль пользователя (admin/user)."""
    if role not in ("admin", "user"):
        return {"ok": False, "error": "Недопустимая роль."}
    cfg = load_users()
    key, user = _find_user_by_email(cfg, email)
    if not user:
        return {"ok": False, "error": "Пользователь не найден."}
    user["role"] = role
    save_users(cfg)
    return {"ok": True, "error": ""}


def delete_user(email: str) -> dict:
    """Удаляет пользователя и его сессии."""
    cfg = load_users()
    key, user = _find_user_by_email(cfg, email)
    if not user:
        return {"ok": False, "error": "Пользователь не найден."}
    del cfg["credentials"]["usernames"][key]
    save_users(cfg)
    _destroy_sessions_for_email(email)
    return {"ok": True, "error": ""}


def count_admins() -> int:
    cfg = load_users()
    return sum(1 for u in cfg["credentials"]["usernames"].values() if u.get("role") == "admin")
