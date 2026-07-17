"""
Параграф (online.prg.kz/lawyer) — мониторинг изменений законодательства в сфере ИС.
Использует Playwright для входа по логину/паролю.
"""

import logging
import json
from datetime import datetime
from pathlib import Path
from config_manager import get_paragraph_creds

logger = logging.getLogger(__name__)

# Ключевые слова для поиска по всей сфере ИС
IP_KEYWORDS = [
    # Товарные знаки
    "товарный знак", "товарных знаков", "торговая марка", "знак обслуживания",
    "общеизвестный знак", "общеизвестный товарный знак",
    # Авторское право и смежные
    "авторское право", "авторских прав", "авторского права",
    "смежные права", "смежных прав", "исполнитель", "фонограмма",
    "авторский договор", "авторское вознаграждение",
    "коллективное управление правами",
    # Патенты и изобретения
    "патент", "патентный", "изобретение", "полезная модель",
    "промышленный образец", "селекционное достижение",
    # Общее ИС
    "интеллектуальная собственность", "интеллектуальной собственности",
    "промышленная собственность", "исключительное право",
    "объекты интеллектуальной собственности",
    # Географические обозначения
    "географическое указание", "наименование места происхождения",
    # Органы и реестры
    "qazpatent", "казпатент", "патентный поверенный",
    "апелляционный совет", "апелляционная комиссия",
    # Международные договоры
    "мадридское соглашение", "парижская конвенция",
    "ниццкая классификация", "МКТУ", "ВОИС", "ТРИПС",
    "бернская конвенция", "договор ВОИС",
]

# Конкретные законы РК в сфере ИС — мониторим их целиком
IP_LAWS = [
    "Закон Республики Казахстан о товарных знаках",           # № 456-I от 26.07.1999
    "Закон Республики Казахстан об авторском праве",          # № 6-I от 10.06.1996
    "Патентный закон Республики Казахстан",                   # № 427-I от 16.07.1999
    "об охране селекционных достижений",
    "о географических указаниях",
    "об интеллектуальной собственности",
]

ADILET_SEARCH_URL = "https://adilet.zan.kz/rus/search/docs"
PARAGRAPH_URL = "https://online.prg.kz/lawyer"

from paths import DATA_DIR
CACHE_FILE = DATA_DIR / "paragraph_cache.json"


def monitor_legislation_changes(use_adilet_fallback: bool = True) -> list[dict]:
    """
    Проверяет новые/изменённые нормативные акты, затрагивающие ИС.
    Сначала пробует Параграф, при ошибке — Adilet (открытый источник).
    """
    url, login, password = get_paragraph_creds()

    if login and password:
        try:
            return _scrape_paragraph(url, login, password)
        except Exception as e:
            logger.warning(f"Параграф недоступен ({e}), переключаемся на Adilet")

    if use_adilet_fallback:
        return _scrape_adilet()

    return []


def _scrape_paragraph(url: str, login: str, password: str) -> list[dict]:
    """Входит в Параграф и ищет изменения по ИС."""
    from playwright.sync_api import sync_playwright

    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({"Accept-Language": "ru-RU,ru;q=0.9"})

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Кликаем "Вход для пользователей" чтобы открыть форму логина
            for link_sel in ['a:has-text("Вход для пользователей")', 'a[href*="login"]:has-text("Вход")', 'a:has-text("Войти")']:
                el = page.locator(link_sel)
                if el.count() > 0:
                    el.first.click()
                    page.wait_for_timeout(2000)
                    break

            # Авторизация
            logged_in = False
            if page.locator("input[type='password']").count() > 0:
                for ls in ["input[name='login']", "input[name='username']", "input[name='email']", "input[type='text']:visible"]:
                    if page.locator(ls).count() > 0:
                        page.fill(ls, login)
                        break
                page.fill("input[type='password']", password)
                for bs in ["button[type='submit']", "input[type='submit']", "button:has-text('Войти')", "button:has-text('Вход')"]:
                    if page.locator(bs).count() > 0:
                        page.click(bs)
                        page.wait_for_load_state("networkidle", timeout=15000)
                        logged_in = True
                        break

            if not logged_in:
                logger.info("Форма входа не найдена — продолжаем с публичным доступом")

            if logged_in:
                logger.info("Вход в Параграф выполнен успешно")
            else:
                logger.info("Публичный доступ Параграф")

            # Поиск по всем ИС-ключевым словам
            all_search_terms = IP_KEYWORDS[:8] + IP_LAWS[:4]
            for keyword in all_search_terms:
                kw_results = _search_paragraph_keyword(page, keyword)
                results.extend(kw_results)

        except Exception as e:
            logger.error(f"Ошибка работы с Параграфом: {e}")
            raise
        finally:
            browser.close()

    return _deduplicate_docs(results)


def _search_paragraph_keyword(page, keyword: str) -> list[dict]:
    results = []
    try:
        # Поле поиска Параграф использует name=SearchInput
        search_selectors = [
            "input[name='SearchInput']",
            "input[placeholder*='поиск']",
            "input[name='q']",
            "input[type='search']",
            ".search-input input",
        ]
        searched = False
        for sel in search_selectors:
            try:
                if page.locator(sel).count() > 0:
                    page.fill(sel, keyword)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("networkidle", timeout=10000)
                    searched = True
                    break
            except Exception:
                pass

        if not searched:
            return results

        # Извлечение результатов — Параграф показывает ссылки на документы
        doc_links = page.locator(
            ".doc-title a, .result-title a, .document-item a, "
            ".search-result a, h3 a, h4 a, .doctitle a, td.docTitle a"
        ).all()
        for link in doc_links[:20]:
            try:
                title = link.inner_text().strip()
                if not title or len(title) < 5:
                    continue
                href = link.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://online.prg.kz" + href

                # Пробуем получить дату изменения из строки рядом
                doc_date = ""
                try:
                    parent = link.locator("xpath=../..")
                    parent_text = parent.inner_text()
                    import re
                    date_m = re.search(r"\d{2}\.\d{2}\.\d{4}", parent_text)
                    if date_m:
                        doc_date = date_m.group(0)
                except Exception:
                    pass

                results.append({
                    "title": title,
                    "url": href,
                    "source": "paragraph",
                    "keyword": keyword,
                    "doc_date": doc_date,
                    "found_at": datetime.now().isoformat(),
                    "is_new": True,
                    "change_summary": "",
                })
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Ошибка поиска по ключевому слову '{keyword}': {e}")
    return results


def _scrape_adilet() -> list[dict]:
    """
    Запасной вариант: бесплатная база Министерства юстиции РК.
    Поиск по ИС-тематике в adilet.zan.kz.
    """
    import requests
    from bs4 import BeautifulSoup

    results = []
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    for keyword in ["товарный знак", "интеллектуальная собственность", "авторское право"]:
        try:
            r = session.get(
                ADILET_SEARCH_URL,
                params={"phrase": keyword, "fromDate": "", "toDate": ""},
                timeout=15,
            )
            soup = BeautifulSoup(r.text, "html.parser")
            docs = soup.select(".doc-item, .result-item, .search-result, article")

            for doc in docs[:10]:
                title_el = doc.select_one("a.doc-title, a.title, h3 a, h4 a, a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://adilet.zan.kz" + href

                date_el = doc.select_one(".date, .doc-date, time")
                doc_date = date_el.get_text(strip=True) if date_el else ""

                results.append({
                    "title": title,
                    "url": href,
                    "source": "adilet",
                    "keyword": keyword,
                    "doc_date": doc_date,
                    "found_at": datetime.now().isoformat(),
                    "is_new": True,
                    "change_summary": "",
                })
        except Exception as e:
            logger.warning(f"Adilet поиск '{keyword}': {e}")

    return _deduplicate_docs(results)


def get_cached_docs() -> list[dict]:
    """Возвращает кэшированные документы."""
    if CACHE_FILE.exists():
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_docs_cache(docs: list[dict]):
    """Сохраняет документы в кэш."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {d["url"]: d for d in get_cached_docs()}
    for doc in docs:
        if doc["url"] not in existing:
            doc["is_new"] = True
            existing[doc["url"]] = doc
        else:
            existing[doc["url"]]["is_new"] = False
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(existing.values()), f, ensure_ascii=False, indent=2)


def _deduplicate_docs(docs: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for d in docs:
        key = d.get("url") or d.get("title", "")
        if key and key not in seen:
            seen.add(key)
            result.append(d)
    return result
