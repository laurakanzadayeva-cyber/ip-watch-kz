"""
Парсер электронного бюллетеня Kazpatent (ebulletin.kazpatent.kz).
JSON API на порту 6002.

Три типа разделов:
  - Зарегистрированные знаки: /published/select_tzizo/{bull_num}/{date}
  - Заявки на ТЗ:             /published/select_eksp_tzizo/{date}
  - Договоры/извещения:       /published/select_izv_1/{bull_num}/{date}
                               /published/select_izv_2/{bull_num}/{date}
"""

import re
import json
import logging
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

API_BASE = "https://ebulletin.kazpatent.kz:6002"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Referer": "https://ebulletin.kazpatent.kz/",
}

# Эндпоинты для зарегистрированных знаков и извещений: /published/{ep}/{bull_num}/{date}
REGISTERED_ENDPOINTS = {
    "select_tzizo":              "Зарегистрированные ТЗ",
    "select_izv_1":              "Договоры (лицензии, уступки ч.1)",
    "select_izv_2":              "Договоры (лицензии, уступки ч.2)",
    "select_izv_prodl_tz":       "Продление ТЗ",
    "select_izv_prodl_tz_mktu":  "Продление ТЗ (изм. МКТУ)",
    "select_izv_dub_tz":         "Дубликат св-ва ТЗ",
    "select_izv_tz_izm_name":    "Изм. наименования правообл.",
    "select_izv_tz_izm_address": "Изм. адреса правообл.",
    "select_izv_tz_izm_mktu":    "Изм. МКТУ",
    "select_izv_cancellation":   "Аннулирование ТЗ",
    "select_izv_tk":             "Прекращение ТЗ",
    "select_izv_prek_tz":        "Прекращение охраны ТЗ",
    "select_nmpt":               "НМПТ",
    "select_gu":                 "Географические указания",
}

# Эндпоинты для заявок: /published/{ep}/{date}  (без bull_num!)
APPLICATION_ENDPOINTS = {
    "select_eksp_tzizo": "Заявки на ТЗ",
    "select_eksp_nmpt":  "Заявки на НМПТ",
    "select_eksp_gu":    "Заявки на ГУ",
}

# Эндпоинты-объявления (select_izv_1, select_izv_2): главное поле — izv_ru
ANNOUNCEMENT_ENDPOINTS = {"select_izv_1", "select_izv_2"}

# Поля для заявок (экспертиза)
APP_FIELD_MAP = {
    "req_number_21":      "application_number",
    "req_date_22":        "application_date",
    "publication_date":   "publication_date",
    "field_731_ru":       "owner",
    "field_731_kz":       "owner_kz",
    "field_510_511":      "goods_services",
    "field_510_511_short":"nice_classes_short",
    "field_591":          "colors",
    "declarant_address":  "owner_address",
}

# Поля для зарегистрированных знаков
REG_FIELD_MAP = {
    "gos_number_11":      "registration_number",
    "gos_date_11":        "registration_date",
    "req_number_21":      "application_number",
    "req_date_22":        "application_date",
    "field_181":          "expiry_date",
    "field_730_ru":       "owner",
    "field_510_511":      "goods_services",
    "field_510_511_short":"nice_classes_short",
    "field_591":          "colors",
    "pat_dby":            "publication_date",
    "pat_nby":            "bulletin_number",
}

# Поля для договоров/извещений (select_izv_1, select_izv_2)
ANNOUNCEMENT_FIELD_MAP = {
    "gos_number_11": "registration_number",  # номер договора
    "izv_ru":        "announcement_text",    # полный текст объявления на русском
}


def get_issue_dates(year: int) -> dict:
    """Возвращает {номер_выпуска: дата} за год."""
    try:
        r = requests.get(
            f"{API_BASE}/bulletin/select_bull_list_published?year={year}",
            headers=HEADERS, timeout=15, verify=False,
        )
        r.raise_for_status()
        return r.json()  # {"1": "2025-01-05", "40": "2025-10-03", ...}
    except Exception as e:
        logger.error(f"Ошибка получения выпусков {year}: {e}")
        return {}


_LAT_TO_CYR = str.maketrans({
    'A': 'А', 'B': 'Б', 'C': 'С', 'D': 'Д', 'E': 'Е', 'F': 'Ф', 'G': 'Г',
    'H': 'Х', 'I': 'И', 'J': 'Й', 'K': 'К', 'L': 'Л', 'M': 'М', 'N': 'Н',
    'O': 'О', 'P': 'П', 'R': 'Р', 'S': 'С', 'T': 'Т', 'U': 'У', 'V': 'В',
    'W': 'В', 'X': 'КС', 'Y': 'Й', 'Z': 'З',
})


def _expand_keywords(keywords: list[str]) -> list[str]:
    """Добавляет кириллические варианты для латинских слов (SERGEK → СЕРГЕК)."""
    expanded = list(keywords)
    for kw in keywords:
        if kw.isascii():
            cyr = kw.upper().translate(_LAT_TO_CYR)
            if cyr not in expanded:
                expanded.append(cyr)
    return expanded


def search_bulletin(
    year: int,
    keywords: list[str],
    issue_num: str = None,
    max_issues: int = 60,
    progress_callback=None,
) -> list[dict]:
    """
    Ищет по ключевым словам во ВСЕХ разделах бюллетеня:
      - Заявки на ТЗ
      - Зарегистрированные ТЗ
      - Договоры (лицензии, уступки прав)
      - Продления, аннулирования, изменения
    Для латинских слов автоматически добавляет кириллическую транслитерацию.
    """
    dates_map = get_issue_dates(year)
    if not dates_map:
        return []

    if issue_num:
        dates_map = {k: v for k, v in dates_map.items() if k == str(issue_num)} or dates_map

    kw_upper = [k.upper() for k in _expand_keywords(keywords)]
    results = []
    checked = 0

    for num, date in dates_map.items():
        if checked >= max_issues:
            break
        if progress_callback:
            progress_callback(checked, len(dates_map), date)

        # Заявки — только дата (без bull_num)
        for ep, label in APPLICATION_ENDPOINTS.items():
            recs = _fetch_and_search(
                f"{API_BASE}/bulletin/published/{ep}/{date}",
                kw_upper, date, num, label, ep,
            )
            results.extend(recs)

        # Зарегистрированные, договоры, извещения — bull_num + дата
        for ep, label in REGISTERED_ENDPOINTS.items():
            recs = _fetch_and_search(
                f"{API_BASE}/bulletin/published/{ep}/{num}/{date}",
                kw_upper, date, num, label, ep,
            )
            results.extend(recs)

        checked += 1

    return _deduplicate(results)


def _fetch_and_search(url, kw_upper, date, bull_num, section_label, endpoint_name):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []

        # Поиск ведём в декодированном тексте (не \u-escape)
        full_text = json.dumps(data, ensure_ascii=False).upper()
        if not any(kw in full_text for kw in kw_upper):
            return []

        is_announcement = endpoint_name in ANNOUNCEMENT_ENDPOINTS
        is_application = endpoint_name in APPLICATION_ENDPOINTS

        results = []
        for rec in data:
            rec_str = json.dumps(rec, ensure_ascii=False).upper()
            if any(kw in rec_str for kw in kw_upper):
                result = _build_result(rec, date, bull_num, section_label,
                                       is_application, is_announcement)
                if result:
                    results.append(result)
        if results:
            logger.info(f"[{section_label}] {date}: найдено {len(results)}")
        return results
    except Exception as e:
        logger.debug(f"Ошибка {url}: {e}")
        return []


def _build_result(rec: dict, date: str, bull_num: str, section: str,
                  is_application: bool, is_announcement: bool) -> dict | None:
    if is_announcement:
        field_map = ANNOUNCEMENT_FIELD_MAP
    elif is_application:
        field_map = APP_FIELD_MAP
    else:
        field_map = REG_FIELD_MAP

    obj_type = "application" if is_application else "announcement" if is_announcement else "trademark"

    r = {
        "source_code":       "kz_bulletin",
        "object_type":       obj_type,
        "section":           section,
        "designation":       "",
        "registration_number": "",
        "application_number":  "",
        "registration_date":   "",
        "application_date":    "",
        "publication_date":    date,
        "expiry_date":         "",
        "owner":               "",
        "owner_address":       "",
        "goods_services":      "",
        "announcement_text":   "",
        "nice_classes":        [],
        "colors":              "",
        "bulletin_number":     bull_num,
        "status_mark":         obj_type,
        "source_url": (
            f"https://ebulletin.kazpatent.kz/#/bulletin"
            f"?timestamp={date}&bull_num={bull_num}&data_source=bulletin&language=ru"
        ),
    }

    for api_field, my_field in field_map.items():
        val = rec.get(api_field)
        if val:
            r[my_field] = str(val).strip()

    # Парсим классы МКТУ
    r["nice_classes"] = _parse_classes(r.get("nice_classes_short", ""))
    r.pop("nice_classes_short", None)

    # ── Designation (метка для отображения) ──────────────────────────────
    if is_announcement:
        # Извлекаем название ТЗ из текста объявления (в «»)
        txt = r.get("announcement_text", "")
        m = re.search(r'«([^»]+)»', txt)
        if m:
            r["designation"] = m.group(1)[:80]
        else:
            r["designation"] = txt[:80] if txt else f"Договор №{r['registration_number']}"
    elif is_application:
        # Заявка: номер заявки + краткое обозначение классов
        num = r.get("application_number", "")
        classes = r.get("nice_classes", [])
        cls_str = f"кл. {','.join(map(str, classes))}" if classes else ""
        r["designation"] = f"Заявка №{num} {cls_str}".strip() if num else r.get("goods_services", "")[:80]
    else:
        # Зарегистрированный знак: рег. номер — НЕ товары/услуги
        reg = r.get("registration_number", "")
        if reg:
            r["designation"] = f"ТЗ №{reg}"
        elif r.get("application_number"):
            r["designation"] = f"Заявка №{r['application_number']}"

    if not any([r["registration_number"], r["application_number"],
                r["owner"], r["announcement_text"]]):
        return None
    return r


def _parse_classes(text: str) -> list[int]:
    nums = re.findall(r'\b(\d{1,2})\b', text or "")
    return sorted(set(int(n) for n in nums if 1 <= int(n) <= 45))


def _deduplicate(items: list[dict]) -> list[dict]:
    seen, result = set(), []
    for item in items:
        key = (
            item.get("application_number", ""),
            item.get("registration_number", ""),
            item.get("section", ""),
            item.get("publication_date", ""),
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
