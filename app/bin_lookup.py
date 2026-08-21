"""
Поиск сведений об организации по БИН.

Порядок:
1. Справочник в базе (bin_directory) — то, что юрист уже вводил раньше.
2. Открытые данные data.egov.kz — работает только с ключом API
   (Настройки → Ключи доступа → data.egov.kz).
3. Пусто + понятное объяснение, что делать.

Публичные бесплатные API stat.gov.kz / salyk.kz на 2026 год закрыты,
поэтому основной рабочий путь — справочник, который наполняется вручную
один раз на компанию.
"""

import re
import logging
import requests

logger = logging.getLogger(__name__)

TIMEOUT = 12
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html;q=0.9",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

_EMPTY = {"name": "", "address": "", "director": "", "status": "",
          "kato": "", "oked": "", "source": ""}

EGOV_DATASET = "gbd_ul"  # реестр юридических лиц


def is_valid_bin(bin_str: str) -> bool:
    return bool(re.fullmatch(r"\d{12}", (bin_str or "").strip()))


# ─── Справочник в базе ───────────────────────────────────────────────────────

def ensure_bin_schema() -> None:
    """Создаёт таблицу справочника (best-effort, работает и в SQLite, и в Supabase)."""
    try:
        from database import get_connection
        conn = get_connection()
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS bin_directory (
                    bin TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    address TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    updated_at TEXT
                )"""
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Не удалось создать таблицу bin_directory: {e}")


def get_from_directory(bin_str: str) -> dict:
    try:
        from database import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT company_name, address FROM bin_directory WHERE bin = ?",
                (bin_str,),
            ).fetchone()
        finally:
            conn.close()
        if row:
            return {**_EMPTY, "name": row["company_name"] or "",
                    "address": row["address"] or "", "source": "справочник"}
    except Exception as e:
        logger.debug(f"Справочник БИН недоступен: {e}")
    return dict(_EMPTY)


def save_to_directory(bin_str: str, company_name: str, address: str = "", note: str = "") -> None:
    """Запоминает соответствие БИН → наименование, чтобы не вводить повторно."""
    if not is_valid_bin(bin_str) or not company_name.strip():
        return
    ensure_bin_schema()
    from database import get_connection
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        exists = conn.execute(
            "SELECT bin FROM bin_directory WHERE bin = ?", (bin_str,)).fetchone()
        if exists:
            # пустой адрес не затирает уже сохранённый
            conn.execute(
                """UPDATE bin_directory
                   SET company_name = ?, address = COALESCE(NULLIF(?, ''), address),
                       note = ?, updated_at = ?
                   WHERE bin = ?""",
                (company_name.strip(), address, note, now, bin_str),
            )
        else:
            conn.execute(
                """INSERT INTO bin_directory (bin, company_name, address, note, updated_at)
                   VALUES (?,?,?,?,?)""",
                (bin_str, company_name.strip(), address, note, now),
            )
        conn.commit()
    finally:
        conn.close()


def list_directory(limit: int = 200) -> list[dict]:
    try:
        from database import get_connection
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT bin, company_name, address, updated_at FROM bin_directory "
                "ORDER BY company_name LIMIT ?", (limit,)
            ).fetchall()
        finally:
            conn.close()
        return [{k: r[k] for k in r.keys()} for r in rows]
    except Exception as e:
        logger.debug(f"Не удалось прочитать справочник БИН: {e}")
        return []


# ─── Открытые данные egov (нужен ключ API) ───────────────────────────────────

def _egov_api_key() -> str:
    try:
        from config_manager import load_credentials
        key = (load_credentials().get("egov", {}) or {}).get("api_key", "")
        if key:
            return key
    except Exception:
        pass
    try:
        import streamlit as st
        return str(st.secrets.get("egov", {}).get("api_key", ""))
    except Exception:
        return ""


def _try_egov_opendata(bin_str: str) -> dict:
    api_key = _egov_api_key()
    if not api_key:
        return dict(_EMPTY)
    url = f"https://data.egov.kz/api/v4/{EGOV_DATASET}/v1"
    params = {"apiKey": api_key, "source": f'{{"size":1,"query":{{"match":{{"bin":"{bin_str}"}}}}}}'}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            logger.warning(f"data.egov.kz вернул {r.status_code} для БИН {bin_str}")
            return dict(_EMPTY)
        data = r.json()
        items = data if isinstance(data, list) else data.get("data") or []
        if not items:
            return dict(_EMPTY)
        src = items[0]
        name = src.get("nameRu") or src.get("name_ru") or src.get("name") or ""
        if not name:
            return dict(_EMPTY)
        return {
            **_EMPTY,
            "name": name,
            "address": src.get("addressRu") or src.get("address") or "",
            "director": src.get("directorRu") or src.get("director") or "",
            "status": src.get("statusRu") or src.get("status") or "",
            "oked": src.get("okedRu") or src.get("oked") or "",
            "source": "data.egov.kz",
        }
    except Exception as e:
        logger.warning(f"Ошибка data.egov.kz для БИН {bin_str}: {e}")
        return dict(_EMPTY)


# ─── Точка входа ─────────────────────────────────────────────────────────────

def lookup_company_by_bin(bin_str: str) -> dict:
    """
    Возвращает {name, address, director, status, kato, oked, source}.
    При неудаче — те же поля пустые + 'error' с объяснением.
    """
    bin_str = (bin_str or "").strip()
    if not is_valid_bin(bin_str):
        return {**_EMPTY, "error": "БИН должен содержать ровно 12 цифр"}

    found = get_from_directory(bin_str)
    if found.get("name"):
        return found

    found = _try_egov_opendata(bin_str)
    if found.get("name"):
        # запоминаем, чтобы в следующий раз не ходить в сеть
        try:
            save_to_directory(bin_str, found["name"], found.get("address", ""),
                              note="data.egov.kz")
        except Exception:
            pass
        return found

    hint = ("Автоматическое определение недоступно: бесплатные реестры "
            "(stat.gov.kz, salyk.kz) закрыли публичный доступ. "
            "Укажите наименование компании вручную — система запомнит его "
            "для этого БИН. Либо пропишите ключ API data.egov.kz в Настройках.")
    return {**_EMPTY, "error": hint}
