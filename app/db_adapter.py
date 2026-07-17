"""
Адаптер базы данных: SQLite локально, PostgreSQL (Supabase) в облаке.
Интерфейс совместим с sqlite3 — остальной код менять не нужно.
"""

import os
import sqlite3


def _is_cloud() -> bool:
    try:
        import streamlit as st
        return "supabase" in st.secrets
    except Exception:
        return False


def _get_pg_connection():
    import psycopg2
    import psycopg2.extras
    import streamlit as st

    conn = psycopg2.connect(
        host=st.secrets["supabase"]["db_host"],
        port=st.secrets["supabase"]["db_port"],
        dbname="postgres",
        user=st.secrets["supabase"]["db_user"],
        password=st.secrets["supabase"]["db_password"],
        sslmode="require",
    )
    conn.autocommit = False
    return _PgConnectionWrapper(conn)


class _PgCursorWrapper:
    """Имитирует sqlite3.Cursor для psycopg2."""

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        sql = sql.replace("DATETIME", "TIMESTAMPTZ")
        if params:
            self._cur.execute(sql, params)
        else:
            self._cur.execute(sql)

    def executemany(self, sql, seq):
        sql = sql.replace("?", "%s")
        self._cur.executemany(sql, seq)

    def executescript(self, script):
        # Разбиваем скрипт на отдельные команды
        script = script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY")
        script = script.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        script = script.replace("IF NOT EXISTS", "IF NOT EXISTS")
        script = script.replace("DATETIME", "TIMESTAMPTZ")
        # ON CONFLICT для INSERT OR IGNORE
        statements = [s.strip() for s in script.split(";") if s.strip()]
        for stmt in statements:
            if stmt.upper().startswith("INSERT INTO"):
                stmt += " ON CONFLICT DO NOTHING"
            try:
                self._cur.execute(stmt)
            except Exception:
                pass

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return _PgRow(dict(zip([d[0] for d in self._cur.description], row)))

    def fetchall(self):
        rows = self._cur.fetchall()
        if not rows:
            return []
        cols = [d[0] for d in self._cur.description]
        return [_PgRow(dict(zip(cols, r))) for r in rows]

    @property
    def lastrowid(self):
        try:
            self._cur.execute("SELECT lastval()")
            return self._cur.fetchone()[0]
        except Exception:
            return None

    @property
    def rowcount(self):
        return self._cur.rowcount


class _PgRow:
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


class _PgConnectionWrapper:
    """Имитирует sqlite3.Connection для psycopg2."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return _PgCursorWrapper(self._conn.cursor())

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._conn.commit()
        self._conn.close()


def get_connection():
    """Возвращает соединение с БД: PostgreSQL в облаке, SQLite локально."""
    if _is_cloud():
        return _get_pg_connection()
    # Локально — SQLite как прежде
    from paths import DB_PATH, init_user_dirs
    init_user_dirs()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
