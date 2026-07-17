"""
Парсер Общеизвестных товарных знаков КЗ.
Использует Playwright: навигация + парсинг DOM.
(Простой HTTP не работает — нет отдельного фильтрующего endpoint)
"""
import logging
import re
from playwright.sync_api import sync_playwright, Error as PlaywrightError
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://gosreestr.kazpatent.kz"


def scrape_well_known_trademarks(progress_callback=None) -> list[dict]:
    """
    Получает все Общеизвестные ТЗ Казахстана через браузер.
    Возвращает список dict с полями знаков.
    """
    results = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"Accept-Language": "ru-RU,ru;q=0.9"})

            if progress_callback:
                progress_callback("Открываю реестр...", 0)

            page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            # Раскрываем группу "Товарные знаки" в основном NavBar
            _click_navbar_group(page, "Товарные знаки")
            page.wait_for_timeout(1500)

            # Кликаем "Общеизвестные товарные знаки"
            clicked = _click_item_by_text(page, "Общеизвестные товарные знаки")
            if not clicked:
                logger.warning("Не удалось найти 'Общеизвестные ТЗ' в меню — пробуем JS")
                page.evaluate("() => { if(window.nbTrademarkFilters) nbTrademarkFilters.GetGroup(0).SetExpanded(true); }")
                page.wait_for_timeout(1500)

            # Нажимаем "Найти" с пустыми фильтрами (получаем все)
            _click_find_button(page, "TrademarkUniversal")
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2000)

            if progress_callback:
                progress_callback("Парсю результаты...", 10)

            # Парсим CardView результатов
            page_num = 0
            max_pages = 20

            while page_num < max_pages:
                html = page.content()
                cards = _parse_cards_from_html(html, "well_known")

                if not cards:
                    logger.info(f"Страница {page_num}: карточек нет, завершаем")
                    break

                results.extend(cards)
                logger.info(f"Страница {page_num}: получено {len(cards)} карточек")

                if progress_callback:
                    progress_callback(f"Загружено {len(results)} записей...", min(90, len(results)))

                # Следующая страница
                has_next = _go_next_page(page)
                if not has_next:
                    break
                page.wait_for_load_state("networkidle", timeout=10000)
                page.wait_for_timeout(1000)
                page_num += 1

            browser.close()

    except Exception as e:
        logger.error(f"Ошибка при скрапинге Общеизвестных ТЗ: {e}")

    return results


def _click_navbar_group(page, group_text: str):
    """Раскрывает группу NavBar по тексту заголовка."""
    page.evaluate(f"""
        () => {{
            const spans = Array.from(document.querySelectorAll('span.dxnb-ghtext, span'));
            for (const s of spans) {{
                if (s.textContent.trim() === {group_text!r}) {{
                    const td = s.closest('td') || s.closest('div') || s.parentElement;
                    if (td) td.click();
                    return;
                }}
            }}
        }}
    """)


def _click_item_by_text(page, text: str) -> bool:
    """Кликает элемент NavBar по точному тексту."""
    result = page.evaluate(f"""
        () => {{
            const all = Array.from(document.querySelectorAll('span, a, li, div'));
            const matches = all.filter(el =>
                el.textContent.trim() === {text!r} && el.offsetParent !== null
            );
            if (matches.length > 0) {{
                matches[0].click();
                return true;
            }}
            return false;
        }}
    """)
    return bool(result)


def _click_find_button(page, form_code: str):
    """Нажимает кнопку Найти для указанного раздела."""
    page.evaluate(f"""
        () => {{
            // Пробуем через DevExpress button
            const btnId = 'btnFind1_{form_code}_I';
            const btn = document.getElementById(btnId);
            if (btn) {{ btn.click(); return; }}

            // Пробуем все видимые кнопки Найти
            const btns = Array.from(document.querySelectorAll('input[value="Найти"], button'));
            const vis = btns.filter(b => b.offsetParent !== null);
            if (vis.length > 0) vis[0].click();
        }}
    """)


def _go_next_page(page) -> bool:
    """Переходит на следующую страницу CardView. Возвращает True если перешёл."""
    result = page.evaluate("""
        () => {
            const next = document.querySelector('.dxpNext:not(.dxpDisabled), [class*="dxpNextImage"]');
            if (next && next.offsetParent !== null) {
                next.click();
                return true;
            }
            return false;
        }
    """)
    return bool(result)


def _parse_cards_from_html(html: str, object_type: str) -> list[dict]:
    """Парсит карточки из HTML страницы."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    cards = soup.select("div.dxcvFlowCard_Material, div[id*='DXDataCard']")

    for card in cards:
        data = {
            "source_code": "kz_registry",
            "object_type": object_type,
            "designation": "",
            "registration_number": "",
            "application_number": "",
            "registration_date": "",
            "expiry_date": "",
            "bulletin_number": "",
            "owner": "",
            "nice_classes": [],
            "status_mark": "active",
            "source_url": "",
            "image_url": "",
        }

        _LABEL_MAP = {
            "№ регистрации": "registration_number",
            "номер заявки":  "application_number",
            "дата регистрации": "registration_date",
            "срок действия": "expiry_date",
            "номер бюллетеня": "bulletin_number",
            "владелец": "owner",
            "правообладатель": "owner",
            "название": "designation",
            "наименование": "designation",
            "мкту": "nice_classes_raw",
            "статус": "status_mark",
        }

        for ft in card.select("table.dxflItem_Material"):
            rows = ft.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True).lower()
                    value = cells[1].get_text(" ", strip=True)
                    for key, field in _LABEL_MAP.items():
                        if key in label:
                            if field == "nice_classes_raw":
                                data["nice_classes"] = _parse_classes(value)
                            elif field == "status_mark":
                                data["status_mark"] = _normalize_status(value)
                            else:
                                data[field] = value
                            break

        # Ссылка
        link = card.select_one("a[href*='Details']")
        if link:
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = BASE_URL + href
            data["source_url"] = href

        if any([data["registration_number"], data["source_url"]]):
            results.append(data)

    return results


def _normalize_status(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["действ", "active"]): return "active"
    if any(w in t for w in ["заявк", "pending"]): return "application"
    if any(w in t for w in ["прекращ", "expired", "истёк", "истек"]): return "expired"
    if any(w in t for w in ["отказ", "refused"]): return "refused"
    return "unknown"


def _parse_classes(text: str) -> list[int]:
    nums = re.findall(r'\b(\d{1,2})\b', text)
    return sorted(set(int(n) for n in nums if 1 <= int(n) <= 45))
