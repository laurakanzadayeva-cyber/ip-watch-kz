"""
Загрузчик документов из Параграф (online.prg.kz/lawyer).
Входит под учётными данными из credentials.json,
при конфликте сессий автоматически выходит с других устройств.
Скачивает законы по ИС в папку laws/Параграф/.
"""

import re
import time
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

from paths import LAWS_DIR as _LAWS_ROOT, SCREENSHOTS_DIR
LAWS_DIR = _LAWS_ROOT / "Параграф"
INDEX_FILE = _LAWS_ROOT / "_index_paragraph.json"

# Законы для скачивания: (название, doc_id, имя файла)
# doc_id=None → автоматический поиск через _find_doc_id()
TARGET_LAWS = [
    # ── Основные законы по ИС ────────────────────────────────────────────────
    ("Закон РК о товарных знаках, знаках обслуживания и НМПТ",              1014203,  "Закон_о_ТЗ"),
    ("Закон РК об авторском праве и смежных правах",                         1005798,  "Закон_об_авторском_праве"),
    ("Патентный закон Республики Казахстан",                                 1013991,  "Патентный_закон"),
    ("Закон РК об охране селекционных достижений",                           1014046,  "Закон_о_селекции"),
    ("Закон РК о правовой охране топологий интегральных микросхем",          None,     "Закон_о_топологиях_ИМС"),
    ("Закон РК о Национальном институте интеллектуальной собственности",     None,     "Закон_о_НИИС"),

    # ── Кодексы ──────────────────────────────────────────────────────────────
    ("Гражданский кодекс РК Общая часть",                                    1006061,  "ГК_РК_общая"),
    ("Гражданский кодекс РК Особенная часть",                                1013880,  "ГК_РК_особенная"),
    ("Уголовный кодекс Республики Казахстан 2014",                           31575252, "УК_РК"),
    ("Кодекс РК об административных правонарушениях",                        31577399, "КоАП_РК"),
    ("Гражданский процессуальный кодекс РК 2015",                            34329053, "ГПК_РК"),
    ("Кодекс Республики Казахстан о таможенном регулировании 2017",          None,     "Таможенный_кодекс"),

    # ── Международные договоры ───────────────────────────────────────────────
    ("Парижская конвенция по охране промышленной собственности",              1007749,  "Парижская_конвенция"),
    ("Мадридское соглашение о международной регистрации знаков",             30727361, "Мадридское_соглашение"),
    ("Протокол к Мадридскому соглашению о международной регистрации знаков", None,     "Протокол_Мадрид"),
    ("Бернская конвенция об охране литературных и художественных произведений", 1007512, "Бернская_конвенция"),
    ("Договор ВОИС по авторскому праву WCT",                                 None,     "WCT_договор"),
    ("Договор ВОИС по исполнениям и фонограммам WPPT",                       None,     "WPPT_договор"),
    ("Договор PCT патентная кооперация",                                      31485040, "Договор_PCT"),
    ("Соглашение ТРИПС о торговых аспектах прав на интеллектуальную собственность", None, "ТРИПС"),

    # ── Подзаконные акты ─────────────────────────────────────────────────────
    ("Правила регистрации товарных знаков знаков обслуживания",              36163631, "Правила_регистрации_ТЗ"),
    ("Правила проведения экспертизы заявок на объекты интеллектуальной собственности приказ 1349", None, "Правила_экспертизы_ИС"),

    # ── Судебная практика ────────────────────────────────────────────────────
    ("Нормативное постановление Верховного Суда РК 2007 авторское право смежные права", 39311152, "Судебная_практика_ИС"),
]

PARAGRAPH_URL = "https://online.prg.kz/lawyer"


def load_index() -> dict:
    if INDEX_FILE.exists():
        with open(INDEX_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_index(index: dict):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def download_all(headless: bool = True, progress_callback=None) -> dict:
    """
    Основная функция: входит в Параграф и скачивает все законы.
    headless=False — показывает браузер (для отладки).
    """
    from config_manager import get_paragraph_creds
    _, login, password = get_paragraph_creds()

    if not login or not password:
        return {"error": "Не заданы логин/пароль Параграфа в Настройках"}

    LAWS_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    summary = {"total": len(TARGET_LAWS), "downloaded": 0, "skipped": 0, "errors": 0, "details": []}
    index = load_index()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            locale="ru-RU",
            accept_downloads=True,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        try:
            # ── Шаг 1: Вход ──────────────────────────────────────────────────
            logged_in = _login(page, login, password)
            if not logged_in:
                return {"error": "Не удалось войти в Параграф"}

            print("✅ Вход в Параграф выполнен")

            # ── Шаг 2: Скачиваем каждый закон ───────────────────────────────
            for i, (title, doc_id, filename) in enumerate(TARGET_LAWS):
                if progress_callback:
                    progress_callback(i, len(TARGET_LAWS), filename)

                print(f"\n  [{i+1}/{len(TARGET_LAWS)}] {filename}...")
                result = _download_law(page, title, doc_id, filename, index)
                summary["details"].append(result)

                if result["status"] == "ok":
                    summary["downloaded"] += 1
                    index[filename] = result
                elif result["status"] == "skipped":
                    summary["skipped"] += 1
                else:
                    summary["errors"] += 1

                time.sleep(2)

        except Exception as e:
            logger.error(f"Критическая ошибка Параграфа: {e}")
            summary["error"] = str(e)
        finally:
            browser.close()

    save_index(index)
    return summary


def _login(page, login: str, password: str) -> bool:
    """Входит в Параграф, обрабатывает конфликт сессий."""
    try:
        page.goto(PARAGRAPH_URL, wait_until="commit", timeout=60000)
        page.wait_for_timeout(4000)
        _screenshot(page, "01_start")

        # Уже залогинены? (есть поле поиска #SearchInput и нет формы пароля)
        if _is_logged_in(page):
            print("  (уже авторизованы)")
            return True

        # Нужно войти — ищем форму входа
        # Прямо переходим на страницу входа если форма не видна
        if page.locator("input[type='password']").count() == 0:
            # Ищем ссылку на вход
            _click_login_link(page)
            page.wait_for_timeout(3000)

        # Если форма всё ещё не появилась — идём напрямую
        if page.locator("input[type='password']").count() == 0:
            page.goto("https://online.prg.kz/login", wait_until="commit", timeout=30000)
            page.wait_for_timeout(3000)

        _screenshot(page, "02_login_form")

        # Проверяем снова — возможно уже залогинены после навигации
        if _is_logged_in(page):
            return True

        # Заполняем поле логина
        login_selectors = [
            "input[placeholder*='огин']",
            "input[placeholder*='ogin']",
            "input[name='login']",
            "input[name='username']",
            "input[name='email']",
            "input[type='email']",
        ]
        login_filled = False
        for sel in login_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.fill(login)
                    login_filled = True
                    break
            except Exception:
                pass

        if not login_filled:
            logger.warning("Поле логина не найдено")
            _screenshot(page, "login_no_field")
            return False

        # Поле пароля
        page.locator("input[type='password']").first.fill(password)
        page.wait_for_timeout(500)

        # Кнопка Войти
        for bs in ["button:text-is('Войти')", "button[type='submit']",
                    "input[type='submit']", "button:has-text('Войти')"]:
            try:
                btn = page.locator(bs).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    break
            except Exception:
                pass

        page.wait_for_timeout(5000)
        _screenshot(page, "03_after_login")

        # Конфликт сессий
        _handle_session_conflict(page)
        page.wait_for_timeout(3000)
        _screenshot(page, "04_after_conflict")

        return _is_logged_in(page)

    except Exception as e:
        logger.error(f"Ошибка входа: {e}")
        _screenshot(page, "login_error")
        return False


def _click_login_link(page):
    """Кликает ссылку входа если форма скрыта."""
    for sel in [
        'a:has-text("Вход для пользователей")',
        'a:has-text("Войти")',
        'a:has-text("Вход")',
        'button:has-text("Войти")',
        '.login-link',
        '[href*="login"]',
    ]:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                el.click()
                page.wait_for_timeout(2000)
                return
        except Exception:
            pass


def _handle_session_conflict(page):
    """
    Если Параграф спрашивает 'войти и выйти с других устройств' — соглашаемся.
    """
    conflict_texts = [
        "другим устройствам", "другом устройстве", "другие устройства",
        "активная сессия", "уже авторизован", "выйти с других",
        "continue anyway", "войти на это устройство",
    ]
    page_text = page.content().lower()
    if not any(t in page_text for t in conflict_texts):
        return

    print("  ⚠️  Обнаружен конфликт сессий — выходим с других устройств")
    _screenshot(page, "session_conflict")

    # Ищем кнопку подтверждения
    confirm_selectors = [
        "button:has-text('Выйти с других')",
        "button:has-text('Продолжить')",
        "button:has-text('Войти')",
        "a:has-text('Выйти с других')",
        "a:has-text('Продолжить')",
        "button:has-text('Yes')",
        "button:has-text('ОК')",
        "button:has-text('OK')",
        "button[type='submit']",
    ]
    for sel in confirm_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                page.wait_for_timeout(3000)
                print("  ✅ Вышли с других устройств")
                return
        except Exception:
            pass

    # Если кнопка не нашлась — ищем любую кнопку на странице с этим текстом
    buttons = page.locator("button, a.btn, input[type='submit']").all()
    for btn in buttons:
        try:
            txt = btn.inner_text().strip().lower()
            if any(x in txt for x in ["продолжить", "выйти", "войти", "continue", "ok"]):
                btn.click()
                page.wait_for_timeout(3000)
                print(f"  ✅ Нажали кнопку '{txt}'")
                return
        except Exception:
            pass


def _is_logged_in(page) -> bool:
    """Проверяет, вошли ли в аккаунт — ищет поисковую строку #SearchInput."""
    try:
        el = page.locator("#SearchInput")
        if el.count() > 0 and el.is_visible():
            return True
        pwd = page.locator("input[type='password']")
        if pwd.count() == 0:
            content = page.content().lower()
            if "личный кабинет" in content or "выйти" in content:
                return True
    except Exception:
        pass
    return False


def _download_law(page, title: str, doc_id: int | None, filename: str, index: dict) -> dict:
    """Скачивает один документ по doc_id или через поиск."""
    dest_path = LAWS_DIR / f"{filename}.docx"

    # Пропускаем уже скачанные файлы
    if dest_path.exists() and dest_path.stat().st_size > 10_000:
        size_kb = dest_path.stat().st_size // 1024
        print(f"    ⏭  уже есть ({size_kb} KB)")
        return {"filename": filename, "status": "skipped", "file": str(dest_path)}

    # Если doc_id не задан — ищем через поиск
    if doc_id is None:
        doc_id = _find_doc_id(page, title)
        if not doc_id:
            print(f"    ❌ Не найден в поиске")
            return {"filename": filename, "status": "not_found", "query": title}

    doc_url = f"{PARAGRAPH_URL.rstrip('/lawyer')}online.prg.kz/document/?doc_id={doc_id}"
    doc_page_url = f"https://online.prg.kz/document/?doc_id={doc_id}"
    word_url = f"https://online.prg.kz/document/Word.aspx?topic_id={doc_id}"

    # Открываем страницу документа
    try:
        page.goto(doc_page_url, wait_until="commit", timeout=30000)
        page.wait_for_timeout(3000)
    except Exception as e:
        print(f"    ❌ Ошибка загрузки страницы: {e}")
        return {"filename": filename, "status": "error", "error": str(e)}

    # Ждём пока оверлей maskmsg не скроется (он блокирует клики)
    try:
        page.wait_for_function(
            "!document.getElementById('maskmsg') || "
            "window.getComputedStyle(document.getElementById('maskmsg')).display === 'none' || "
            "document.getElementById('maskmsg').style.visibility === 'hidden'",
            timeout=15000,
        )
    except Exception:
        # Если не скрылся — скрываем принудительно через JS
        page.evaluate("var m = document.getElementById('maskmsg'); if(m) m.style.display='none';")
        page.wait_for_timeout(500)

    # Кнопка "Копировать в Word"
    word_btn = page.locator("div[title='Копировать в Word']")
    if word_btn.count() == 0:
        print(f"    ⚠️  Кнопка Word не найдена, сохраняем текст...")
        text_saved = _save_page_text_as_docx(page, title, dest_path, doc_page_url)
        if text_saved:
            size_kb = dest_path.stat().st_size // 1024 if dest_path.exists() else 0
            print(f"    ✅ Сохранён текст ({size_kb} KB)")
            return {"filename": filename, "status": "ok", "file": str(dest_path),
                    "source_url": doc_page_url, "downloaded_at": datetime.now().isoformat(),
                    "note": "text_fallback"}
        print(f"    ❌ Текст тоже не удалось сохранить")
        return {"filename": filename, "status": "error", "error": "кнопка Word не найдена"}

    # Проверяем g_access (0 = нет доступа → onclick не сработает)
    g_access = page.evaluate("typeof g_access !== 'undefined' ? g_access : -1")
    if g_access == 0:
        print(f"    ⚠️  Нет доступа к документу (g_access=0), сохраняем текст...")
        text_saved = _save_page_text_as_docx(page, title, dest_path, doc_page_url)
        if text_saved:
            size_kb = dest_path.stat().st_size // 1024 if dest_path.exists() else 0
            print(f"    ✅ Сохранён текст ({size_kb} KB)")
            return {"filename": filename, "status": "ok", "file": str(dest_path),
                    "source_url": doc_page_url, "downloaded_at": datetime.now().isoformat(),
                    "note": "text_only_no_access"}
        return {"filename": filename, "status": "error", "error": "g_access=0, текст не сохранён"}

    # Скачиваем Word (используем JS click чтобы обойти оверлеи)
    word_url = f"https://online.prg.kz/document/Word.aspx?topic_id={doc_id}"
    try:
        with page.expect_download(timeout=120000) as dl:
            word_btn.first.evaluate("el => el.click()")
        download = dl.value
        download.save_as(str(dest_path))
        size_kb = dest_path.stat().st_size // 1024 if dest_path.exists() else 0
        print(f"    ✅ Word скачан ({size_kb} KB)")
        return {
            "filename": filename,
            "status": "ok",
            "file": str(dest_path),
            "source_url": doc_page_url,
            "doc_id": doc_id,
            "downloaded_at": datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"    ❌ Ошибка скачивания Word: {e}")
        return {"filename": filename, "status": "error", "error": f"скачивание: {e}"}


def _find_doc_id(page, query: str) -> int | None:
    """Ищет документ через поисковую строку, возвращает первый подходящий doc_id."""
    import re as _re
    try:
        page.fill("#SearchInput", query)
        page.locator("button.btn-search").click()
        page.wait_for_timeout(4000)

        links = page.eval_on_selector_all("a[href*='doc_id']", """els => els
            .filter(e => {
                if (!e.offsetParent) return false;
                const m = (e.href||'').match(/doc_id=(\\d+)/);
                const text = (e.innerText||'').trim();
                return m && parseInt(m[1]) > 100 && text.length > 5;
            })
            .slice(0, 3)
            .map(e => ({
                text: (e.innerText||'').trim(),
                docId: parseInt((e.href||'').match(/doc_id=(\\d+)/)[1])
            }))""")

        for l in links:
            if l["docId"] > 100:
                print(f"    Найден: doc_id={l['docId']}: {l['text'][:50]}")
                return l["docId"]
    except Exception as e:
        logger.debug(f"Поиск '{query}': {e}")
    return None


def _search_document(page, query: str) -> str | None:
    """Ищет документ и возвращает URL первого результата."""
    try:
        # Пробуем поле поиска
        search_selectors = [
            "input[name='SearchInput']",
            "input[id*='search']",
            "input[placeholder*='оиск']",
            "input[placeholder*='earch']",
            ".search-block input",
            "input[type='text']:visible",
        ]

        for sel in search_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible() and not el.get_attribute("readonly"):
                    el.triple_click()
                    el.fill(query)
                    page.wait_for_timeout(500)
                    el.press("Enter")
                    page.wait_for_timeout(4000)

                    # Берём первый результат
                    url = _get_first_result_url(page)
                    if url:
                        return url
                    break
            except Exception:
                pass

        # Запасной вариант: прямой URL поиска
        encoded = query.replace(" ", "+")
        page.goto(f"{PARAGRAPH_URL}?SearchInput={encoded}&search=true", wait_until="commit", timeout=30000)
        page.wait_for_timeout(3000)
        return _get_first_result_url(page)

    except Exception as e:
        logger.debug(f"Ошибка поиска '{query}': {e}")
        return None


def _get_first_result_url(page) -> str | None:
    """Извлекает URL первого результата поиска."""
    link_selectors = [
        ".doctitle a", ".doc-title a", ".result-title a",
        ".search-result a", "td.docTitle a", ".document-link a",
        ".results-list a", "h3 a", "h4 a",
    ]
    for sel in link_selectors:
        links = page.locator(sel).all()
        for link in links:
            try:
                href = link.get_attribute("href") or ""
                text = link.inner_text().strip()
                if href and len(text) > 5:
                    if not href.startswith("http"):
                        href = "https://online.prg.kz" + href
                    return href
            except Exception:
                pass
    return None


def _try_download_word(page, dest_path: Path) -> bool:
    """Ищет кнопку скачивания Word и скачивает файл."""
    word_selectors = [
        "a[href*='.doc']", "a[href*='.docx']", "a[href*='word']",
        "a:has-text('Word')", "a:has-text('DOC')", "a:has-text('DOCX')",
        "button:has-text('Word')", "button:has-text('Скачать')",
        ".download-word", "[title*='Word']", "[title*='word']",
        "a[href*='rtf']", "a:has-text('RTF')",
    ]
    for sel in word_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                with page.expect_download(timeout=30000) as dl_info:
                    el.click()
                download = dl_info.value
                download.save_as(str(dest_path))
                return dest_path.exists() and dest_path.stat().st_size > 1000
        except Exception:
            pass
    return False


def _save_page_text_as_docx(page, title: str, dest_path: Path, source_url: str) -> bool:
    """Берёт текст со страницы документа и сохраняет как DOCX."""
    try:
        # Ищем основной текст документа
        content_selectors = [
            ".doc-text", ".document-text", ".document-body", ".content-area",
            "#document-content", ".law-text", "article", "main",
        ]
        text = ""
        for sel in content_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible():
                    text = el.inner_text()
                    if len(text) > 500:
                        break
            except Exception:
                pass

        if not text or len(text) < 200:
            text = page.inner_text("body")

        if len(text) < 200:
            return False

        # Сохраняем через laws_downloader.text_to_docx
        import sys, os
        sys.path.insert(0, os.path.dirname(__file__))
        from laws_downloader import text_to_docx
        text_to_docx(title.replace("_", " "), text, dest_path, source_url)
        return dest_path.exists() and dest_path.stat().st_size > 5000

    except Exception as e:
        logger.debug(f"Ошибка сохранения текста: {e}")
        return False


def _screenshot(page, name: str):
    """Сохраняет скриншот для отладки."""
    try:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOTS_DIR / f"para_{name}.png"))
    except Exception:
        pass


if __name__ == "__main__":
    import sys
    headless = "--visible" not in sys.argv

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print(f"Параграф загрузчик {'(headless)' if headless else '(видимый браузер)'}")
    print(f"Папка: {LAWS_DIR}")
    print("=" * 60)

    result = download_all(headless=headless)
    print("\n" + "=" * 60)
    if "error" in result:
        print(f"ОШИБКА: {result['error']}")
    else:
        print(f"Скачано: {result['downloaded']}, ошибок: {result['errors']}")
        for d in result.get("details", []):
            status_icon = {"ok": "✅", "skipped": "⏭ ", "not_found": "🔍"}.get(d["status"], "❌")
            print(f"  {status_icon} {d.get('filename', '?')}: {d['status']}")
    print(f"Файлы: {LAWS_DIR}")
