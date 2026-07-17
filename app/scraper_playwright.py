"""
Playwright-based парсер для:
  - gosreestr.kazpatent.kz (реестр ТЗ и ОТЗ)
  - ebulletin.kazpatent.kz (электронный бюллетень)
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

from paths import SCREENSHOTS_DIR, DOWNLOADS_DIR

REGISTRY_BASE = "https://gosreestr.kazpatent.kz"
BULLETIN_BASE = "http://ebulletin.kazpatent.kz"


def _get_browser(playwright):
    return playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )


# ──────────────────────────────────────────────────────────
# РЕЕСТР — полная выгрузка всех ТЗ
# ──────────────────────────────────────────────────────────

def scrape_registry_full(
    query: str = "",
    object_type: str = "trademark",
    max_pages: int = 100,
    progress_callback=None,
) -> list[dict]:
    """
    Полная выгрузка записей из реестра gosreestr.kazpatent.kz.
    object_type: 'trademark' | 'well_known' | 'international'
    Если query пустой — скачивает ВСЕ записи.
    """
    from playwright.sync_api import sync_playwright

    endpoint_map = {
        "trademark": "/Trademark",
        "well_known": "/TIM",
        "international": "/InternationalTrademark",
    }
    endpoint = endpoint_map.get(object_type, "/Trademark")
    search_url = REGISTRY_BASE + endpoint

    results = []

    with sync_playwright() as pw:
        browser = _get_browser(pw)
        page = browser.new_page()
        page.set_extra_http_headers({"Accept-Language": "ru-RU,ru;q=0.9"})

        try:
            page.goto(REGISTRY_BASE, wait_until="domcontentloaded", timeout=30000)
            page.goto(search_url, wait_until="networkidle", timeout=30000)

            # Заполняем поле поиска если задан запрос
            if query:
                name_selectors = [
                    "input[name*='Name']",
                    "input[name*='name']",
                    "input[placeholder*='наимен']",
                    "input[type='text']:first-of-type",
                ]
                for sel in name_selectors:
                    try:
                        if page.locator(sel).count() > 0:
                            page.fill(sel, query)
                            break
                    except Exception:
                        pass

            # Нажимаем кнопку поиска
            btn_selectors = [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Найти')",
                "input[value='Найти']",
            ]
            for sel in btn_selectors:
                try:
                    if page.locator(sel).count() > 0:
                        page.click(sel)
                        page.wait_for_load_state("networkidle", timeout=15000)
                        break
                except Exception:
                    pass

            page_num = 0
            while page_num < max_pages:
                page_num += 1
                if progress_callback:
                    progress_callback(page_num, len(results))

                page_results = _extract_registry_rows(page, object_type)
                results.extend(page_results)

                if not page_results:
                    break

                # Переход на следующую страницу
                next_btn = page.locator("a[rel='next'], .pagination .next, a:has-text('»'), a:has-text('Следующ')")
                if next_btn.count() == 0:
                    break
                try:
                    next_btn.first.click()
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    break

        except Exception as e:
            logger.error(f"Ошибка при парсинге реестра: {e}")
            raise RuntimeError(f"Ошибка при работе с реестром Kazpatent: {e}")
        finally:
            browser.close()

    return results


def _extract_registry_rows(page, object_type: str) -> list[dict]:
    results = []
    try:
        rows = page.locator("table tbody tr, .result-item, .trademark-item").all()
        if not rows:
            rows = page.locator("tr[data-id], .card-item").all()
    except Exception:
        return []

    for row in rows:
        try:
            text = row.inner_text()
            if not text.strip():
                continue

            cells = row.locator("td").all()
            cell_texts = [c.inner_text().strip() for c in cells]

            if len(cell_texts) < 2:
                continue

            # Ссылка на карточку
            link = row.locator("a").first
            href = ""
            try:
                href = link.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = REGISTRY_BASE + href
            except Exception:
                pass

            mark = {
                "designation": cell_texts[0] if cell_texts else text[:100],
                "registration_number": cell_texts[1] if len(cell_texts) > 1 else "",
                "application_number": cell_texts[2] if len(cell_texts) > 2 else "",
                "owner": cell_texts[3] if len(cell_texts) > 3 else "",
                "nice_classes": _parse_classes(cell_texts[4] if len(cell_texts) > 4 else ""),
                "status_mark": _normalize_status(cell_texts[5] if len(cell_texts) > 5 else ""),
                "registration_date": cell_texts[6] if len(cell_texts) > 6 else "",
                "application_date": "",
                "publication_date": "",
                "owner_address": "",
                "goods_services": "",
                "source_url": href,
                "source_code": "kz_registry",
                "object_type": object_type,
            }

            # Попытка получить детали карточки
            if href:
                mark.update(_fetch_card_details(href))

            results.append(mark)
        except Exception as e:
            logger.debug(f"Пропуск строки: {e}")

    return results


def _fetch_card_details(url: str) -> dict:
    """Загружает карточку знака и извлекает все поля."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = _get_browser(pw)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)

            detail = {}
            fields_map = {
                "owner_address": ["адрес", "address", "местонахождение"],
                "goods_services": ["товар", "услуг", "goods", "перечень"],
                "application_date": ["дата подачи", "дата заявки"],
                "registration_date": ["дата регистрации"],
                "publication_date": ["дата публикации"],
                "application_number": ["номер заявки", "заявк"],
                "registration_number": ["номер регистрации", "рег. номер"],
                "designation": ["обозначение", "наименование"],
                "owner": ["правообладатель", "заявитель"],
            }

            # Ищем значения полей в карточке
            labels = page.locator(".field-label, th, .label, dt").all()
            for label in labels:
                try:
                    label_text = label.inner_text().lower().strip()
                    for field, keywords in fields_map.items():
                        if any(kw in label_text for kw in keywords):
                            sibling = label.locator("xpath=following-sibling::*[1]")
                            if sibling.count() > 0:
                                detail[field] = sibling.first.inner_text().strip()
                            break
                except Exception:
                    pass

            # Изображение знака
            img = page.locator("img.trademark-image, .mark-image img, img[alt*='знак']").first
            try:
                detail["image_url"] = img.get_attribute("src") or ""
            except Exception:
                detail["image_url"] = ""

            browser.close()
            return detail
    except Exception as e:
        logger.debug(f"Не удалось получить детали карточки {url}: {e}")
        return {}


# ──────────────────────────────────────────────────────────
# БЮЛЛЕТЕНЬ — парсинг по дате и ключевым словам
# ──────────────────────────────────────────────────────────

def scrape_bulletin(
    year: int = None,
    issue_num: str = None,
    keywords: list[str] = None,
    date_str: str = None,
) -> list[dict]:
    """
    Парсит электронный бюллетень Kazpatent.
    Возвращает список публикаций, соответствующих критериям.
    """
    from playwright.sync_api import sync_playwright

    year = year or datetime.now().year
    results = []

    with sync_playwright() as pw:
        browser = _get_browser(pw)
        page = browser.new_page()

        try:
            url = f"{BULLETIN_BASE}/#/home?targetYear={year}"
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # Получаем список выпусков за год
            issues = _get_bulletin_issues(page, year)
            logger.info(f"Найдено выпусков бюллетеня за {year}: {len(issues)}")

            for issue in issues:
                if issue_num and issue.get("number") != str(issue_num):
                    continue
                if date_str and date_str not in issue.get("date", ""):
                    continue

                # Открываем выпуск
                issue_records = _parse_bulletin_issue(page, issue, keywords)
                results.extend(issue_records)

        except Exception as e:
            logger.error(f"Ошибка парсинга бюллетеня: {e}")
            raise RuntimeError(f"Ошибка при работе с бюллетенем Kazpatent: {e}")
        finally:
            browser.close()

    return results


def _get_bulletin_issues(page, year: int) -> list[dict]:
    issues = []
    try:
        issue_links = page.locator(".issue-item, .bulletin-issue, a[href*='issue'], .issue-link").all()

        if not issue_links:
            issue_links = page.locator("a").all()

        for link in issue_links:
            try:
                text = link.inner_text().strip()
                href = link.get_attribute("href") or ""
                if text and (str(year) in text or "выпуск" in text.lower() or "бюллетень" in text.lower()):
                    issues.append({"text": text, "href": href, "date": text, "number": text})
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Ошибка получения списка выпусков: {e}")
    return issues


def _parse_bulletin_issue(page, issue: dict, keywords: list[str] = None) -> list[dict]:
    results = []
    try:
        href = issue.get("href", "")
        if href and not href.startswith("http"):
            href = BULLETIN_BASE + "/" + href.lstrip("/")

        if href:
            page.goto(href, wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(2000)

        content = page.inner_text("body")

        if keywords:
            if not any(kw.lower() in content.lower() for kw in keywords):
                return []

        # Ищем записи о товарных знаках в бюллетене
        records = page.locator(".trademark-record, .publication-item, .record-item, table tbody tr").all()

        for record in records:
            try:
                text = record.inner_text().strip()
                if not text:
                    continue

                if keywords and not any(kw.lower() in text.lower() for kw in keywords):
                    continue

                link_el = record.locator("a").first
                src_url = ""
                try:
                    src_url = link_el.get_attribute("href") or ""
                except Exception:
                    pass

                results.append({
                    "designation": text[:200],
                    "source_code": "kz_bulletin",
                    "object_type": "trademark",
                    "publication_date": issue.get("date", ""),
                    "source_url": src_url or href,
                    "owner": "",
                    "registration_number": "",
                    "application_number": "",
                    "status_mark": "published",
                    "nice_classes": [],
                    "application_date": "",
                    "registration_date": "",
                    "goods_services": "",
                    "raw_text": text[:500],
                })
            except Exception:
                pass

        # Если records пусто — сохраняем весь выпуск как одну запись
        if not records and keywords:
            results.append({
                "designation": f"Бюллетень {issue.get('text', '')}",
                "source_code": "kz_bulletin",
                "object_type": "bulletin",
                "publication_date": issue.get("date", ""),
                "source_url": href,
                "owner": "",
                "registration_number": "",
                "application_number": "",
                "status_mark": "published",
                "nice_classes": [],
                "application_date": "",
                "registration_date": "",
                "goods_services": content[:1000] if keywords and any(kw.lower() in content.lower() for kw in keywords) else "",
                "raw_text": content[:500],
            })

    except Exception as e:
        logger.debug(f"Ошибка парсинга выпуска: {e}")
    return results


# ──────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────

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
