"""
Поиск сведений об организации по БИН через открытые источники РК.
Порядок попыток: stat.gov.kz → egov open data → КГД → возврат пустого результата.
"""

import re
import logging
import requests

logger = logging.getLogger(__name__)

TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html;q=0.9",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

_EMPTY = {"name": "", "address": "", "director": "", "status": "", "kato": "", "oked": ""}


def lookup_company_by_bin(bin_str: str) -> dict:
    """
    Возвращает словарь с полями: name, address, director, status, kato, oked.
    Пустые строки если данные недоступны.
    """
    bin_str = bin_str.strip()
    if not re.fullmatch(r"\d{12}", bin_str):
        return {**_EMPTY, "error": "БИН должен содержать ровно 12 цифр"}

    result = _try_stat_gov(bin_str)
    if result.get("name"):
        return result

    result = _try_egov_opendata(bin_str)
    if result.get("name"):
        return result

    result = _try_kgd(bin_str)
    if result.get("name"):
        return result

    return {**_EMPTY, "error": "Организация не найдена в открытых реестрах"}


# ─── Источник 1: Комитет по статистике ───────────────────────────────────────

def _try_stat_gov(bin_str: str) -> dict:
    """stat.gov.kz — публичный реестр юридических лиц."""
    try:
        url = "https://stat.gov.kz/api/juridical/counter/api/"
        params = {"bin": bin_str, "lang": "ru"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            # Ответ может быть списком или объектом
            if isinstance(data, list) and data:
                data = data[0]
            if isinstance(data, dict) and (data.get("name") or data.get("nameRu")):
                return {
                    "name":     data.get("nameRu") or data.get("name") or "",
                    "address":  data.get("address") or data.get("legalAddress") or "",
                    "director": data.get("director") or data.get("directorName") or "",
                    "status":   data.get("statusRu") or data.get("status") or "действующий",
                    "kato":     data.get("kato") or "",
                    "oked":     data.get("oked") or "",
                }
    except Exception as e:
        logger.debug(f"stat.gov.kz БИН {bin_str}: {e}")
    return dict(_EMPTY)


# ─── Источник 2: egov.kz открытые данные ─────────────────────────────────────

def _try_egov_opendata(bin_str: str) -> dict:
    """data.egov.kz — открытые данные о компаниях."""
    try:
        url = f"https://data.egov.kz/api/v4/adata_gosuslugi_zayavlenie_na_registraciyu_yul/index?source%5B%5D=bin%3A{bin_str}&size=1"
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            hits = data.get("data") or data.get("hits", {}).get("hits", [])
            if isinstance(hits, list) and hits:
                src = hits[0].get("_source") or hits[0]
                name = src.get("nameRu") or src.get("name") or src.get("org_name") or ""
                if name:
                    return {
                        "name":     name,
                        "address":  src.get("address") or src.get("legalAddress") or "",
                        "director": src.get("director") or "",
                        "status":   "действующий",
                        "kato":     src.get("kato") or "",
                        "oked":     src.get("oked") or "",
                    }
    except Exception as e:
        logger.debug(f"egov opendata БИН {bin_str}: {e}")
    return dict(_EMPTY)


# ─── Источник 3: КГД (Комитет государственных доходов) ───────────────────────

def _try_kgd(bin_str: str) -> dict:
    """salyk.kz — публичная проверка налогоплательщика."""
    try:
        url = "https://salyk.kz/TaxPayer/CheckActivityRest"
        payload = {"bin": bin_str, "lang": "ru"}
        r = requests.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json"}, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            name = data.get("nameRu") or data.get("name") or ""
            if name:
                return {
                    "name":     name,
                    "address":  data.get("address") or "",
                    "director": data.get("director") or "",
                    "status":   data.get("statusRu") or "действующий",
                    "kato":     "",
                    "oked":     "",
                }
    except Exception as e:
        logger.debug(f"КГД БИН {bin_str}: {e}")
    return dict(_EMPTY)
