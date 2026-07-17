"""
Отправка Telegram-уведомлений при обнаружении новых совпадений ТЗ.
Использует Bot API (sendMessage) через requests.
"""

import json
import logging
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

from paths import CONFIG_DIR
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TG_API = "https://api.telegram.org"

_config_cache: dict | None = None


def _load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    try:
        if CREDENTIALS_PATH.exists():
            with open(CREDENTIALS_PATH, encoding="utf-8") as f:
                creds = json.load(f)
            _config_cache = creds.get("telegram", {})
        else:
            _config_cache = {}
    except Exception as e:
        logger.error(f"Ошибка чтения credentials.json: {e}")
        _config_cache = {}
    return _config_cache


def reload_config():
    global _config_cache
    _config_cache = None


def is_configured() -> bool:
    reload_config()
    cfg = _load_config()
    return bool(cfg.get("bot_token") and cfg.get("chat_id"))


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Отправляет сообщение в Telegram. Возвращает True при успехе."""
    cfg = _load_config()
    token = cfg.get("bot_token", "")
    chat_id = cfg.get("chat_id", "")

    if not token or not chat_id:
        logger.debug("Telegram не настроен — уведомление пропущено")
        return False

    url = f"{TG_API}/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=15,
        )
        if r.status_code == 200 and r.json().get("ok"):
            return True
        logger.warning(f"Telegram API ошибка: {r.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")
        return False


def notify_new_mark(profile_name: str, candidate: dict, match_result: dict) -> bool:
    """Формирует и отправляет уведомление о новом найденном знаке."""
    risk = match_result.get("risk_level", "")
    risk_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    icon = risk_icons.get(risk, "⚠️")

    designation = candidate.get("designation", "—")
    owner = candidate.get("owner", "—")
    reg_num = candidate.get("registration_number", "")
    app_num = candidate.get("application_number", "")
    section = candidate.get("section", candidate.get("source_code", ""))
    source_url = candidate.get("source_url", "")

    num_str = ""
    if reg_num:
        num_str = f"Рег. № <b>{reg_num}</b>"
    elif app_num:
        num_str = f"Заявка № <b>{app_num}</b>"

    lines = [
        f"{icon} <b>IP Watch KZ — новое совпадение!</b>",
        f"",
        f"Профиль: <b>{profile_name}</b>",
        f"Риск: <b>{match_result.get('risk_label', risk)}</b>",
        f"",
        f"Обозначение: <b>{designation}</b>",
        f"Правообладатель: {owner}",
    ]
    if num_str:
        lines.append(num_str)
    if section:
        lines.append(f"Раздел: {section}")
    if source_url:
        lines.append(f'<a href="{source_url}">Открыть источник</a>')
    if match_result.get("reason"):
        lines.append(f"\nПричина: {match_result['reason']}")

    text = "\n".join(lines)
    return send_message(text)


def notify_monitoring_summary(summary: dict, new_marks: list[dict]) -> bool:
    """
    Итоговое уведомление после завершения мониторинга.
    Отправляется только если найдены новые совпадения.
    """
    if not summary.get("total_new"):
        return False

    lines = [
        "📊 <b>IP Watch KZ — итоги мониторинга</b>",
        "",
        f"Всего найдено: {summary.get('total_found', 0)}",
        f"Из них новых: <b>{summary.get('total_new', 0)}</b>",
    ]
    if summary.get("errors"):
        lines.append(f"Ошибок источников: {len(summary['errors'])}")

    if new_marks:
        lines.append("\n<b>Новые совпадения:</b>")
        for m in new_marks[:10]:
            risk = m.get("risk_level", "")
            icon = "🔴" if risk == "high" else "🟡" if risk == "medium" else "🟢"
            lines.append(f"  {icon} {m.get('designation', '—')} ({m.get('owner', '—')})")
        if len(new_marks) > 10:
            lines.append(f"  ... и ещё {len(new_marks) - 10}")

    return send_message("\n".join(lines))


def test_connection() -> tuple[bool, str]:
    """Проверяет соединение с ботом. Возвращает (ok, message)."""
    cfg = _load_config()
    token = cfg.get("bot_token", "")
    chat_id = cfg.get("chat_id", "")

    if not token:
        return False, "Не указан bot_token"
    if not chat_id:
        return False, "Не указан chat_id"

    try:
        # Проверяем бота
        r = requests.get(f"{TG_API}/bot{token}/getMe", timeout=10)
        if r.status_code != 200 or not r.json().get("ok"):
            return False, f"Неверный token: {r.json().get('description', r.text[:100])}"
        bot_name = r.json()["result"].get("username", "bot")

        # Отправляем тестовое сообщение
        ok = send_message("✅ IP Watch KZ подключён к Telegram-боту!")
        if ok:
            return True, f"Бот @{bot_name} подключён, тестовое сообщение отправлено"
        return False, f"Бот @{bot_name} найден, но сообщение не доставлено (проверьте chat_id)"
    except Exception as e:
        return False, f"Ошибка подключения: {e}"
