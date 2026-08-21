"""
Мониторинг реестра авторских прав — copyright.kazpatent.kz
(Государственный реестр прав на объекты, охраняемые авторским правом).

Сайт построен на IBM XPages: поиск и пагинация работают через внутренний
JS-фреймворк, который надёжно воспроизвести из скрипта нельзя. Зато главная
страница отдаёт список последних свидетельств в читаемой таблице, а новые
свидетельства всегда идут сверху (номер по убыванию). Для мониторинга этого
достаточно: регулярно забираем свежие записи и отбираем совпадения по автору
или названию произведения.
"""

import logging
import re
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://copyright.kazpatent.kz"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}
TIMEOUT = 25

# Порядок колонок в таблице реестра
# Св-во № | Дата публикации | Рег. номер заявки | Дата подачи |
# Дата создания | Тип объекта | Название RU | Авторы | Статус
_COLS = ["cert_number", "publication_date", "application_number",
         "application_date", "creation_date", "object_type",
         "title", "authors", "status"]


def _fetch_html() -> str:
    r = requests.get(BASE_URL + "/", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def parse_records(html: str) -> list[dict]:
    """Разбирает таблицу реестра авторских прав в список словарей."""
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.select_one("table.itsGridDataTable")
    if not tbl:
        return []
    records = []
    for tr in tbl.select("tr.itsFeedHover"):
        cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True))
                 for td in tr.find_all("td")]
        cells = [c for c in cells if c]  # убираем пустые служебные ячейки
        if len(cells) < len(_COLS):
            continue
        rec = dict(zip(_COLS, cells[:len(_COLS)]))
        rec["source"] = "copyright_kz"
        rec["source_url"] = BASE_URL + "/"
        records.append(rec)
    return records


def fetch_recent(limit: int = 50) -> list[dict]:
    """Последние опубликованные свидетельства авторского права."""
    try:
        recs = parse_records(_fetch_html())
    except Exception as e:
        logger.error(f"Ошибка загрузки реестра авторских прав: {e}")
        raise RuntimeError(f"Не удалось получить данные copyright.kazpatent.kz: {e}")
    return recs[:limit]


def search(query: str, by: str = "any") -> list[dict]:
    """
    Поиск среди последних свидетельств.
    by: 'author' — по автору/правообладателю,
        'title'  — по названию произведения,
        'any'    — по обоим полям.
    Примечание: покрывает свежие публикации (для мониторинга этого достаточно);
    полный поиск по всей истории реестра сайт скриптам не отдаёт.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    out = []
    for rec in fetch_recent(limit=200):
        author = (rec.get("authors") or "").lower()
        title = (rec.get("title") or "").lower()
        if by == "author" and q in author:
            out.append(rec)
        elif by == "title" and q in title:
            out.append(rec)
        elif by == "any" and (q in author or q in title):
            out.append(rec)
    return out
