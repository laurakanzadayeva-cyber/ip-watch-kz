"""Анализ сохранённого HTML реестра"""
from bs4 import BeautifulSoup

with open("../data/downloads/trademark_search.html", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# Ищем грид результатов
for sel in ["#cvReestr", "[id*='Grid']", "[id*='Reestr']", "[id*='grid']"]:
    el = soup.select_one(sel)
    if el:
        print(f"Grid found: {sel} -> id={el.get('id')} tag={el.name}")
        break

# Все таблицы
tables = soup.find_all("table")
print(f"\nТаблиц на странице: {len(tables)}")
for i, t in enumerate(tables):
    row_count = len(t.find_all("tr"))
    tid = t.get("id", "")
    tcls = t.get("class", [])
    if row_count > 2 or "dxgv" in str(tcls) or tid:
        print(f"  Table[{i}] id={tid} class={tcls} rows={row_count}")
        rows = t.find_all("tr")
        for row in rows[:4]:
            cells = [td.get_text(" ", strip=True)[:40] for td in row.find_all(["td", "th"])]
            if cells:
                print(f"    CELLS: {cells}")

# DevExpress DataRow
dxg_rows = soup.select("tr.dxgvDataRow_Material, tr.dxgvDataRow, .dxgvDataRow")
print(f"\nDevExpress data rows: {len(dxg_rows)}")
for row in dxg_rows[:5]:
    cells = [td.get_text(" ", strip=True)[:50] for td in row.find_all("td")]
    links = [a.get("href", "") for a in row.find_all("a")]
    print(f"  cells={cells}")
    print(f"  links={links}")

# Заголовки колонок
headers = soup.select("th.dxgvHeader_Material, th.dxgvHeader, .dxgvHeader")
print(f"\nЗаголовки колонок: {[h.get_text(strip=True) for h in headers]}")

# Ищем любые ссылки на карточки знаков
mark_links = [(a.get_text(strip=True)[:40], a.get("href", "")) for a in soup.find_all("a") if "Trademark" in a.get("href", "") or "Details" in a.get("href", "")]
print(f"\nСсылки на карточки ({len(mark_links)}):")
for t, h in mark_links[:10]:
    print(f"  [{t}] -> {h}")

# Подсчёт записей
count_el = soup.select_one(".dxpSummary, .record-count, [id*='Summary']")
if count_el:
    print(f"\nСводка: {count_el.get_text(strip=True)}")
