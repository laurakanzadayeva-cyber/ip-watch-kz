"""
Проверка актуальности законодательных документов на Adilet (adilet.zan.kz).
Публичный доступ — авторизация не требуется.
"""
import re
from datetime import datetime


# Реестр ключевых документов: ключ → метаданные
CORE_DOC_REGISTRY = {
    "Закон_о_ТЗ": {
        "title": "Закон РК «О товарных знаках, знаках обслуживания, НМПТ и НГПУ» (1999)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/Z990000456_",
        "prg_doc_id": 1014203,
        "category": "Законы ИС",
        "priority": "high",
    },
    "Закон_об_авторском_праве": {
        "title": "Закон РК «Об авторском праве и смежных правах» (1996)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/Z960000006_",
        "prg_doc_id": 1005798,
        "category": "Законы ИС",
        "priority": "high",
    },
    "Патентный_закон": {
        "title": "Патентный закон РК (1999)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/Z990000427_",
        "prg_doc_id": 1013991,
        "category": "Законы ИС",
        "priority": "high",
    },
    "Закон_о_НИИС": {
        "title": "Закон РК «О Национальном институте ИС» (2021)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/Z2100000042",
        "prg_doc_id": None,
        "category": "Законы ИС",
        "priority": "medium",
    },
    "ГК_РК_общая": {
        "title": "ГК РК — Общая часть (1994)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/K940001000_",
        "prg_doc_id": 1006061,
        "category": "Кодексы",
        "priority": "high",
    },
    "ГК_РК_особенная": {
        "title": "ГК РК — Особенная часть (1999)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/K950001000_",
        "prg_doc_id": 1013880,
        "category": "Кодексы",
        "priority": "high",
    },
    "УК_РК": {
        "title": "Уголовный кодекс РК (2014)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/K1400000226",
        "prg_doc_id": 31575252,
        "category": "Кодексы",
        "priority": "medium",
    },
    "КоАП_РК": {
        "title": "Кодекс РК об административных правонарушениях (2014)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/K1400000235",
        "prg_doc_id": 31577399,
        "category": "Кодексы",
        "priority": "medium",
    },
    "ГПК_РК": {
        "title": "Гражданский процессуальный кодекс РК (2015)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/K1500000377",
        "prg_doc_id": None,
        "category": "Кодексы",
        "priority": "medium",
    },
    "Парижская_конвенция": {
        "title": "Парижская конвенция по охране промышленной собственности",
        "adilet_url": "https://adilet.zan.kz/rus/docs/Z990000422_",
        "prg_doc_id": 1007749,
        "category": "Международные договоры",
        "priority": "medium",
    },
    "Бернская_конвенция": {
        "title": "Бернская конвенция об охране лит. и худ. произведений (1971)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/Z020000304_",
        "prg_doc_id": 1007512,
        "category": "Международные договоры",
        "priority": "medium",
    },
    "Мадридское_соглашение": {
        "title": "Мадридское соглашение о международной регистрации знаков",
        "adilet_url": "https://adilet.zan.kz/rus/docs/Z010000217_",
        "prg_doc_id": 30727361,
        "category": "Международные договоры",
        "priority": "high",
    },
    "Протокол_Мадрид": {
        "title": "Протокол к Мадридскому соглашению",
        "adilet_url": "https://adilet.zan.kz/rus/docs/Z030000370_",
        "prg_doc_id": None,
        "category": "Международные договоры",
        "priority": "high",
    },
    "ТРИПС": {
        "title": "Соглашение ТРИПС (1994)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/Z060000207_",
        "prg_doc_id": None,
        "category": "Международные договоры",
        "priority": "medium",
    },
    "НП_ВС_2007_авторское": {
        "title": "НП ВС РК № 11 — защита авторского права (2007)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/P070000011_",
        "prg_doc_id": 39311152,
        "category": "Судебная практика",
        "priority": "high",
    },
    "Правила_регистрации_ТЗ": {
        "title": "Правила регистрации товарных знаков (Приказ МЮ)",
        "adilet_url": "https://adilet.zan.kz/rus/docs/V1900019451",
        "prg_doc_id": 36163631,
        "category": "Подзаконные акты",
        "priority": "high",
    },
}


def _parse_kz_date(text: str) -> datetime | None:
    """Парсит дату в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД из строки."""
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m2:
        try:
            return datetime(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        except ValueError:
            pass
    return None


def check_adilet_doc(url: str) -> dict:
    """
    Проверяет актуальность документа по URL на Adilet.
    Возвращает: {status, last_modified, notes, error}

    Статусы:
      current       — изменений не обнаружено
      amended       — изменён (> 2 лет назад)
      amended_new   — изменён недавно (< 2 лет)
      revoked       — утратил силу
      error         — ошибка проверки
    """
    import requests
    from bs4 import BeautifulSoup

    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
        )
        if not resp.ok:
            return {"status": "error", "error": f"HTTP {resp.status_code}"}

        soup = BeautifulSoup(resp.text, "html.parser")
        page_text = soup.get_text(separator=" ")

        # Утратил силу
        if re.search(r"утрат[а-яА-Я]+\s+сил[уа]", page_text, re.IGNORECASE):
            return {"status": "revoked", "last_modified": None,
                    "notes": "Документ утратил силу"}

        # Ищем метаинформацию об изменениях
        found_date = None
        found_text = ""

        # Паттерн: «Изменен 15.03.2024» или «Изменен: 15.03.2024»
        patterns = [
            r"[Иизменен]{6,8}[^а-яА-Я0-9]*(\d{2}\.\d{2}\.\d{4})",
            r"с\s+изменениями\s+(?:от\s+)?(\d{2}\.\d{2}\.\d{4})",
            r"редакция\s+(?:от\s+)?(\d{2}\.\d{2}\.\d{4})",
            r"в\s+редакции.*?(\d{2}\.\d{2}\.\d{4})",
        ]
        for pat in patterns:
            m = re.search(pat, page_text, re.IGNORECASE | re.DOTALL)
            if m:
                found_text = m.group(0).strip()[:80]
                found_date = _parse_kz_date(m.group(1))
                break

        # Попробуем найти через структуру HTML — блоки с датами
        if not found_date:
            for tag in soup.find_all(["span", "div", "p", "td"], string=re.compile(r"Измен", re.IGNORECASE)):
                sibling_text = tag.get_text(separator=" ")
                d = _parse_kz_date(sibling_text)
                if d:
                    found_date = d
                    found_text = sibling_text.strip()[:80]
                    break

        if found_date:
            days_old = (datetime.now() - found_date).days
            status = "amended_new" if days_old < 730 else "amended"
            date_str = found_date.strftime("%d.%m.%Y")
            return {
                "status": status,
                "last_modified": date_str,
                "notes": found_text or f"Изменён {date_str}",
            }

        return {"status": "current", "last_modified": None, "notes": "Изменений не обнаружено"}

    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}


def check_doc(key: str) -> dict:
    """Проверяет один документ по ключу из CORE_DOC_REGISTRY."""
    if key not in CORE_DOC_REGISTRY:
        return {"status": "error", "error": "Документ не найден в реестре"}
    info = CORE_DOC_REGISTRY[key]
    result = check_adilet_doc(info["adilet_url"])
    result["checked_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    result["key"] = key
    result.update(info)
    return result


def check_all_docs(keys: list[str] | None = None) -> list[dict]:
    """Проверяет несколько документов. Возвращает список результатов."""
    targets = keys or list(CORE_DOC_REGISTRY.keys())
    return [check_doc(k) for k in targets]
