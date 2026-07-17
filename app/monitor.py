"""
Основная логика мониторинга: запуск поиска, сохранение результатов, дедупликация.
"""

import logging
from datetime import datetime
from database import get_connection, init_db
from similarity import compare, RISK_LABELS
from scraper_kazpatent import search_trademarks as search_registry_new
from scraper_kz import search_bulletin
from telegram_notifier import notify_new_mark, notify_monitoring_summary, is_configured as tg_configured

logger = logging.getLogger(__name__)


def run_monitoring(
    profile_ids: list[int] | None = None,
    source_codes: list[str] | None = None,
) -> dict:
    """
    Запускает мониторинг по указанным профилям и источникам.
    Если profile_ids=None — по всем активным профилям.
    Если source_codes=None — по всем активным источникам.
    Возвращает сводку: найдено/новых/ошибок.
    """
    init_db()
    conn = get_connection()

    profiles = _load_profiles(conn, profile_ids)
    active_sources = _load_sources(conn, source_codes)

    summary = {"total_found": 0, "total_new": 0, "errors": [], "run_ids": []}
    new_marks_all: list[dict] = []

    for profile in profiles:
        variants = _load_variants(conn, profile["id"])
        all_designations = [profile["main_designation"]] + [v["variant"] for v in variants]
        profile_name = profile["main_designation"]
        _profile_owner = profile["owner_email"] if "owner_email" in profile.keys() else None

        for source in active_sources:
            run_id = _start_run(conn, profile["id"], source["code"])
            summary["run_ids"].append(run_id)
            found_count = 0
            new_count = 0

            try:
                candidates = _fetch_candidates(source["code"], all_designations)

                for ctrl in all_designations:
                    for candidate in candidates:
                        result = compare(ctrl, candidate["designation"])
                        if not result["is_match"]:
                            continue

                        is_new = _save_mark(conn, profile["id"], source["code"], candidate, result,
                                            _profile_owner)
                        found_count += 1
                        if is_new:
                            new_count += 1
                            new_marks_all.append({**candidate, **result})
                            if tg_configured():
                                notify_new_mark(profile_name, candidate, result)

                _update_source_status(conn, source["code"], success=True)
                _finish_run(conn, run_id, "success", found_count, new_count)

            except Exception as e:
                err_msg = str(e)
                logger.error(f"Ошибка мониторинга [{source['code']}]: {err_msg}")
                summary["errors"].append({"source": source["code"], "error": err_msg})
                _update_source_status(conn, source["code"], success=False, error=err_msg)
                _finish_run(conn, run_id, "error", 0, 0, err_msg)

            summary["total_found"] += found_count
            summary["total_new"] += new_count

    conn.commit()
    conn.close()
    return summary


def _load_profiles(conn, profile_ids):
    if profile_ids:
        placeholders = ",".join("?" * len(profile_ids))
        return conn.execute(
            f"SELECT * FROM monitoring_profiles WHERE id IN ({placeholders}) AND status='active'",
            profile_ids,
        ).fetchall()
    return conn.execute(
        "SELECT * FROM monitoring_profiles WHERE status='active'"
    ).fetchall()


def _load_sources(conn, source_codes):
    if source_codes:
        placeholders = ",".join("?" * len(source_codes))
        return conn.execute(
            f"SELECT * FROM sources WHERE code IN ({placeholders}) AND status='active'",
            source_codes,
        ).fetchall()
    return conn.execute(
        "SELECT * FROM sources WHERE status='active'"
    ).fetchall()


def _load_variants(conn, profile_id):
    return conn.execute(
        "SELECT * FROM profile_variants WHERE profile_id=?", (profile_id,)
    ).fetchall()


def _fetch_candidates(source_code: str, designations: list[str]) -> list[dict]:
    candidates = []
    for designation in designations:
        try:
            if source_code == "kz_registry":
                items = search_registry_new(designation, object_type="trademark", max_pages=5)
            elif source_code == "kz_bulletin":
                items = search_bulletin(designation)
            else:
                items = []
            candidates.extend(items)
        except Exception as e:
            logger.warning(f"Ошибка при поиске '{designation}' в {source_code}: {e}")
            # Продолжаем с другими обозначениями, не прерываем весь мониторинг
    return candidates


def _save_mark(conn, profile_id: int, source_code: str, candidate: dict, match_result: dict,
               owner_email: str | None = None) -> bool:
    existing = conn.execute(
        """SELECT id FROM found_marks
           WHERE profile_id=? AND source_code=? AND designation=?
             AND (registration_number=? OR application_number=?)""",
        (
            profile_id,
            source_code,
            candidate["designation"],
            candidate.get("registration_number", ""),
            candidate.get("application_number", ""),
        ),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE found_marks SET last_checked_at=CURRENT_TIMESTAMP WHERE id=?",
            (existing["id"],),
        )
        return False

    cur = conn.execute(
        """INSERT INTO found_marks (
            profile_id, source_code, designation, object_type,
            application_number, registration_number,
            application_date, registration_date, publication_date,
            owner, owner_address, status_mark, goods_services,
            source_url, match_reason, risk_level, owner_email
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            profile_id,
            source_code,
            candidate["designation"],
            candidate.get("object_type", "trademark"),
            candidate.get("application_number", ""),
            candidate.get("registration_number", ""),
            candidate.get("application_date", ""),
            candidate.get("registration_date", ""),
            candidate.get("publication_date", ""),
            candidate.get("owner", ""),
            candidate.get("owner_address", ""),
            candidate.get("status_mark", "unknown"),
            candidate.get("goods_services", ""),
            candidate.get("source_url", ""),
            match_result["reason"],
            match_result["risk_level"],
            owner_email,
        ),
    )
    mark_id = cur.lastrowid
    if mark_id is None:
        row = conn.execute(
            "SELECT id FROM found_marks WHERE designation=? AND source_code=? ORDER BY id DESC LIMIT 1",
            (candidate["designation"], source_code),
        ).fetchone()
        mark_id = row[0] if row else None

    for cls in candidate.get("nice_classes", []):
        conn.execute(
            "INSERT INTO mark_classes (mark_id, nice_class) VALUES (?,?)",
            (mark_id, cls),
        )

    return True


def _start_run(conn, profile_id, source_code) -> int:
    cur = conn.execute(
        "INSERT INTO search_runs (profile_id, source_code, status) VALUES (?,?,?)",
        (profile_id, source_code, "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    if run_id is None:
        row = conn.execute(
            "SELECT id FROM search_runs WHERE profile_id=? AND source_code=? ORDER BY id DESC LIMIT 1",
            (profile_id, source_code),
        ).fetchone()
        run_id = row[0] if row else 0
    return run_id


def _finish_run(conn, run_id, status, found, new_count, error=None):
    conn.execute(
        """UPDATE search_runs
           SET status=?, finished_at=CURRENT_TIMESTAMP,
               found_total=?, found_new=?, error_text=?
           WHERE id=?""",
        (status, found, new_count, error, run_id),
    )


def _update_source_status(conn, code: str, success: bool, error: str | None = None):
    if success:
        conn.execute(
            "UPDATE sources SET last_checked=CURRENT_TIMESTAMP, last_error=NULL WHERE code=?",
            (code,),
        )
    else:
        conn.execute(
            "UPDATE sources SET last_checked=CURRENT_TIMESTAMP, last_error=? WHERE code=?",
            (error, code),
        )
