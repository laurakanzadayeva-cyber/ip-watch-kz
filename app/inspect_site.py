"""Перехват эндпоинта Общеизвестных ТЗ через Playwright"""
from playwright.sync_api import sync_playwright
import urllib.parse
import json

def inspect():
    captured = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context()

        def on_request(req):
            if req.method == "POST" and "gosreestr.kazpatent.kz" in req.url:
                pd = req.post_data or ""
                decoded = urllib.parse.parse_qs(pd)
                entry = {
                    "url": req.url,
                    "params": {k: v[0] for k, v in decoded.items()},
                }
                captured.append(entry)
                print(f"\n>>> POST: {req.url}")
                for k, v in decoded.items():
                    if v[0]:
                        print(f"  {k} = {v[0][:60]}")

        ctx.on("request", on_request)
        page = ctx.new_page()
        page.set_extra_http_headers({"Accept-Language": "ru-RU,ru;q=0.9"})

        print("Открываем реестр...")
        page.goto("https://gosreestr.kazpatent.kz", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # Раскрываем NavBar группу "Товарные знаки"
        print("\n1. Кликаем на группу 'Товарные знаки'...")
        page.evaluate("""
            () => {
                const spans = Array.from(document.querySelectorAll('span.dxnb-ghtext, .dxnb-groupHeader span, span'));
                for (const s of spans) {
                    if (s.textContent.trim() === 'Товарные знаки') {
                        const td = s.closest('td');
                        if (td) { td.click(); return 'clicked td'; }
                        s.click();
                        return 'clicked span';
                    }
                }
                return 'not found';
            }
        """)
        page.wait_for_timeout(2000)

        # Скриншот после раскрытия группы
        page.screenshot(path="../data/screenshots/navbar_expanded.png")
        print("  Скриншот: navbar_expanded.png")

        # Кликаем "Общеизвестные товарные знаки"
        print("\n2. Кликаем 'Общеизвестные товарные знаки'...")
        result = page.evaluate("""
            () => {
                // Ищем все видимые элементы с таким текстом
                const all = Array.from(document.querySelectorAll('*'));
                const matches = all.filter(el =>
                    el.childElementCount === 0 &&
                    el.textContent.trim() === 'Общеизвестные товарные знаки' &&
                    el.offsetParent !== null
                );
                console.log('Найдено элементов:', matches.length);
                if (matches.length > 0) {
                    const el = matches[0];
                    console.log('Кликаем:', el.tagName, el.className);
                    el.click();
                    return `clicked ${el.tagName}.${el.className}`;
                }
                // Расширенный поиск
                const byText = Array.from(document.querySelectorAll('a, li, span, td, div'))
                    .filter(el => el.textContent.includes('Общеизвестные') && el.offsetParent !== null);
                if (byText.length > 0) {
                    byText[0].click();
                    return `clicked_extended: ${byText[0].tagName}.${byText[0].className.slice(0,30)}`;
                }
                return 'NOT FOUND';
            }
        """)
        print(f"  Результат: {result}")
        page.wait_for_timeout(3000)
        page.screenshot(path="../data/screenshots/well_known_clicked.png")
        print("  Скриншот: well_known_clicked.png")

        # Ждём новый POST
        page.wait_for_timeout(3000)

        print(f"\n=== Перехвачено {len(captured)} POST-запросов к реестру ===")
        for c in captured:
            print(f"\nURL: {c['url']}")
            key_params = {k: v for k, v in c['params'].items() if v}
            for k, v in key_params.items():
                print(f"  {k} = {v[:80]}")

        # Текущий URL и текст
        print(f"\nТекущий URL: {page.url}")
        title_text = page.evaluate("""
            () => {
                const title = document.querySelector('h1, h2, .page-title, .section-title');
                return title ? title.textContent : 'не найдено';
            }
        """)
        print(f"Заголовок секции: {title_text}")

        # Последний перехваченный POST - сохраняем
        if captured:
            well_known_posts = [c for c in captured if "Partial" in c['url']]
            if well_known_posts:
                last = well_known_posts[-1]
                print(f"\n!!! Endpoint найден: {last['url']}")
                with open("../data/downloads/well_known_post.json", "w", encoding="utf-8") as f:
                    json.dump(last, f, ensure_ascii=False, indent=2)

        page.wait_for_timeout(5000)
        ctx.close()
        browser.close()

if __name__ == "__main__":
    inspect()
