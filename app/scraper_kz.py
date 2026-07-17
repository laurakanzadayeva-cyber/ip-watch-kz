"""
Модуль для поиска по реестру Kazpatent.
Использует requests + BeautifulSoup для парсинга публичных данных.
"""

import requests
from bs4 import BeautifulSoup
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

REGISTRY_SEARCH_URL = "https://gosreestr.kazpatent.kz/Trademark/Details"
REGISTRY_BASE_URL = "https://gosreestr.kazpatent.kz"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

SESSION_TIMEOUT = 20


def _make_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def search_registry(query: str, object_type: str = "trademark") -> list[dict]:
    """
    Ищет обозначение в реестре gosreestr.kazpatent.kz.
    Возвращает список словарей с данными найденных знаков.
    """
    results = []
    session = _make_session()

    try:
        # Поиск через форму реестра
        search_params = {
            "Text": query,
            "Type": "1" if object_type == "trademark" else "2",
        }
        resp = session.get(
            REGISTRY_BASE_URL + "/Trademark/Search",
            params=search_params,
            timeout=SESSION_TIMEOUT,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        results = _parse_registry_results(soup, query)

    except requests.RequestException as e:
        logger.error(f"Ошибка при поиске в реестре: {e}")
        raise RuntimeError(f"Ошибка подключения к реестру Kazpatent: {e}")

    return results


def _parse_registry_results(soup: BeautifulSoup, query: str) -> list[dict]:
    results = []
    rows = soup.select("table.search-results tr, .trademark-item, .result-row")

    if not rows:
        # Попытка найти результаты по альтернативным селекторам
        rows = soup.select("tr[data-id], .trademark-card, article.result")

    for row in rows:
        try:
            mark = _extract_mark_from_row(row, query)
            if mark:
                results.append(mark)
        except Exception as e:
            logger.warning(f"Не удалось разобрать строку результатов: {e}")

    return results


def _extract_mark_from_row(row, query: str) -> dict | None:
    text = row.get_text(separator=" ", strip=True)
    if not text or len(text) < 2:
        return None

    link_tag = row.find("a", href=True)
    source_url = ""
    if link_tag:
        href = link_tag["href"]
        if not href.startswith("http"):
            href = REGISTRY_BASE_URL + href
        source_url = href

    designation = ""
    designation_el = row.select_one(".designation, .trademark-name, td:first-child")
    if designation_el:
        designation = designation_el.get_text(strip=True)
    elif link_tag:
        designation = link_tag.get_text(strip=True)

    if not designation:
        return None

    owner = ""
    owner_el = row.select_one(".owner, .applicant, td:nth-child(3)")
    if owner_el:
        owner = owner_el.get_text(strip=True)

    reg_number = ""
    reg_el = row.select_one(".reg-number, .number, td:nth-child(2)")
    if reg_el:
        reg_number = reg_el.get_text(strip=True)

    status_text = ""
    status_el = row.select_one(".status, td.status")
    if status_el:
        status_text = status_el.get_text(strip=True)

    classes_raw = ""
    class_el = row.select_one(".classes, .nice-class, td.classes")
    if class_el:
        classes_raw = class_el.get_text(strip=True)

    return {
        "designation": designation,
        "owner": owner,
        "registration_number": reg_number,
        "application_number": "",
        "status_mark": _normalize_status(status_text),
        "nice_classes": _parse_classes(classes_raw),
        "source_url": source_url,
        "source_code": "kz_registry",
        "object_type": "trademark",
        "publication_date": "",
        "registration_date": "",
        "application_date": "",
        "raw_text": text[:500],
    }


def _normalize_status(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["действ", "active", "зарегистр"]):
        return "active"
    if any(w in t for w in ["заявк", "applic", "pending"]):
        return "application"
    if any(w in t for w in ["прекращ", "expired", "annull"]):
        return "expired"
    if any(w in t for w in ["отказ", "refused", "reject"]):
        return "refused"
    return "unknown"


def _parse_classes(text: str) -> list[int]:
    import re
    nums = re.findall(r'\b(\d{1,2})\b', text)
    return sorted(set(int(n) for n in nums if 1 <= int(n) <= 45))


def search_bulletin(query: str) -> list[dict]:
    """
    Ищет публикации в бюллетене Kazpatent.
    """
    results = []
    session = _make_session()

    try:
        resp = session.get(
            "https://kazpatent.kz/ru/electronic-bulletin",
            timeout=SESSION_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = _parse_bulletin_page(soup, query)
    except requests.RequestException as e:
        logger.error(f"Ошибка при поиске в бюллетене: {e}")
        raise RuntimeError(f"Ошибка подключения к бюллетеню Kazpatent: {e}")

    return results


def _parse_bulletin_page(soup: BeautifulSoup, query: str) -> list[dict]:
    results = []
    items = soup.select(".bulletin-item, .bulletin-entry, article, .publication-item")

    for item in items:
        text = item.get_text(separator=" ", strip=True)
        if not text:
            continue

        q_lower = query.lower()
        if q_lower not in text.lower():
            continue

        link_tag = item.find("a", href=True)
        source_url = ""
        if link_tag:
            href = link_tag["href"]
            if not href.startswith("http"):
                href = "https://kazpatent.kz" + href
            source_url = href

        results.append({
            "designation": query,
            "owner": "",
            "registration_number": "",
            "application_number": "",
            "status_mark": "unknown",
            "nice_classes": [],
            "source_url": source_url,
            "source_code": "kz_bulletin",
            "object_type": "trademark",
            "publication_date": "",
            "registration_date": "",
            "application_date": "",
            "raw_text": text[:500],
        })

    return results
