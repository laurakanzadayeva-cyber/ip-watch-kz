import sqlite3
import os
from pathlib import Path
from paths import DB_PATH, init_user_dirs

init_user_dirs()


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS monitoring_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        main_designation TEXT NOT NULL,
        object_types TEXT NOT NULL DEFAULT 'trademark,well_known',
        sources TEXT NOT NULL DEFAULT 'kz_registry,kz_bulletin',
        nice_classes TEXT DEFAULT 'all',
        excluded_owners TEXT DEFAULT '',
        search_mode TEXT NOT NULL DEFAULT 'normal',
        status TEXT NOT NULL DEFAULT 'active',
        comment TEXT DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS profile_variants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id INTEGER NOT NULL REFERENCES monitoring_profiles(id) ON DELETE CASCADE,
        variant TEXT NOT NULL,
        script TEXT DEFAULT 'any',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        url TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        last_checked DATETIME,
        last_error TEXT
    );

    CREATE TABLE IF NOT EXISTS search_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id INTEGER REFERENCES monitoring_profiles(id),
        source_code TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'running',
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        finished_at DATETIME,
        found_total INTEGER DEFAULT 0,
        found_new INTEGER DEFAULT 0,
        error_text TEXT
    );

    CREATE TABLE IF NOT EXISTS found_marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id INTEGER REFERENCES monitoring_profiles(id),
        source_code TEXT NOT NULL,
        designation TEXT NOT NULL,
        object_type TEXT DEFAULT 'trademark',
        application_number TEXT,
        registration_number TEXT,
        application_date TEXT,
        registration_date TEXT,
        publication_date TEXT,
        owner TEXT,
        owner_address TEXT,
        status_mark TEXT DEFAULT 'active',
        goods_services TEXT,
        source_url TEXT,
        image_url TEXT,
        match_reason TEXT,
        risk_level TEXT DEFAULT 'informational',
        legal_status TEXT DEFAULT 'not_reviewed',
        lawyer_comment TEXT DEFAULT '',
        include_in_report INTEGER DEFAULT 1,
        recommended_action TEXT DEFAULT 'watch',
        risk_confirmed TEXT DEFAULT 'not_set',
        recheck_needed INTEGER DEFAULT 0,
        first_found_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_checked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_duplicate INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS mark_classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mark_id INTEGER NOT NULL REFERENCES found_marks(id) ON DELETE CASCADE,
        nice_class INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS legal_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mark_id INTEGER NOT NULL REFERENCES found_marks(id) ON DELETE CASCADE,
        reviewed_by TEXT DEFAULT 'lawyer',
        legal_status TEXT,
        risk_confirmed TEXT,
        risk_level TEXT,
        include_in_report INTEGER DEFAULT 1,
        recheck_needed INTEGER DEFAULT 0,
        comment TEXT,
        recommended_action TEXT,
        reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        period_from TEXT,
        period_to TEXT,
        sources TEXT,
        profiles TEXT,
        format TEXT DEFAULT 'xlsx',
        file_path TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mark_id INTEGER NOT NULL REFERENCES found_marks(id) ON DELETE CASCADE,
        file_path TEXT NOT NULL,
        file_type TEXT,
        description TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    INSERT OR IGNORE INTO sources (code, name, url, status) VALUES
        ('kz_registry', 'Реестр Kazpatent', 'https://gosreestr.kazpatent.kz/', 'active'),
        ('kz_bulletin', 'Бюллетень Kazpatent', 'https://kazpatent.kz/ru/electronic-bulletin', 'active'),
        ('wipo', 'WIPO Global Brand Database', 'https://branddb.wipo.int/', 'planned'),
        ('madrid', 'Madrid Monitor', 'https://www.wipo.int/madrid/monitor/en/', 'planned');
    """)

    conn.commit()
    conn.close()
