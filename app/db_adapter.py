"""
Адаптер базы данных: SQLite локально, Supabase HTTPS в облаке.
Интерфейс совместим с sqlite3 — остальной код менять не нужно.
"""

import sqlite3


def _is_cloud() -> bool:
    try:
        import streamlit as st
        return "supabase" in st.secrets
    except Exception:
        return False


def _get_supabase_client():
    from supabase import create_client
    import streamlit as st
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["service_role_key"]
    return create_client(url, key)


def _interpolate(sql: str, params) -> str:
    """Подставляет ? placeholders с экранированием значений."""
    if not params:
        return sql
    parts = sql.split("?")
    result = parts[0]
    for i, param in enumerate(params):
        if param is None:
            result += "NULL"
        elif isinstance(param, bool):
            result += "TRUE" if param else "FALSE"
        elif isinstance(param, (int, float)):
            result += str(param)
        else:
            result += "'" + str(param).replace("'", "''") + "'"
        result += parts[i + 1]
    return result


class _SupaCursor:
    def __init__(self, client):
        self._client = client
        self._results = []
        self._lastrowid = None
        self.rowcount = 0

    def execute(self, sql: str, params=None):
        sql = sql.strip()
        # Конвертируем SQLite-специфичный синтаксис
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY")
        sql = sql.replace("DATETIME", "TIMESTAMPTZ")
        sql_final = _interpolate(sql, params)
        upper = sql_final.lstrip().upper()

        if upper.startswith("SELECT") or upper.startswith("WITH"):
            resp = self._client.rpc("run_query", {"sql": sql_final}).execute()
            self._results = resp.data if resp.data else []
        elif upper.startswith("PRAGMA") or upper.startswith("--"):
            self._results = []
        else:
            resp = self._client.rpc("run_exec", {"sql": sql_final}).execute()
            if resp.data:
                self.rowcount = int(resp.data.get("rowcount") or 0)
                self._lastrowid = resp.data.get("lastrowid")
            self._results = []

    def executemany(self, sql: str, seq):
        for params in seq:
            self.execute(sql, params)

    def executescript(self, script: str):
        # На облаке таблицы уже созданы через SQL Editor — пропускаем CREATE
        statements = [s.strip() for s in script.split(";") if s.strip()]
        for stmt in statements:
            upper = stmt.lstrip().upper()
            if upper.startswith("CREATE") or upper.startswith("PRAGMA"):
                continue
            # Конвертируем INSERT OR IGNORE
            stmt = stmt.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if stmt.lstrip().upper().startswith("INSERT"):
                stmt += " ON CONFLICT DO NOTHING"
            try:
                self.execute(stmt)
            except Exception:
                pass

    def fetchone(self):
        if not self._results:
            return None
        return _SupaRow(self._results[0])

    def fetchall(self):
        return [_SupaRow(r) for r in self._results]

    @property
    def lastrowid(self):
        return self._lastrowid


class _SupaRow:
    """Имитирует sqlite3.Row — доступ по имени и индексу."""

    def __init__(self, data: dict):
        self._data = data
        self._keys = list(data.keys())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[self._keys[key]]
        return self._data[key]

    def __iter__(self):
        return iter(self._data.values())

    def keys(self):
        return self._keys

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __repr__(self):
        return repr(self._data)


class _SupaConnection:
    """Имитирует sqlite3.Connection для Supabase."""

    def __init__(self, client):
        self._client = client

    def cursor(self):
        return _SupaCursor(self._client)

    def execute(self, sql: str, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        pass  # Supabase — autocommit

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def get_connection():
    """Возвращает соединение: Supabase в облаке, SQLite локально."""
    if _is_cloud():
        return _SupaConnection(_get_supabase_client())
    from paths import DB_PATH, init_user_dirs
    init_user_dirs()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
