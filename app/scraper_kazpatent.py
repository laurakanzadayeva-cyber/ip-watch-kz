"""
Парсер реестра gosreestr.kazpatent.kz.
Использует прямые HTTP-запросы к API (перехваченному из DevExpress).
Endpoint: POST /Trademark/TrademarksPartial
"""

import requests
import logging
import time
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

BASE_URL = "https://gosreestr.kazpatent.kz"
SEARCH_ENDPOINTS = {
    "trademark":     "/Trademark/TrademarksPartial",
    "well_known":    "/TIM/TIMsPartial",
    "international": "/InternationalTrademark/TrademarksPartial",
}
DETAIL_ROUTES = {
    "trademark":     "/Trademark/Details",
    "well_known":    "/TIM/Details",
    "international": "/InternationalTrademark/Details",
}
REESTR_TYPES = {
    "trademark":     "Trademark",
    "well_known":    "WellKnownTrademark",
    "international": "InternationalTrademark",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE_URL + "/",
}

# Структура фильтра — полный список полей формы
FILTER_FIELDS = [
    ("Number",                    "Contain"),
    ("ApplicationNumber",         "Contain"),
    ("ApplicationRegistrationDate","Between"),
    ("OwnerDo",                   "Contain"),
    ("Name",                      "Contain"),
    ("Icgs",                      "Contain"),
    ("BulletinNumber",            "Contain"),
    ("BulletinDate",              "Between"),
]


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": HEADERS["User-Agent"], "Accept-Language": HEADERS["Accept-Language"]})
    # Получаем стартовые cookies
    try:
        s.get(BASE_URL, timeout=15)
    except Exception as e:
        logger.warning(f"Не удалось получить стартовые cookies: {e}")
    return s


def _build_post_data(
    object_type: str,
    name: str = "",
    reg_number: str = "",
    owner: str = "",
    icgs: str = "",
    bulletin_number: str = "",
    page: int = 0,
    page_size: int = 20,
) -> dict:
    """Формирует POST-тело запроса к API реестра."""
    reestr_type = REESTR_TYPES.get(object_type, "Trademark")

    # Key="" + filter по Name работает лучше чем Key=name (из тестов API)
    data = {
        "searchObj[SearchModelObj][ReestrType]": reestr_type,
        "searchObj[SearchModelObj][Key]": "",
        "filterObj[valid]": "true",
        "view": "1",
    }

    # Заполняем структуру фильтров
    values = {
        "Number": reg_number,
        "ApplicationNumber": "",
        "ApplicationRegistrationDate": "",
        "OwnerDo": owner,
        "Name": name,
        "Icgs": icgs,
        "BulletinNumber": bulletin_number,
        "BulletinDate": "",
    }

    for i, (prop, operator) in enumerate(FILTER_FIELDS):
        data[f"filterObj[sFindParam][{i}][sProperty]"] = prop
        data[f"filterObj[sFindParam][{i}][sOperator]"] = operator
        data[f"filterObj[sFindParam][{i}][sValue]"] = values.get(prop, "")
        data[f"filterObj[sFindParam][{i}][sValue2]"] = ""

    # Пагинация DevExpress CardView
    if page > 0:
        data["cvReestr$DXPage"] = str(page)
        data["__DXCallbackParam"] = f"Pager|{page}"

    return data


def search_by_number(reg_number: str, object_type: str = "trademark") -> dict | None:
    """Быстрый поиск одного знака по регистрационному номеру."""
    results = search_trademarks(
        query="",
        reg_number=reg_number.strip(),
        object_type=object_type,
        max_pages=1,
    )
    return results[0] if results else None


def search_trademarks(
    query: str,
    object_type: str = "trademark",
    owner: str = "",
    icgs: str = "",
    reg_number: str = "",
    max_pages: int = 10,
    progress_callback=None,
) -> list[dict]:
    """
    Поиск товарных знаков в реестре Kazpatent.
    query: поисковый запрос по названию/обозначению
    reg_number: поиск по регистрационному номеру (если задан — приоритет над query)
    object_type: 'trademark' | 'well_known' | 'international'
    """
    endpoint = SEARCH_ENDPOINTS.get(object_type, SEARCH_ENDPOINTS["trademark"])
    url = BASE_URL + endpoint

    session = _make_session()
    all_results = []
    page = 0

    while page < max_pages:
        if progress_callback:
            progress_callback(page + 1, len(all_results))

        data = _build_post_data(
            object_type=object_type,
            name=query,
            reg_number=reg_number,
            owner=owner,
            icgs=icgs,
            page=page,
        )

        try:
            resp = session.post(url, data=data, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Ошибка запроса к реестру (страница {page}): {e}")
            break

        records, has_next = _parse_cardview_response(resp.text, object_type)

        if not records:
            logger.info(f"Страница {page}: записей нет, завершаем")
            break

        logger.info(f"Страница {page}: получено {len(records)} записей")
        all_results.extend(records)

        if not has_next:
            break

        page += 1
        time.sleep(0.5)  # уважаем сервер

    return all_results


def _parse_cardview_response(html: str, object_type: str) -> tuple[list[dict], bool]:
    """
    Парсит HTML-ответ DevExpress CardView.
    Каждая карточка — div.dxcvFlowCard_Material, содержит:
      - table.dxflGroup_Material → поля (label/value)
      - div.pull-right.top-left → ссылка на Details
    Возвращает (список записей, есть_ли_следующая_страница).
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Основной контейнер карточек
    cards = soup.select("div.dxcvFlowCard_Material, div[id*='DXDataCard']")

    for card in cards:
        record = _extract_card_data(card, object_type)
        if record:
            results.append(record)

    # Проверяем наличие следующей страницы через пейджер
    pager = soup.select_one(".dxcvPager, .dxpPager, [class*='dxpPager']")
    has_next = False
    if pager:
        pager_text = pager.get_text(" ", strip=True)
        # Ищем "Страница X из Y" и если X < Y — есть следующая
        m = re.search(r'страница\s+(\d+)\s+из\s+(\d+)', pager_text, re.IGNORECASE)
        if m and int(m.group(1)) < int(m.group(2)):
            has_next = True
        else:
            next_btn = pager.select_one(".dxpNext:not(.dxpDisabled), .dxpNextImage")
            has_next = next_btn is not None

    return results, has_next


# Маппинг русских лейблов полей CardView → ключи словаря записи
_LABEL_MAP = {
    "№ регистрации":         "registration_number",
    "номер регистрации":     "registration_number",
    "номер заявки":          "application_number",
    "дата регистрации":      "registration_date",
    "дата подачи":           "application_date",
    "дата заявки":           "application_date",
    "дата публикации":       "publication_date",
    "дата бюллетеня":        "publication_date",
    "номер бюллетеня":       "bulletin_number",
    "владелец":              "owner",
    "правообладатель":       "owner",
    "заявитель":             "owner",
    "мкту":                  "nice_classes_raw",
    "классы мкту":           "nice_classes_raw",
    "название":              "designation",
    "наименование":          "designation",
    "обозначение":           "designation",
    "статус":                "status_mark",
    "товары и услуги":       "goods_services",
    "срок действия":         "expiry_date",
}


def _extract_card_data(card, object_type: str) -> dict | None:
    """
    Извлекает поля из карточки DevExpress CardView.
    card = div.dxcvFlowCard_Material
    """
    data = {
        "source_code": "kz_registry",
        "object_type": object_type,
        "designation": "",
        "registration_number": "",
        "application_number": "",
        "registration_date": "",
        "application_date": "",
        "publication_date": "",
        "expiry_date": "",
        "bulletin_number": "",
        "owner": "",
        "owner_address": "",
        "nice_classes": [],
        "status_mark": "active",
        "goods_services": "",
        "source_url": "",
        "image_url": "",
    }

    # Поля из sub-таблиц dxflItem_Material — каждая таблица = одно поле [label, value]
    for ft in card.select("table.dxflItem_Material"):
        rows = ft.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower().rstrip(":")
                value = cells[1].get_text(" ", strip=True)
                if not value:
                    continue
                for key, field in _LABEL_MAP.items():
                    if key in label:
                        if field == "nice_classes_raw":
                            data["nice_classes"] = _parse_classes(value)
                        elif field == "status_mark":
                            data["status_mark"] = _normalize_status(value)
                        else:
                            data[field] = value
                        break

    # Ссылка на карточку — в div.pull-right внутри той же карточки
    detail_route = DETAIL_ROUTES.get(object_type, "/Trademark/Details")
    link = card.select_one(f"a[href*='{detail_route}'], a[href*='docNumber']")
    if link:
        href = link.get("href", "")
        if href and not href.startswith("http"):
            href = BASE_URL + href
        data["source_url"] = href
        doc_num = re.search(r'docNumber=(\d+)', href)
        if doc_num:
            data["doc_number"] = doc_num.group(1)

    # Изображение знака (не иконки навигации)
    img = card.select_one("img[src*='DXCache']")
    if img:
        src = img.get("src", "")
        if src and not src.startswith("http"):
            src = BASE_URL + src
        data["image_url"] = src

    # Если designation пустое — не сохраняем запись
    if not any([data["registration_number"], data["source_url"], data["owner"]]):
        return None

    return data


def get_mark_details(doc_number: str, object_type: str = "trademark") -> dict:
    """Загружает детальную карточку знака по номеру."""
    detail_route = DETAIL_ROUTES.get(object_type, "/Trademark/Details")
    url = f"{BASE_URL}{detail_route}?docNumber={doc_number}"

    session = _make_session()
    try:
        resp = session.get(url, headers={"User-Agent": HEADERS["User-Agent"], "Accept-Language": HEADERS["Accept-Language"]}, timeout=20)
        resp.raise_for_status()
        return _parse_details_page(resp.text, url)
    except Exception as e:
        logger.error(f"Ошибка загрузки карточки {url}: {e}")
        return {}


def _parse_details_page(html: str, source_url: str) -> dict:
    """Парсит страницу детальной карточки знака."""
    soup = BeautifulSoup(html, "html.parser")
    data = {"source_url": source_url}

    label_map = {
        "наименование": "designation",
        "обозначение": "designation",
        "номер регистрации": "registration_number",
        "номер заявки": "application_number",
        "дата регистрации": "registration_date",
        "дата подачи": "application_date",
        "дата бюллетеня": "publication_date",
        "владелец": "owner",
        "правообладатель": "owner",
        "адрес": "owner_address",
        "мкту": "nice_classes_raw",
        "перечень": "goods_services",
        "товары": "goods_services",
        "статус": "status_mark",
    }

    for row in soup.select("tr, .field-row"):
        cells = row.find_all(["td", "th", "dt", "dd"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(" ", strip=True)
            for key, field in label_map.items():
                if key in label:
                    if field == "nice_classes_raw":
                        data["nice_classes"] = _parse_classes(value)
                    elif field == "status_mark":
                        data["status_mark"] = _normalize_status(value)
                    else:
                        data[field] = value
                    break

    # Изображение знака
    img = soup.select_one(".trademark-image img, .mark-image img, img.logo, img[alt*='знак']")
    if img:
        src = img.get("src", "")
        if src and not src.startswith("http"):
            src = BASE_URL + src
        data["image_url"] = src

    return data


def _normalize_status(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["действ", "active", "зарегистр"]):
        return "active"
    if any(w in t for w in ["заявк", "applic", "pending"]):
        return "application"
    if any(w in t for w in ["прекращ", "expired", "annull", "истёк"]):
        return "expired"
    if any(w in t for w in ["отказ", "refused", "reject"]):
        return "refused"
    return "unknown"


def _parse_classes(text: str) -> list[int]:
    nums = re.findall(r'\b(\d{1,2})\b', text)
    return sorted(set(int(n) for n in nums if 1 <= int(n) <= 45))
