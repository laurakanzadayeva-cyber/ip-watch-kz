"""
IP Watch KZ — Мониторинг товарных знаков
Главное приложение Streamlit
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import sqlite3
import pandas as pd
import warnings
from datetime import datetime, date
from pathlib import Path

from database import init_db, get_connection
from similarity import RISK_LABELS, RISK_COLORS
from export_excel import generate_report
from config_manager import load_credentials, save_credentials, credentials_configured

# ─── Конфигурация страницы ───────────────────────────────────────────────────

st.set_page_config(
    page_title="IP Watch KZ",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Авторизация ─────────────────────────────────────────────────────────────

import auth as _auth
import extra_streamlit_components as stx
from datetime import timedelta

# Проверяем флаг открытого доступа (auth_required = false в st.secrets отключает вход)
_auth_required = True
try:
    _raw = st.secrets["auth_required"]
    if isinstance(_raw, bool):
        _auth_required = _raw
    else:
        _auth_required = str(_raw).lower() not in ("false", "0", "no")
except Exception:
    pass

_SESSION_COOKIE = "ipwatch_session"


_cookie_mgr = stx.CookieManager(key="ipwatch_cookies")


def _set_session_cookie(token: str):
    _cookie_mgr.set(
        _SESSION_COOKIE, token,
        expires_at=datetime.now() + timedelta(days=_auth.REMEMBER_DAYS),
        key="set_session_cookie",
    )


def _clear_session_cookie():
    try:
        _cookie_mgr.delete(_SESSION_COOKIE, key="del_session_cookie")
    except Exception:
        pass


# Авто-вход по cookie «Запомнить меня»
if _auth_required and "auth_user" not in st.session_state:
    try:
        _tok = _cookie_mgr.get(_SESSION_COOKIE)
    except Exception:
        _tok = None
    if _tok:
        _remembered = _auth.get_session_user(_tok)
        if _remembered:
            st.session_state["auth_user"] = _remembered
        else:
            # cookie указывает на уничтоженную/истёкшую сессию — убираем
            _clear_session_cookie()


def _render_auth_header():
    st.markdown("""
    <div style="display:flex;flex-direction:column;align-items:center;
                justify-content:center;gap:0;margin:6vh 0 24px;">
        <div style="margin-bottom:24px;text-align:center;">
            <div style="font-size:36px;font-weight:900;color:#1B2A4A;
                        letter-spacing:3px;font-family:'Segoe UI',Arial,sans-serif;
                        line-height:1;text-transform:uppercase;">SERGEK</div>
            <div style="font-size:20px;font-weight:700;color:#2563EB;
                        letter-spacing:5px;font-family:'Segoe UI',Arial,sans-serif;
                        text-transform:uppercase;margin-top:2px;">GROUP</div>
            <div style="width:100%;height:2px;background:linear-gradient(90deg,#2563EB,#93C5FD);
                        border-radius:2px;margin-top:8px;"></div>
        </div>
        <div style="background:#F0F7FF;border:1px solid #BFDBFE;border-radius:12px;
                    padding:14px 28px;text-align:center;">
            <div style="font-size:22px;font-weight:700;color:#1E3A8A;letter-spacing:-0.3px;">
                ⚖️ IP Watch KZ
            </div>
            <div style="font-size:13px;color:#64748B;margin-top:4px;">
                Система мониторинга товарных знаков
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def _render_auth_gate():
    """Экран входа/регистрации. Выполняет st.stop(), если пользователь не вошёл."""
    warnings.filterwarnings("ignore")

    _render_auth_header()
    _spacer_l, _center, _spacer_r = st.columns([1, 1.4, 1])
    with _center:
        tab_login, tab_register = st.tabs(["🔑 Вход", "📝 Регистрация"])

        # ── Вход ──────────────────────────────────────────────────────────────
        with tab_login:
            with st.form("login_form"):
                email = st.text_input("Электронная почта", key="login_email")
                password = st.text_input("Пароль", type="password", key="login_pwd")
                remember = st.checkbox("Запомнить меня", value=True, key="login_remember")
                submitted = st.form_submit_button("Войти", use_container_width=True, type="primary")
            if submitted:
                user = _auth.verify_login(email, password)
                if user:
                    st.session_state["auth_user"] = user
                    if remember:
                        # .set() сам инициирует перезагрузку после записи cookie
                        _set_session_cookie(_auth.create_session(user["email"]))
                    else:
                        st.rerun()
                else:
                    st.error("Неверная почта или пароль.")

        # ── Регистрация ───────────────────────────────────────────────────────
        with tab_register:
            _stage = st.session_state.get("reg_stage", "form")

            if _stage == "form":
                with st.form("register_form"):
                    r_name = st.text_input("Имя и фамилия", key="reg_name")
                    r_email = st.text_input("Электронная почта", key="reg_email")
                    r_pwd = st.text_input("Пароль (мин. 6 символов)", type="password", key="reg_pwd")
                    r_submit = st.form_submit_button("Зарегистрироваться", use_container_width=True, type="primary")
                if r_submit:
                    res = _auth.register_start(r_name, r_email, r_pwd)
                    if res["ok"]:
                        st.session_state["reg_stage"] = "confirm"
                        st.session_state["reg_pending_email"] = r_email.strip().lower()
                        st.session_state["reg_dev_code"] = res.get("dev_code")
                        st.rerun()
                    else:
                        st.error(res["error"])

            elif _stage == "confirm":
                pend_email = st.session_state.get("reg_pending_email", "")
                st.info(f"На адрес **{pend_email}** отправлен 6-значный код подтверждения.")
                dev_code = st.session_state.get("reg_dev_code")
                if dev_code:
                    st.warning(f"SMTP не настроен (dev-режим). Код: **{dev_code}**")
                with st.form("confirm_form"):
                    c_code = st.text_input("Код из письма", max_chars=6, key="reg_code")
                    c_submit = st.form_submit_button("Подтвердить", use_container_width=True, type="primary")
                if c_submit:
                    res = _auth.register_confirm(pend_email, c_code)
                    if res["ok"]:
                        st.session_state["auth_user"] = res["user"]
                        for k in ("reg_stage", "reg_pending_email", "reg_dev_code"):
                            st.session_state.pop(k, None)
                        st.success("Регистрация завершена!")
                        # .set() сам инициирует перезагрузку после записи cookie
                        _set_session_cookie(_auth.create_session(res["user"]["email"]))
                    else:
                        st.error(res["error"])
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("↻ Отправить код заново", use_container_width=True):
                        res = _auth.resend_code(pend_email)
                        if res["ok"]:
                            st.session_state["reg_dev_code"] = res.get("dev_code")
                            st.success("Код отправлен повторно.")
                            st.rerun()
                        else:
                            st.error(res["error"])
                with col_b:
                    if st.button("← Назад", use_container_width=True):
                        st.session_state["reg_stage"] = "form"
                        st.rerun()
    st.stop()


if _auth_required and "auth_user" not in st.session_state:
    _render_auth_gate()

# Данные текущего пользователя (пусто, если вход отключён)
_current_user = st.session_state.get("auth_user", {})
_auth_name = _current_user.get("name", "")

# ─── Инициализация БД ────────────────────────────────────────────────────────

init_db()

# ─── Вспомогательные функции ─────────────────────────────────────────────────

SOURCE_LABELS = {
    "kz_registry": "Реестр KZ",
    "kz_bulletin": "Бюллетень KZ",
    "wipo": "WIPO",
    "madrid": "Madrid",
    "manual": "Добавлено вручную",
}
OBJECT_TYPE_LABELS = {
    "trademark": "Товарный знак",
    "well_known": "Общеизвестный ТЗ",
    "trade_name": "Фирменное наименование",
}
STATUS_LABELS = {
    "active": "Действует",
    "application": "Заявка",
    "expired": "Прекращён",
    "refused": "Отказ",
    "unknown": "Иной",
}
LEGAL_STATUS_LABELS = {
    "not_reviewed": "Не проверено",
    "risk_confirmed": "Риск подтверждён",
    "risk_not_confirmed": "Риск не подтверждён",
    "archived": "Архив",
}
RISK_BADGE = {
    "high":          "🔴 Высокий",
    "medium":        "🟠 Средний",
    "low":           "🟢 Низкий",
    "informational": "🔵 Информ.",
}


def fmt_date(val):
    if not val:
        return "—"
    return str(val)


# ─── Транслитерация для товарных знаков КЗ ───────────────────────────────────

_RU_TO_LAT = {
    'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'YO','Ж':'ZH','З':'Z',
    'И':'I','Й':'Y','К':'K','Л':'L','М':'M','Н':'N','О':'O','П':'P','Р':'R',
    'С':'S','Т':'T','У':'U','Ф':'F','Х':'KH','Ц':'TS','Ч':'CH','Ш':'SH',
    'Щ':'SHCH','Ъ':'','Ы':'Y','Ь':'','Э':'E','Ю':'YU','Я':'YA',
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
    'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
    'щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
}
# Посимвольная транслитерация латиница → кириллица (для аббревиатур: KFS→КФС, BI→БИ)
_LAT_CHAR_TO_CYR = {
    'A':'А','B':'Б','C':'К','D':'Д','E':'Е','F':'Ф','G':'Г','H':'Х',
    'I':'И','J':'Ж','K':'К','L':'Л','M':'М','N':'Н','O':'О','P':'П',
    'Q':'К','R':'Р','S':'С','T':'Т','U':'У','V':'В','W':'В','X':'КС',
    'Y':'Й','Z':'З',
}

def _ru_to_lat(text: str) -> str:
    return ''.join(_RU_TO_LAT.get(c, c) for c in text)

def _lat_to_cyr(text: str) -> str:
    """Посимвольная транслитерация латиницы в кириллицу (для аббревиатур)."""
    return ''.join(_LAT_CHAR_TO_CYR.get(c.upper(), c) for c in text)

def _has_cyrillic(text: str) -> bool:
    return any('Ѐ' <= c <= 'ӿ' for c in text)

def _auto_variants(designation: str) -> list[str]:
    """
    Генерирует варианты написания обозначения:
    - Кириллица → латиница (СЕРГЕК → SERGEK)
    - Латиница → кириллица (KFS → КФС, SERGEK → СЕРГЕК)
    - Title Case варианты
    Используется чтобы один профиль охватывал оба языка.
    """
    variants = []
    d = designation.strip()
    if not d:
        return variants

    if _has_cyrillic(d):
        # Кириллица → Латиница
        lat = _ru_to_lat(d.upper())
        if lat and lat != d.upper():
            variants.append(lat)
            # Title case латиницы
            lat_title = lat.title()
            if lat_title != lat:
                variants.append(lat_title)
    else:
        # Латиница → Кириллица (посимвольно)
        cyr = _lat_to_cyr(d.upper())
        if cyr and cyr != d.upper():
            variants.append(cyr)
            # Title case кириллицы
            cyr_title = cyr.title()
            if cyr_title != cyr:
                variants.append(cyr_title)

    # Title Case исходного обозначения
    title = d.title()
    if title != d and title not in variants:
        variants.append(title)

    return list(dict.fromkeys(variants))  # убираем дубли


def calc_contestation(reg_date_val):
    """5-летний срок оспаривания ТЗ с даты регистрации (ст. 28 Закона о ТЗ РК)."""
    if not reg_date_val:
        return {"status": "unknown", "label": "—", "days_left": None, "deadline": None}
    try:
        if isinstance(reg_date_val, datetime):
            reg_date = reg_date_val.date()
        elif isinstance(reg_date_val, date):
            reg_date = reg_date_val
        else:
            s = str(reg_date_val).strip()[:10]
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
                try:
                    reg_date = datetime.strptime(s, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                return {"status": "unknown", "label": "—", "days_left": None, "deadline": None}

        deadline = date(reg_date.year + 5, reg_date.month, reg_date.day)
        today = date.today()
        days_left = (deadline - today).days

        if days_left < 0:
            return {"status": "expired", "label": "❌ Истёк",
                    "days_left": days_left, "deadline": deadline.strftime("%d.%m.%Y")}
        elif days_left <= 180:
            return {"status": "urgent", "label": f"⚠️ {days_left} дн.",
                    "days_left": days_left, "deadline": deadline.strftime("%d.%m.%Y")}
        else:
            y, m = days_left // 365, (days_left % 365) // 30
            lbl = f"✅ {y}л {m}м" if y > 0 else f"✅ {m} мес."
            return {"status": "open", "label": lbl,
                    "days_left": days_left, "deadline": deadline.strftime("%d.%m.%Y")}
    except Exception:
        return {"status": "unknown", "label": "—", "days_left": None, "deadline": None}


def get_profiles():
    with get_connection() as conn:
        return conn.execute("SELECT * FROM monitoring_profiles ORDER BY name").fetchall()


def get_sources():
    with get_connection() as conn:
        return conn.execute("SELECT * FROM sources ORDER BY name").fetchall()


def get_marks(filters: dict | None = None) -> list:
    with get_connection() as conn:
        # Подзапрос для nice_classes — избегаем GROUP BY (проблема в PostgreSQL)
        query = """
            SELECT fm.*,
                   (SELECT GROUP_CONCAT(mc.nice_class ORDER BY mc.nice_class)
                    FROM mark_classes mc WHERE mc.mark_id = fm.id) AS nice_classes_str,
                   mp.name AS profile_name
            FROM found_marks fm
            LEFT JOIN monitoring_profiles mp ON mp.id = fm.profile_id
        """
        conditions = []
        params = []

        if filters:
            if filters.get("source"):
                conditions.append("fm.source_code = ?")
                params.append(filters["source"])
            if filters.get("object_type"):
                conditions.append("fm.object_type = ?")
                params.append(filters["object_type"])
            if filters.get("risk_level"):
                conditions.append("fm.risk_level = ?")
                params.append(filters["risk_level"])
            if filters.get("legal_status"):
                conditions.append("fm.legal_status = ?")
                params.append(filters["legal_status"])
            if filters.get("include_in_report") is not None:
                conditions.append("fm.include_in_report = ?")
                params.append(1 if filters["include_in_report"] else 0)
            if filters.get("owner_contains"):
                conditions.append("fm.owner LIKE ?")
                params.append(f"%{filters['owner_contains']}%")
            if filters.get("profile_id"):
                conditions.append("fm.profile_id = ?")
                params.append(filters["profile_id"])
            if filters.get("date_from"):
                conditions.append("fm.first_found_at >= ?")
                params.append(filters["date_from"])
            if filters.get("date_to"):
                conditions.append("fm.first_found_at <= ?")
                params.append(filters["date_to"])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY fm.risk_level DESC, fm.first_found_at DESC"

        return conn.execute(query, params).fetchall()


def get_mark_by_id(mark_id: int):
    with get_connection() as conn:
        mark = conn.execute(
            """SELECT fm.*,
                      (SELECT GROUP_CONCAT(mc.nice_class ORDER BY mc.nice_class)
                       FROM mark_classes mc WHERE mc.mark_id = fm.id) AS nice_classes_str,
                      mp.name AS profile_name
               FROM found_marks fm
               LEFT JOIN monitoring_profiles mp ON mp.id = fm.profile_id
               WHERE fm.id = ?""",
            (mark_id,),
        ).fetchone()
        return mark


def get_runs():
    with get_connection() as conn:
        return conn.execute(
            """SELECT sr.*, mp.name AS profile_name
               FROM search_runs sr
               LEFT JOIN monitoring_profiles mp ON mp.id = sr.profile_id
               ORDER BY sr.started_at DESC LIMIT 200""",
        ).fetchall()


def update_mark(mark_id: int, **kwargs):
    with get_connection() as conn:
        allowed = {
            "legal_status", "lawyer_comment", "include_in_report",
            "risk_level", "recommended_action", "risk_confirmed", "recheck_needed",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(
            f"UPDATE found_marks SET {sets} WHERE id=?",
            list(updates.values()) + [mark_id],
        )
        conn.commit()


def render_bulletin_record(r: dict, year: int = None):
    """Отображает карточку результата из бюллетеня."""
    label = r.get("designation") or r.get("owner", "Запись")
    section_tag = r.get("section", "")
    obj_type = r.get("object_type", "")
    bull_num = r.get("bulletin_number", "?")
    year_str = f" {year}" if year else ""

    if obj_type == "application":
        icon = "📋"
    elif obj_type == "announcement":
        icon = "📝"
    else:
        icon = "✅"

    header = f"{icon} {label[:60]}  |  {section_tag}  |  Бюллетень{year_str} №{bull_num}"

    with st.expander(header):
        # Договоры/извещения — показываем полный текст
        if obj_type == "announcement" and r.get("announcement_text"):
            st.markdown("**Текст объявления:**")
            st.text(r["announcement_text"][:1500])
            st.write(f"**Номер регистрации договора:** {r.get('registration_number', '—')}")
            st.write(f"**Дата публикации:** {r.get('publication_date', '—')}")
        else:
            c1, c2 = st.columns(2)
            with c1:
                if r.get("application_number"):
                    st.write(f"**Заявка №:** {r['application_number']}")
                if r.get("registration_number"):
                    st.write(f"**Рег. №:** {r['registration_number']}")
                st.write(f"**Дата публ.:** {r.get('publication_date', '—')}")
                if r.get("application_date"):
                    st.write(f"**Дата подачи:** {r['application_date']}")
                if r.get("registration_date"):
                    st.write(f"**Дата рег.:** {r['registration_date']}")
            with c2:
                if r.get("owner"):
                    st.write(f"**Правообладатель/заявитель:** {r['owner'][:200]}")
                if r.get("owner_address"):
                    st.write(f"**Адрес:** {r['owner_address'][:120]}")
                if r.get("nice_classes"):
                    st.write(f"**Классы МКТУ:** {r['nice_classes']}")
                if r.get("colors"):
                    st.write(f"**Цвета:** {r['colors']}")
            if r.get("goods_services"):
                st.write(f"**Товары/услуги:** {r['goods_services'][:600]}")
        st.markdown(f"[🔗 Открыть бюллетень]({r.get('source_url', '')})")


# ─── CSS ─────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── Шрифт и фон ────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
}
.stApp { background: #F1F5F9; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { display: none !important; }
.stDeployButton { display: none !important; }

/* ── Сайдбар — тёмно-синий ──────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: #0F1F3D !important;
    border-right: 1px solid rgba(255,255,255,0.07) !important;
    padding: 0 !important;
}
section[data-testid="stSidebar"] > div:first-child {
    padding: 0 !important;
    display: flex;
    flex-direction: column;
    height: 100vh;
}
/* Скролл внутри сайдбара */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    background: #0F1F3D !important;
}

/* Метки секций навигации */
.sb-section-label {
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: 1.8px !important;
    text-transform: uppercase !important;
    color: rgba(255,255,255,0.28) !important;
    padding: 14px 16px 4px !important;
    margin: 0 !important;
    line-height: 1 !important;
}

/* Прячем радио input и кружок — несколько селекторов для разных версий Streamlit */
section[data-testid="stSidebar"] .stRadio input[type="radio"] {
    position: absolute !important; width: 0 !important; height: 0 !important;
    opacity: 0 !important; pointer-events: none !important;
}
/* Streamlit 1.30+: кружок — div[aria-hidden="true"] внутри label */
section[data-testid="stSidebar"] .stRadio label [aria-hidden="true"],
section[data-testid="stSidebar"] .stRadio label > div:first-child,
section[data-testid="stSidebar"] .stRadio [data-baseweb="radio"] > div:first-child,
section[data-testid="stSidebar"] .stRadio label > span:first-child {
    display: none !important;
    width: 0 !important; height: 0 !important;
    overflow: hidden !important; flex: none !important;
}
section[data-testid="stSidebar"] .stRadio > label { display: none; }
section[data-testid="stSidebar"] .stRadio > div {
    display: flex !important;
    flex-direction: column !important;
    gap: 1px !important;
    padding: 4px 10px !important;
}
section[data-testid="stSidebar"] .stRadio > div > label {
    display: flex !important;
    align-items: center !important;
    padding: 8px 12px !important;
    border-radius: 7px !important;
    cursor: pointer !important;
    font-size: 13px !important;
    color: rgba(255,255,255,0.65) !important;
    font-weight: 500 !important;
    transition: background 0.1s !important;
    margin: 0 !important;
    border-left: 3px solid transparent !important;
    gap: 0 !important;
}
/* Текстовый div — убрать лишний отступ слева */
section[data-testid="stSidebar"] .stRadio > div > label > div:last-child,
section[data-testid="stSidebar"] .stRadio > div > label > p {
    padding-left: 0 !important; margin-left: 0 !important;
    color: inherit !important;
}
section[data-testid="stSidebar"] .stRadio > div > label:hover {
    background: rgba(255,255,255,0.07) !important;
    color: rgba(255,255,255,0.9) !important;
}
section[data-testid="stSidebar"] .stRadio > div > label:has(input:checked),
section[data-testid="stSidebar"] .stRadio > div > label[data-baseweb="radio"]:has(input:checked) {
    background: rgba(59,130,246,0.18) !important;
    color: #fff !important;
    font-weight: 600 !important;
    border-left: 3px solid #3B82F6 !important;
}

/* Метки секций внутри одного radio-виджета через nth-child */
section[data-testid="stSidebar"] .stRadio > div > label:nth-child(5) {
    margin-top: 6px !important;
}
section[data-testid="stSidebar"] .stRadio > div > label:nth-child(5)::before {
    content: 'МОНИТОРИНГ';
    display: block;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.8px;
    color: rgba(255,255,255,0.28);
    text-transform: uppercase;
    padding: 0 0 8px;
    margin-bottom: 2px;
}
section[data-testid="stSidebar"] .stRadio > div > label:nth-child(9) {
    margin-top: 6px !important;
}
section[data-testid="stSidebar"] .stRadio > div > label:nth-child(9)::before {
    content: 'БАЗА ЗНАНИЙ';
    display: block;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.8px;
    color: rgba(255,255,255,0.28);
    text-transform: uppercase;
    padding: 0 0 8px;
    margin-bottom: 2px;
}

/* Кнопка Выйти в сайдбаре */
section[data-testid="stSidebar"] .stButton > button {
    color: rgba(255,255,255,0.5) !important;
    border-color: rgba(255,255,255,0.12) !important;
    background: transparent !important;
    font-size: 12px !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.07) !important;
    color: rgba(255,255,255,0.8) !important;
}

/* Popover в сайдбаре */
section[data-testid="stSidebar"] .stPopover > button {
    color: rgba(255,255,255,0.5) !important;
    border-color: rgba(255,255,255,0.12) !important;
    background: transparent !important;
    font-size: 12px !important;
    width: 100% !important;
}

/* ── Главная область ─────────────────────────────────────────────────────── */
div[data-testid="block-container"] {
    padding: 24px 32px !important;
    max-width: 1400px !important;
}

/* ── Кнопки ─────────────────────────────────────────────────────────────── */
div[data-testid="stButton"] > button[kind="primary"],
.stButton > button[kind="primary"] {
    background: #2563EB !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    padding: 9px 18px !important;
    transition: background 0.15s !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #1D4ED8 !important;
}
div[data-testid="stButton"] > button[kind="secondary"] {
    border-radius: 8px !important;
    font-weight: 500 !important;
}

/* ── Поля ввода ─────────────────────────────────────────────────────────── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div {
    border: 1px solid #E2E8F0 !important;
    border-radius: 8px !important;
    font-size: 14px !important;
    background: white !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #2563EB !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.1) !important;
}

/* ── Бейджи рисков ───────────────────────────────────────────────────────── */
.risk-badge-high   { background:#EF4444; color:white; padding:2px 10px; border-radius:4px; font-size:12px; font-weight:700; }
.risk-badge-medium { background:#F59E0B; color:white; padding:2px 10px; border-radius:4px; font-size:12px; font-weight:700; }
.risk-badge-low    { background:#10B981; color:white; padding:2px 10px; border-radius:4px; font-size:12px; font-weight:700; }
.risk-badge-info   { background:#3B82F6; color:white; padding:2px 10px; border-radius:4px; font-size:12px; font-weight:700; }

/* ── Метрики (новый стиль) ───────────────────────────────────────────────── */
.mc-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; margin:12px 0 20px; }
.mc { background:white; border:1px solid #E2E8F0; border-radius:10px; padding:16px 18px; position:relative; overflow:hidden; }
.mc::before { content:''; position:absolute; top:0; left:0; right:0; height:3px; }
.mc-blue::before  { background:#3B82F6; }
.mc-slate::before { background:#94A3B8; }
.mc-red::before   { background:#EF4444; }
.mc-amber::before { background:#F59E0B; }
.mc-green::before { background:#10B981; }
.mc-label { font-size:10px; font-weight:700; letter-spacing:.5px; text-transform:uppercase; color:#64748B; margin-bottom:10px; }
.mc-value { font-size:28px; font-weight:700; color:#0F172A; line-height:1; }
.mc-sub   { font-size:11px; color:#94A3B8; margin-top:5px; }
.mc-trend-up   { font-size:11px; color:#EF4444; margin-top:5px; }
.mc-trend-ok   { font-size:11px; color:#10B981; margin-top:5px; }

/* ── Статус-пиллы ───────────────────────────────────────────────────────── */
.pill { display:inline-flex; align-items:center; gap:4px; padding:2px 8px; border-radius:20px; font-size:11px; font-weight:600; }
.pill-green  { background:#DCFCE7; color:#166534; }
.pill-red    { background:#FEE2E2; color:#991B1B; }
.pill-amber  { background:#FEF3C7; color:#92400E; }
.pill-blue   { background:#DBEAFE; color:#1E40AF; }
.pill-slate  { background:#F1F5F9; color:#475569; }

/* ── Заголовки секций ────────────────────────────────────────────────────── */
.section-header { font-size:16px; font-weight:600; color:#0F172A; margin:0 0 10px; display:flex; align-items:center; justify-content:space-between; }
.section-link   { font-size:12px; font-weight:500; color:#3B82F6; cursor:pointer; }
.section-header { font-size:18px; font-weight:600; color:#111827; margin-bottom:8px; padding-bottom:6px; border-bottom:2px solid #E5E7EB; }

/* ── Страница Возражения ─────────────────────────────────────────────────── */
.opp-hero {
    background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%);
    border-radius: 16px;
    padding: 28px 32px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.opp-hero-text h1 { font-size: 28px; font-weight: 700; color: #111827; margin: 0 0 6px; }
.opp-hero-text p  { font-size: 14px; color: #4B5563; margin: 0; max-width: 420px; line-height: 1.5; }
.opp-hero-art { font-size: 72px; line-height: 1; }

.mode-pills { display: flex; gap: 8px; margin-bottom: 24px; }
.mode-pill {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 8px 18px; border-radius: 20px; font-size: 14px; font-weight: 500;
    border: 1.5px solid #E5E7EB; background: white; color: #374151; cursor: pointer;
}
.mode-pill.active { background: #2563EB; color: white; border-color: #2563EB; }

.step-header {
    display: flex; align-items: center; gap: 12px;
    margin: 28px 0 14px;
}
.step-num {
    display: inline-flex; align-items: center; justify-content: center;
    width: 32px; height: 32px; min-width: 32px;
    background: #2563EB; color: white;
    border-radius: 8px; font-weight: 700; font-size: 15px;
}
.step-title { font-size: 17px; font-weight: 600; color: #111827; }

.form-card {
    background: white; border: 1px solid #E5E7EB;
    border-radius: 12px; padding: 20px 24px; margin-bottom: 12px;
}

.help-card {
    background: white; border: 1px solid #E5E7EB;
    border-radius: 12px; padding: 20px; margin-bottom: 16px;
}
.help-card-title {
    font-size: 15px; font-weight: 600; color: #2563EB; margin: 0 0 14px;
}
.help-step {
    display: flex; gap: 10px; margin-bottom: 10px;
    align-items: flex-start; font-size: 13px; color: #374151; line-height: 1.4;
}
.help-step-num {
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; min-width: 22px;
    background: #EFF6FF; color: #2563EB;
    border-radius: 50%; font-size: 11px; font-weight: 700;
}
.tip-row {
    display: flex; gap: 8px; margin-bottom: 8px;
    font-size: 13px; color: #6B7280; line-height: 1.4;
}
.tip-icon { font-size: 14px; min-width: 18px; }

.gen-btn-wrap {
    position: sticky; bottom: 24px;
    background: white; border: 1px solid #E5E7EB;
    border-radius: 12px; padding: 16px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    margin-top: 16px;
    text-align: center;
}
.gen-btn-sub { font-size: 12px; color: #9CA3AF; margin-top: 6px; }

.inline-add-btn button {
    background: white !important; border: 1.5px dashed #D1D5DB !important;
    border-radius: 8px !important; color: #6B7280 !important;
    font-size: 13px !important; padding: 6px 14px !important;
}
.inline-add-btn button:hover {
    border-color: #2563EB !important; color: #2563EB !important;
    background: #EFF6FF !important;
}

.bin-row { display: flex; gap: 8px; align-items: flex-end; margin-bottom: 12px; }

.mark-row {
    display: flex; gap: 8px; align-items: center;
    background: #F9FAFB; border: 1px solid #E5E7EB;
    border-radius: 8px; padding: 8px 12px; margin-bottom: 6px;
}
</style>
""", unsafe_allow_html=True)

# ─── Боковое меню ────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style="padding:18px 16px 14px;border-bottom:1px solid rgba(255,255,255,0.07);">
        <!-- Логотип SERGEK GROUP на тёмном фоне -->
        <div style="margin-bottom:14px;">
            <div style="font-size:20px;font-weight:900;color:#FFFFFF;
                        letter-spacing:2.5px;font-family:'Segoe UI',Arial,sans-serif;
                        text-transform:uppercase;line-height:1;">SERGEK</div>
            <div style="font-size:11px;font-weight:700;color:#60A5FA;
                        letter-spacing:4px;font-family:'Segoe UI',Arial,sans-serif;
                        text-transform:uppercase;margin-top:1px;">GROUP</div>
            <div style="width:40px;height:2px;background:#3B82F6;
                        border-radius:1px;margin-top:5px;"></div>
        </div>
        <!-- Бейдж системы -->
        <div style="display:flex;align-items:center;gap:9px;
                    background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.25);
                    border-radius:8px;padding:8px 10px;">
            <span style="font-size:15px;">⚖️</span>
            <div>
                <div style="font-size:12px;font-weight:700;color:#BFDBFE;line-height:1.2;">IP Watch KZ</div>
                <div style="font-size:10px;color:rgba(255,255,255,0.3);margin-top:1px;">
                    Мониторинг товарных знаков
                </div>
            </div>
        </div>
    </div>
    <p class="sb-section-label">ОСНОВНОЕ</p>
    """, unsafe_allow_html=True)

    page = st.radio(
        "Раздел",
        [
            "🏠 Главная",
            "🔍 Единый поиск",
            "📋 Профили мониторинга",
            "🌐 Источники",
            "▶️ Запуск проверки",
            "📊 Результаты",
            "📰 Бюллетень Kazpatent",
            "⚖️ Мониторинг законодательства",
            "📚 Правовая база",
            "📝 Отчёты",
            "📖 Журнал проверок",
            "⚙️ Настройки",
        ],
        label_visibility="collapsed",
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    with st.popover("📖 Руководство пользователя", use_container_width=True):
        st.markdown("""
### IP Watch KZ — Руководство пользователя

**Назначение системы**
IP Watch KZ предназначена для мониторинга заявок и регистраций товарных знаков,
поиска совпадений, правовой оценки рисков и формирования отчётов для юридической защиты ИС.

---

**Шаг 1. Создание профиля мониторинга**
Раздел «Профили мониторинга» → «Создать профиль».
Укажите название профиля, основное обозначение товарного знака и варианты написания
(кириллица, латиница, транслитерация, сочетания).

**Шаг 2. Запуск проверки**
Кнопка «🔄 Проверить сейчас» на главной странице — система автоматически проверит
реестр Kazpatent и бюллетени по всем активным профилям.
Или перейдите в «Запуск проверки» для ручной настройки источников.

**Шаг 3. Просмотр результатов**
Раздел «Результаты» — все найденные совпадения с фильтрами по риску, источнику,
статусу правовой проверки. Нажмите на запись для детального просмотра и оценки.

**Шаг 4. Правовая оценка**
В детальной карточке записи укажите: уровень риска, статус проверки,
рекомендуемое действие и комментарий юриста.

**Шаг 5. Формирование отчёта**
Раздел «Отчёты» → выберите период и профиль → сформируйте Excel-отчёт.

---

**Дополнительные возможности**
- **Единый поиск** — поиск по обозначению, правообладателю, номеру заявки
- **Бюллетень Kazpatent** — просмотр новых публикаций
- **Мониторинг законодательства** — отслеживание изменений НПА
- **Правовая база** → «Актуальность» — проверка изменений законов на Adilet
- **Журнал проверок** — история всех запусков мониторинга

---

**Краткий алгоритм работы**
1. Создать профиль мониторинга
2. Запустить проверку
3. Проанализировать найденные совпадения
4. Провести правовую оценку
5. Сформировать отчёт
        """)
        st.divider()
        _manual_path = Path(__file__).parent.parent / "laws" / "core_docs" / "Руководство_пользователя_IP_Watch_KZ.docx"
        if _manual_path.exists():
            with open(_manual_path, "rb") as _mf:
                st.download_button(
                    "⬇️ Скачать руководство (.docx)",
                    data=_mf.read(),
                    file_name="Руководство_пользователя_IP_Watch_KZ.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )

    # ── Кнопка выхода внизу сайдбара ─────────────────────────────────────────
    st.markdown(
        "<div style='border-top:1px solid rgba(255,255,255,0.08);margin-top:8px;padding-top:8px;'></div>",
        unsafe_allow_html=True,
    )
    if _current_user:
        st.markdown(
            f"<div style='font-size:12px;color:rgba(255,255,255,0.55);"
            f"padding:2px 4px 8px;'>👤 {_auth_name or _current_user.get('email','')}</div>",
            unsafe_allow_html=True,
        )
        if st.button("🚪 Выйти", use_container_width=True):
            try:
                _tok_out = _cookie_mgr.get(_SESSION_COOKIE)
                if _tok_out:
                    _auth.destroy_session(_tok_out)
            except Exception:
                pass
            _clear_session_cookie()
            for _k in ("auth_user", "reg_stage", "reg_pending_email", "reg_dev_code"):
                st.session_state.pop(_k, None)
            st.rerun()


# ─── ГЛАВНАЯ ─────────────────────────────────────────────────────────────────

if page == "🏠 Главная":
    st.markdown("""
    <div style="display:flex;align-items:center;justify-content:space-between;
                margin-bottom:4px;">
        <div>
            <div style="font-size:22px;font-weight:700;color:#0F172A;line-height:1.2;">
                Главная
            </div>
            <div style="font-size:13px;color:#64748B;margin-top:3px;">
                Дашборд мониторинга · IP Watch KZ
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    conn = get_connection()
    last_run = conn.execute(
        "SELECT MAX(started_at) AS last FROM search_runs WHERE status='success'"
    ).fetchone()
    active_profiles_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM monitoring_profiles WHERE status='active'"
    ).fetchone()["cnt"]
    new_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM found_marks WHERE legal_status='not_reviewed'"
    ).fetchone()["cnt"]
    high_risk = conn.execute(
        "SELECT COUNT(*) AS cnt FROM found_marks WHERE risk_level='high'"
    ).fetchone()["cnt"]
    medium_risk = conn.execute(
        "SELECT COUNT(*) AS cnt FROM found_marks WHERE risk_level='medium'"
    ).fetchone()["cnt"]
    total_marks = conn.execute("SELECT COUNT(*) AS cnt FROM found_marks").fetchone()["cnt"]
    conn.close()

    last_run_dt = last_run["last"] if last_run else None
    last_run_str = fmt_date(last_run_dt) if last_run_dt else None

    # ── Авто-уведомление если прошло > 24 часов ──
    need_check = False
    if last_run_dt:
        try:
            from datetime import timezone
            lr = datetime.fromisoformat(str(last_run_dt).replace("Z", "+00:00"))
            if lr.tzinfo is None:
                lr = lr.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - lr).total_seconds() / 3600
            if age_hours > 24:
                need_check = True
        except Exception:
            pass
    else:
        need_check = True

    col_title, col_btn = st.columns([3, 1])
    with col_title:
        if last_run_str:
            st.markdown(
                f'<div style="font-size:13px;color:#64748B;padding-top:8px;">'
                f'<span style="display:inline-block;width:7px;height:7px;background:#10B981;'
                f'border-radius:50%;margin-right:6px;vertical-align:middle;"></span>'
                f'Последняя проверка: {last_run_str}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div style="font-size:13px;color:#94A3B8;padding-top:8px;">'
                'Проверка ещё не запускалась</div>',
                unsafe_allow_html=True,
            )
    with col_btn:
        run_now = st.button("🔄 Проверить сейчас", type="primary", use_container_width=True)

    if need_check and not run_now:
        st.markdown("""
        <div style="background:#FFFBEB;border:1px solid #FDE68A;border-left:4px solid #F59E0B;
                    border-radius:8px;padding:10px 14px;font-size:13px;color:#92400E;
                    display:flex;align-items:center;gap:8px;margin-top:4px;">
            ⚠️ Прошло более 24 часов с последней проверки. Рекомендуется запустить мониторинг.
        </div>
        """, unsafe_allow_html=True)

    if run_now:
        if active_profiles_count == 0:
            st.warning("Нет активных профилей. Создайте профиль в разделе «Профили мониторинга».")
        else:
            from monitor import run_monitoring
            with st.spinner("Выполняется мониторинг реестра Kazpatent..."):
                res = run_monitoring()
            if res.get("errors"):
                st.error(f"Ошибки при проверке: {res['errors'][0]['error']}")
            else:
                st.success(f"✅ Проверка завершена. Найдено: {res['total_found']}, новых: {res['total_new']}.")
            st.rerun()

    st.markdown(f"""
    <div class="mc-grid">
        <div class="mc mc-blue">
            <div class="mc-label">Активных профилей</div>
            <div class="mc-value">{active_profiles_count}</div>
            <div class="mc-sub">Под наблюдением</div>
        </div>
        <div class="mc mc-slate">
            <div class="mc-label">Всего найдено</div>
            <div class="mc-value">{total_marks}</div>
            <div class="mc-sub">Совпадений за всё время</div>
        </div>
        <div class="mc mc-red">
            <div class="mc-label">Высокий риск</div>
            <div class="mc-value">{high_risk}</div>
            <div class="mc-sub">Требует немедленного внимания</div>
        </div>
        <div class="mc mc-amber">
            <div class="mc-label">Средний риск</div>
            <div class="mc-value">{medium_risk}</div>
            <div class="mc-sub">Под наблюдением</div>
        </div>
        <div class="mc mc-green">
            <div class="mc-label">Не проверено</div>
            <div class="mc-value">{new_count}</div>
            <div class="mc-sub">Ожидают правовой оценки</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-header" style="font-size:15px;font-weight:600;color:#0F172A;margin-bottom:8px;">Статус источников</div>', unsafe_allow_html=True)

    sources = get_sources()
    if sources:
        rows_html = ""
        for s in sources:
            if s["status"] == "active":
                pill = '<span class="pill pill-green">● Активен</span>'
            else:
                pill = '<span class="pill pill-slate">⏸ Отключён</span>'
            err = s["last_error"] or "—"
            checked = fmt_date(s["last_checked"])
            rows_html += f"""
            <tr>
                <td style="padding:9px 14px;font-size:13px;font-weight:500;color:#0F172A;
                           border-bottom:1px solid #F1F5F9;">{s['name']}</td>
                <td style="padding:9px 14px;border-bottom:1px solid #F1F5F9;">{pill}</td>
                <td style="padding:9px 14px;font-size:13px;color:#64748B;
                           border-bottom:1px solid #F1F5F9;">{checked}</td>
                <td style="padding:9px 14px;font-size:13px;color:#94A3B8;
                           border-bottom:1px solid #F1F5F9;">{err}</td>
            </tr>"""
        st.markdown(f"""
        <div style="background:white;border:1px solid #E2E8F0;border-radius:10px;overflow:hidden;">
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="background:#F8FAFC;">
                        <th style="padding:8px 14px;text-align:left;font-size:10px;font-weight:700;
                                   letter-spacing:.5px;text-transform:uppercase;color:#64748B;">Источник</th>
                        <th style="padding:8px 14px;text-align:left;font-size:10px;font-weight:700;
                                   letter-spacing:.5px;text-transform:uppercase;color:#64748B;">Статус</th>
                        <th style="padding:8px 14px;text-align:left;font-size:10px;font-weight:700;
                                   letter-spacing:.5px;text-transform:uppercase;color:#64748B;">Последняя проверка</th>
                        <th style="padding:8px 14px;text-align:left;font-size:10px;font-weight:700;
                                   letter-spacing:.5px;text-transform:uppercase;color:#64748B;">Ошибка</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("Источники не настроены.")

    if total_marks == 0:
        st.info("💡 Создайте профиль мониторинга и нажмите «Проверить сейчас» для запуска первого мониторинга.")


# ─── ЕДИНЫЙ ПОИСК ────────────────────────────────────────────────────────────

elif page == "🔍 Единый поиск":
    st.title("Единый поиск по реестру и бюллетеню")
    st.markdown("Введите обозначение — система проверит реестр Kazpatent и бюллетени за выбранные годы.")

    with st.form("unified_search"):
        col_q, col_mode = st.columns([3, 1])
        with col_q:
            query = st.text_input(
                "Обозначение или регистрационный номер",
                placeholder="Например: SERGEK  или  56289",
            )
        with col_mode:
            search_mode = st.radio(
                "Искать по",
                options=["названию", "номеру"],
                index=0,
                horizontal=True,
                help="Выберите «номеру» чтобы найти конкретный знак по рег. номеру",
            )
        col1, col2 = st.columns(2)
        with col1:
            search_registry_cb = st.checkbox("Реестр Kazpatent (все зарегистрированные)", value=True)
            search_bulletin_cb = st.checkbox("Бюллетень (новые публикации по годам)", value=True)
        with col2:
            current_year = datetime.now().year
            years_available = list(range(2021, current_year + 1))
            selected_years = st.multiselect(
                "Годы бюллетеня",
                options=years_available,
                default=[current_year - 1, current_year],
                help="Выберите годы для поиска в бюллетене",
            )
        submitted = st.form_submit_button("🔍 Найти", type="primary")

    if submitted and query.strip():
        query = query.strip()
        # Автодетект: если запрос состоит только из цифр — переключаем на поиск по номеру
        by_number = (search_mode == "номеру") or query.isdigit()

        # ── Реестр ──
        if search_registry_cb:
            st.markdown("### 📚 Реестр Kazpatent")
            with st.spinner("Поиск в реестре..."):
                try:
                    from scraper_kazpatent import search_trademarks
                    if by_number:
                        reg_results = search_trademarks(
                            query="", reg_number=query,
                            object_type="trademark", max_pages=2,
                        )
                    else:
                        reg_results = search_trademarks(query, object_type="trademark", max_pages=5)
                    if reg_results:
                        st.success(f"Найдено в реестре: **{len(reg_results)}** знаков")
                        for r in reg_results:
                            label = r.get("designation") or query
                            reg_num = r.get("registration_number", "")
                            owner = r.get("owner", "")
                            with st.expander(f"📌 {label[:60]}  |  Рег. № {reg_num}"):
                                c1, c2 = st.columns(2)
                                with c1:
                                    st.write(f"**Рег. №:** {reg_num}")
                                    st.write(f"**Заявка №:** {r.get('application_number', '—')}")
                                    st.write(f"**Дата рег.:** {r.get('registration_date', '—')}")
                                    st.write(f"**Статус:** {r.get('status_mark', '—')}")
                                with c2:
                                    st.write(f"**Правообладатель:** {owner[:150]}")
                                    st.write(f"**Классы МКТУ:** {r.get('nice_classes', '—')}")
                                if r.get("source_url"):
                                    st.markdown(f"[🔗 Карточка в реестре]({r['source_url']})")
                    else:
                        st.info(f"В реестре по запросу «{query}» ничего не найдено.")
                except Exception as e:
                    st.error(f"Ошибка реестра: {e}")

        # ── Бюллетень ──
        if search_bulletin_cb and selected_years:
            st.markdown("### 📰 Бюллетень Kazpatent")
            from scraper_bulletin import search_bulletin as search_bulletin_fn, get_issue_dates

            total_bulletin = 0
            for year in sorted(selected_years):
                with st.spinner(f"Поиск в бюллетене {year}..."):
                    try:
                        issues_map = get_issue_dates(year)
                        if not issues_map:
                            st.caption(f"{year}: нет данных о выпусках.")
                            continue
                        bull_results = search_bulletin_fn(year=year, keywords=[query])
                        if bull_results:
                            st.success(f"**{year}:** найдено {len(bull_results)} публикаций")
                            total_bulletin += len(bull_results)
                            for r in bull_results:
                                render_bulletin_record(r, year=year)
                        else:
                            st.caption(f"**{year}:** публикаций с «{query}» не найдено ({len(issues_map)} выпусков проверено).")
                    except Exception as e:
                        st.error(f"Ошибка бюллетеня {year}: {e}")

            if search_registry_cb or total_bulletin == 0:
                st.info(
                    "ℹ️ Бюллетень содержит только **новые** публикации за год. "
                    "Если знак зарегистрирован до 2021 г. — он будет только в реестре."
                )
    elif submitted:
        st.warning("Введите обозначение для поиска.")


# ─── ПРОФИЛИ МОНИТОРИНГА ─────────────────────────────────────────────────────

elif page == "📋 Профили мониторинга":
    st.title("Профили мониторинга")

    tab1, tab2 = st.tabs(["Список профилей", "Создать профиль"])

    with tab1:
        profiles = get_profiles()
        if not profiles:
            st.info("Профили не созданы. Перейдите на вкладку «Создать профиль».")
        else:
            for p in profiles:
                with st.expander(f"{'✅' if p['status']=='active' else '⏸️'} {p['name']} — {p['main_designation']}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Основное обозначение:** {p['main_designation']}")
                        with get_connection() as conn:
                            variants = conn.execute(
                                "SELECT variant FROM profile_variants WHERE profile_id=?", (p["id"],)
                            ).fetchall()
                        if variants:
                            st.write(f"**Варианты:** {', '.join(v['variant'] for v in variants)}")
                        st.write(f"**Режим поиска:** {p['search_mode']}")
                        st.write(f"**МКТУ:** {p['nice_classes']}")
                    with col2:
                        sources_list = (p["sources"] or "").split(",")
                        st.write(f"**Источники:** {', '.join(SOURCE_LABELS.get(s.strip(), s.strip()) for s in sources_list)}")
                        obj_list = (p["object_types"] or "").split(",")
                        st.write(f"**Типы объектов:** {', '.join(OBJECT_TYPE_LABELS.get(o.strip(), o.strip()) for o in obj_list)}")
                        if p["comment"]:
                            st.write(f"**Комментарий:** {p['comment']}")

                    col_edit, col_del = st.columns([1, 1])
                    with col_edit:
                        new_status = "active" if p["status"] == "disabled" else "disabled"
                        label = "▶️ Активировать" if p["status"] == "disabled" else "⏸️ Отключить"
                        if st.button(label, key=f"toggle_{p['id']}"):
                            with get_connection() as conn:
                                conn.execute(
                                    "UPDATE monitoring_profiles SET status=? WHERE id=?",
                                    (new_status, p["id"])
                                )
                                conn.commit()
                            st.rerun()
                    with col_del:
                        if st.button("🗑️ Удалить", key=f"del_{p['id']}"):
                            with get_connection() as conn:
                                pid = p["id"]
                                conn.execute("PRAGMA foreign_keys = OFF")
                                conn.execute("DELETE FROM mark_classes WHERE mark_id IN (SELECT id FROM found_marks WHERE profile_id=?)", (pid,))
                                conn.execute("DELETE FROM found_marks WHERE profile_id=?", (pid,))
                                conn.execute("DELETE FROM search_runs WHERE profile_id=?", (pid,))
                                conn.execute("DELETE FROM profile_variants WHERE profile_id=?", (pid,))
                                conn.execute("DELETE FROM monitoring_profiles WHERE id=?", (pid,))
                                conn.execute("PRAGMA foreign_keys = ON")
                                conn.commit()
                            st.rerun()

    with tab2:
        st.subheader("Новый профиль мониторинга")

        # Превью авто-вариантов (вне формы, динамически)
        _prev_desig = st.session_state.get("_prev_desig_input", "")
        _prev_input = st.text_input(
            "Основное обозначение *",
            key="_prev_desig_input",
            placeholder="СЕРГЕК или SERGEK — система добавит оба варианта автоматически",
        )
        _auto = _auto_variants(_prev_input)
        if _auto:
            st.info(f"🔄 Система автоматически добавит варианты: **{', '.join(_auto)}**")

        with st.form("create_profile"):
            name = st.text_input("Название профиля *", placeholder="Мониторинг основного бренда")
            main_designation = st.text_input(
                "Основное обозначение *",
                value=_prev_input,
                placeholder="Введите обозначение товарного знака",
            )
            variants_raw = st.text_area(
                "Дополнительные варианты (каждый с новой строки)",
                placeholder="Сергек Медиа\nSergek Media\nБИ АЙ ГРУПП\n— авто-варианты добавятся сами",
            )
            col1, col2 = st.columns(2)
            with col1:
                object_types = st.multiselect(
                    "Типы объектов",
                    options=["trademark", "well_known"],
                    default=[],
                    format_func=lambda x: OBJECT_TYPE_LABELS.get(x, x),
                )
                search_mode = st.selectbox(
                    "Режим поиска",
                    options=["strict", "normal", "wide"],
                    index=1,
                    format_func=lambda x: {"strict": "Строгий", "normal": "Обычный", "wide": "Широкий"}[x],
                )
            with col2:
                sources = st.multiselect(
                    "Источники",
                    options=["kz_registry", "kz_bulletin", "wipo", "madrid"],
                    default=[],
                    format_func=lambda x: SOURCE_LABELS.get(x, x),
                )
                nice_classes = st.text_input("Классы МКТУ", value="all", help="'all' — все классы, или через запятую: 9,35,42")
            excluded_owners = st.text_input("Исключаемые правообладатели", placeholder="Serge Group, SGT KZ")
            comment = st.text_area("Комментарий", height=80)

            submitted = st.form_submit_button("✅ Создать профиль", type="primary")
            if submitted:
                if not name or not main_designation:
                    st.error("Заполните обязательные поля: «Название профиля» и «Основное обозначение».")
                else:
                    with get_connection() as conn:
                        cur = conn.execute(
                            """INSERT INTO monitoring_profiles
                               (name, main_designation, object_types, sources, nice_classes,
                                excluded_owners, search_mode, comment)
                               VALUES (?,?,?,?,?,?,?,?)""",
                            (
                                name, main_designation,
                                ",".join(object_types),
                                ",".join(sources),
                                nice_classes,
                                excluded_owners,
                                search_mode,
                                comment,
                            ),
                        )
                        profile_id = cur.lastrowid
                        if profile_id is None:
                            row = conn.execute(
                                "SELECT id FROM monitoring_profiles WHERE name=? ORDER BY id DESC LIMIT 1",
                                (name,)
                            ).fetchone()
                            profile_id = row[0] if row else None

                        # Авто-варианты (транслитерация)
                        all_variants = list(_auto_variants(main_designation))
                        # Пользовательские варианты
                        for variant in variants_raw.strip().splitlines():
                            v = variant.strip()
                            if v and v not in all_variants:
                                all_variants.append(v)
                        for v in all_variants:
                            conn.execute(
                                "INSERT INTO profile_variants (profile_id, variant) VALUES (?,?)",
                                (profile_id, v),
                            )
                        conn.commit()
                    auto_msg = f" Авто-добавлены варианты: {', '.join(_auto_variants(main_designation))}." if _auto_variants(main_designation) else ""
                    st.success(f"Профиль «{name}» создан.{auto_msg}")
                    st.rerun()


# ─── ИСТОЧНИКИ ───────────────────────────────────────────────────────────────

elif page == "🌐 Источники":
    st.title("Источники мониторинга")

    sources = get_sources()
    for s in sources:
        status_icon = "✅" if s["status"] == "active" else "🔵" if s["status"] == "planned" else "⏸️"
        with st.expander(f"{status_icon} {s['name']}"):
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"**Код:** `{s['code']}`")
                st.write(f"**URL:** {s['url'] or '—'}")
                st.write(f"**Статус:** {s['status']}")
            with c2:
                st.write(f"**Последняя проверка:** {fmt_date(s['last_checked'])}")
                if s["last_error"]:
                    st.error(f"Последняя ошибка: {s['last_error']}")

    st.markdown("---")
    st.info(
        "WIPO и Madrid Monitor запланированы для MVP+ (вторая версия). "
        "На данный момент доступны источники реестра и бюллетеня Kazpatent."
    )


# ─── ЗАПУСК ПРОВЕРКИ ─────────────────────────────────────────────────────────

elif page == "▶️ Запуск проверки":
    st.title("Запуск мониторинга")

    profiles = get_profiles()
    active_profiles = [p for p in profiles if p["status"] == "active"]

    if not active_profiles:
        st.warning("Нет активных профилей. Создайте профиль в разделе «Профили мониторинга».")
    else:
        st.markdown("### Выбор параметров проверки")

        col1, col2 = st.columns(2)
        with col1:
            selected_profiles_names = st.multiselect(
                "Профили (оставьте пустым — все активные)",
                options=[p["name"] for p in active_profiles],
            )
        with col2:
            selected_sources = st.multiselect(
                "Источники (оставьте пустым — все активные)",
                options=["kz_registry", "kz_bulletin"],
                format_func=lambda x: SOURCE_LABELS.get(x, x),
            )

        st.markdown("---")
        col_b1, col_b2, col_b3 = st.columns(3)

        def _run_monitoring(profile_ids=None, source_codes=None):
            from monitor import run_monitoring
            with st.spinner("Выполняется мониторинг..."):
                result = run_monitoring(
                    profile_ids=profile_ids or None,
                    source_codes=source_codes or None,
                )
            return result

        profile_id_map = {p["name"]: p["id"] for p in active_profiles}

        with col_b1:
            if st.button("🔍 Проверить всё", type="primary", use_container_width=True):
                pids = [profile_id_map[n] for n in selected_profiles_names] if selected_profiles_names else None
                srcs = selected_sources if selected_sources else None
                res = _run_monitoring(pids, srcs)
                if res["errors"]:
                    for err in res["errors"]:
                        st.error(f"Ошибка [{err['source']}]: {err['error']}")
                else:
                    st.success(f"Проверка завершена. Найдено: {res['total_found']}, новых: {res['total_new']}.")

        with col_b2:
            if st.button("🏛️ Проверить реестр KZ", use_container_width=True):
                pids = [profile_id_map[n] for n in selected_profiles_names] if selected_profiles_names else None
                res = _run_monitoring(pids, ["kz_registry"])
                if res["errors"]:
                    st.error(res["errors"][0]["error"])
                else:
                    st.success(f"Реестр KZ: найдено {res['total_found']}, новых {res['total_new']}.")

        with col_b3:
            if st.button("📰 Проверить бюллетень KZ", use_container_width=True):
                pids = [profile_id_map[n] for n in selected_profiles_names] if selected_profiles_names else None
                res = _run_monitoring(pids, ["kz_bulletin"])
                if res["errors"]:
                    st.error(res["errors"][0]["error"])
                else:
                    st.success(f"Бюллетень KZ: найдено {res['total_found']}, новых {res['total_new']}.")

        st.markdown("---")
        st.info(
            "📌 Если сайт Kazpatent временно недоступен или вернул ошибку, "
            "проверка завершается с сообщением об ошибке — данные не теряются. "
            "Запустите проверку повторно позже."
        )


# ─── РЕЗУЛЬТАТЫ ──────────────────────────────────────────────────────────────

elif page == "📊 Результаты":
    st.title("Результаты мониторинга")

    # ── Фильтры ──
    with st.expander("🔽 Фильтры", expanded=True):
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            f_source = st.selectbox(
                "Источник",
                [""] + list(SOURCE_LABELS.keys()),
                format_func=lambda x: "Все источники" if x == "" else SOURCE_LABELS.get(x, x),
            )
            f_object = st.selectbox(
                "Тип объекта",
                [""] + list(OBJECT_TYPE_LABELS.keys()),
                format_func=lambda x: "Все типы" if x == "" else OBJECT_TYPE_LABELS.get(x, x),
            )
        with fc2:
            f_risk = st.selectbox(
                "Риск",
                [""] + list(RISK_LABELS.keys()),
                format_func=lambda x: "Все уровни" if x == "" else RISK_LABELS.get(x, x),
            )
            f_legal = st.selectbox(
                "Статус проверки",
                [""] + list(LEGAL_STATUS_LABELS.keys()),
                format_func=lambda x: "Все" if x == "" else LEGAL_STATUS_LABELS.get(x, x),
            )
        with fc3:
            f_owner = st.text_input("Правообладатель содержит")
            profiles = get_profiles()
            profile_map = {"": "Все профили"}
            profile_map.update({str(p["id"]): p["name"] for p in profiles})
            f_profile = st.selectbox("Профиль", list(profile_map.keys()), format_func=lambda x: profile_map[x])
        with fc4:
            f_in_report = st.selectbox("В отчёт", ["", "yes", "no"], format_func=lambda x: {
                "": "Все", "yes": "Да", "no": "Нет"
            }.get(x, x))
            f_contestable = st.checkbox(
                "⚖️ Только оспариваемые",
                help="Показать знаки, по которым срок оспаривания (5 лет) ещё не истёк",
            )

    filters = {}
    if f_source:
        filters["source"] = f_source
    if f_object:
        filters["object_type"] = f_object
    if f_risk:
        filters["risk_level"] = f_risk
    if f_legal:
        filters["legal_status"] = f_legal
    if f_owner:
        filters["owner_contains"] = f_owner
    if f_profile:
        filters["profile_id"] = int(f_profile)
    if f_in_report == "yes":
        filters["include_in_report"] = True
    elif f_in_report == "no":
        filters["include_in_report"] = False

    marks = get_marks(filters)

    # ── Кнопка ручного добавления ────────────────────────────────────────────
    with st.expander("➕ Добавить знак вручную (из реестра / НИИС)", expanded=False):
        st.caption("Используйте для добавления знаков, найденных самостоятельно в реестре НИИС, WIPO или других источниках.")
        with st.form("manual_add_mark"):
            mc1, mc2 = st.columns(2)
            with mc1:
                m_designation = st.text_input("Обозначение *", placeholder="СЕРГЕК AQTOBE")
                m_reg_num = st.text_input("№ регистрации", placeholder="85439")
                m_reg_date = st.text_input("Дата регистрации", placeholder="15.08.2023")
                m_app_date = st.text_input("Дата подачи заявки", placeholder="12.01.2023")
                m_owner = st.text_input("Правообладатель", placeholder="ТОО «Сергек Медиа»")
            with mc2:
                m_owner_addr = st.text_input("Адрес правообладателя", placeholder="г. Актобе")
                m_classes = st.text_input("Классы МКТУ", placeholder="35, 38, 41")
                m_goods = st.text_area("Товары/услуги", height=68, placeholder="реклама; маркетинг; передача новостей")
                m_source = st.selectbox("Источник", options=["kz_registry", "kz_bulletin", "wipo", "madrid", "manual"],
                                        format_func=lambda x: SOURCE_LABELS.get(x, "Вручную" if x == "manual" else x))
                m_url = st.text_input("Ссылка на источник", placeholder="https://tirek.kz/...")
            mc3, mc4 = st.columns(2)
            with mc3:
                _profiles_list = get_profiles()
                _prof_map = {str(p["id"]): p["name"] for p in _profiles_list}
                m_profile = st.selectbox("Профиль мониторинга", options=[""] + list(_prof_map.keys()),
                                         format_func=lambda x: "— не привязывать —" if x == "" else _prof_map.get(x, x))
                m_risk = st.selectbox("Степень риска", options=list(RISK_LABELS.keys()),
                                      format_func=lambda x: RISK_LABELS.get(x, x), index=2)
            with mc4:
                m_object_type = st.selectbox("Тип объекта", options=list(OBJECT_TYPE_LABELS.keys()),
                                             format_func=lambda x: OBJECT_TYPE_LABELS.get(x, x))
                m_reason = st.text_input("Причина добавления", placeholder="Фирменное наименование, сходное до степени смешения")

            if st.form_submit_button("💾 Добавить знак", type="primary"):
                if not m_designation:
                    st.error("Укажите обозначение.")
                else:
                    with get_connection() as conn:
                        cur2 = conn.execute(
                            """INSERT INTO found_marks
                               (profile_id, source_code, designation, object_type,
                                registration_number, registration_date, application_date,
                                owner, owner_address, goods_services, source_url,
                                match_reason, risk_level, legal_status, include_in_report)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'not_reviewed',1)""",
                            (
                                int(m_profile) if m_profile else None,
                                m_source,
                                m_designation,
                                m_object_type,
                                m_reg_num or None,
                                m_reg_date or None,
                                m_app_date or None,
                                m_owner or None,
                                m_owner_addr or None,
                                m_goods or None,
                                m_url or None,
                                m_reason or "Добавлено вручную",
                                m_risk,
                            ),
                        )
                        new_id = cur2.lastrowid
                        if new_id is None:
                            row = conn.execute(
                                "SELECT id FROM found_marks WHERE designation=? ORDER BY id DESC LIMIT 1",
                                (m_designation,)
                            ).fetchone()
                            new_id = row[0] if row else None
                        # Классы МКТУ
                        if new_id and m_classes:
                            for cls in m_classes.replace(" ", "").split(","):
                                try:
                                    conn.execute("INSERT INTO mark_classes (mark_id, nice_class) VALUES (?,?)",
                                                 (new_id, int(cls)))
                                except Exception:
                                    pass
                        conn.commit()
                    st.success(f"Знак «{m_designation}» добавлен.")
                    st.rerun()

    # Фильтр «Только оспариваемые» — применяется на стороне Python
    if f_contestable:
        marks = [m for m in marks
                 if calc_contestation(m["registration_date"])["status"] in ("open", "urgent")]

    # Счётчики срочных к оспариванию
    urgent_count = sum(1 for m in marks
                       if calc_contestation(m["registration_date"])["status"] == "urgent")
    if urgent_count:
        st.warning(f"⚠️ **{urgent_count} знак(ов)** — срок оспаривания истекает менее чем через 6 месяцев!")

    st.markdown(f"**Найдено записей:** {len(marks)}")

    if not marks:
        st.info("Нет записей, соответствующих фильтрам. Запустите проверку в разделе «Запуск проверки».")
    else:
        # Таблица
        rows = []
        for m in marks:
            ct = calc_contestation(m["registration_date"])
            rows.append({
                "ID": m["id"],
                "Риск": RISK_BADGE.get(m["risk_level"], m["risk_level"] or "—"),
                "Обозначение": m["designation"],
                "Тип": OBJECT_TYPE_LABELS.get(m["object_type"], m["object_type"] or "—"),
                "Источник": SOURCE_LABELS.get(m["source_code"], m["source_code"] or "—"),
                "№ рег.": m["registration_number"] or "—",
                "Дата рег.": fmt_date(m["registration_date"]),
                "Срок оспаривания": ct["label"],
                "Классы МКТУ": m["nice_classes_str"] or "—",
                "Правообладатель": m["owner"] or "—",
                "Статус знака": STATUS_LABELS.get(m["status_mark"], m["status_mark"] or "—"),
                "Статус проверки": LEGAL_STATUS_LABELS.get(m["legal_status"], m["legal_status"] or "—"),
                "В отчёт": "✅" if m["include_in_report"] else "❌",
                "Профиль": m["profile_name"] or "—",
            })

        df = pd.DataFrame(rows)
        selected = st.dataframe(
            df.drop(columns=["ID"]),
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="marks_table",
        )

        # Карточка знака при выборе строки
        sel_rows = selected.selection.rows if selected.selection else []
        if sel_rows:
            mark_id = rows[sel_rows[0]]["ID"]
            _show_mark_card(mark_id)


def _show_mark_card(mark_id: int):
    mark = get_mark_by_id(mark_id)
    if not mark:
        return

    st.markdown("---")
    st.markdown(f"## 📄 Карточка знака: **{mark['designation']}**")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.write(f"**Источник:** {SOURCE_LABELS.get(mark['source_code'], mark['source_code'])}")
        st.write(f"**Тип объекта:** {OBJECT_TYPE_LABELS.get(mark['object_type'], mark['object_type'])}")
        st.write(f"**Статус знака:** {STATUS_LABELS.get(mark['status_mark'], mark['status_mark'])}")
        st.write(f"**№ заявки:** {mark['application_number'] or '—'}")
        st.write(f"**№ регистрации:** {mark['registration_number'] or '—'}")
    with col2:
        st.write(f"**Правообладатель:** {mark['owner'] or '—'}")
        st.write(f"**Адрес:** {mark['owner_address'] or '—'}")
        st.write(f"**Классы МКТУ:** {mark['nice_classes_str'] or '—'}")
        st.write(f"**Дата заявки:** {fmt_date(mark['application_date'])}")
        st.write(f"**Дата регистрации:** {fmt_date(mark['registration_date'])}")
        st.write(f"**Дата публикации:** {fmt_date(mark['publication_date'])}")
    with col3:
        risk_label = RISK_BADGE.get(mark["risk_level"], mark["risk_level"])
        st.write(f"**Предварительный риск:** {risk_label}")
        st.write(f"**Причина совпадения:** {mark['match_reason'] or '—'}")
        st.write(f"**Первая фиксация:** {fmt_date(mark['first_found_at'])}")
        st.write(f"**Последняя проверка:** {fmt_date(mark['last_checked_at'])}")
        if mark["source_url"]:
            st.write(f"**Ссылка:** [{mark['source_url']}]({mark['source_url']})")

    if mark["goods_services"]:
        st.write(f"**Товары/услуги:** {mark['goods_services']}")

    # ── Срок оспаривания ──────────────────────────────────────────────────────
    ct = calc_contestation(mark["registration_date"])
    if ct["status"] != "unknown":
        color_map = {"open": "#16a34a", "urgent": "#d97706", "expired": "#dc2626"}
        bg_map    = {"open": "#f0fdf4", "urgent": "#fffbeb", "expired": "#fef2f2"}
        border_map = {"open": "#bbf7d0", "urgent": "#fde68a", "expired": "#fecaca"}
        color  = color_map.get(ct["status"], "#64748b")
        bg     = bg_map.get(ct["status"], "#f8fafc")
        border = border_map.get(ct["status"], "#e2e8f0")

        if ct["status"] == "expired":
            verdict = "Срок оспаривания истёк — аннулирование через суд затруднено"
        elif ct["status"] == "urgent":
            verdict = f"⚠️ Срочно! Осталось {ct['days_left']} дней — необходимо подать возражение"
        else:
            verdict = f"Можно подать возражение в НИИС до {ct['deadline']}"

        st.markdown(f"""
        <div style="border:1px solid {border};border-radius:10px;background:{bg};
                    padding:14px 18px;margin:12px 0;">
            <div style="font-size:13px;color:#64748b;margin-bottom:4px;font-weight:600;
                        text-transform:uppercase;letter-spacing:0.5px;">
                ⚖️ Срок оспаривания (5 лет с даты регистрации)
            </div>
            <div style="font-size:20px;font-weight:700;color:{color};">
                {ct['label']} &nbsp;·&nbsp;
                <span style="font-size:14px;font-weight:400;">до {ct['deadline']}</span>
            </div>
            <div style="font-size:13px;color:#475569;margin-top:4px;">{verdict}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("### ⚖️ Юридическая оценка")
    with st.form(f"legal_form_{mark_id}"):
        lc1, lc2, lc3 = st.columns(3)
        with lc1:
            new_risk = st.selectbox(
                "Степень риска",
                options=list(RISK_LABELS.keys()),
                index=list(RISK_LABELS.keys()).index(mark["risk_level"]) if mark["risk_level"] in RISK_LABELS else 0,
                format_func=lambda x: RISK_LABELS.get(x, x),
            )
            new_legal_status = st.selectbox(
                "Статус проверки",
                options=list(LEGAL_STATUS_LABELS.keys()),
                index=list(LEGAL_STATUS_LABELS.keys()).index(mark["legal_status"]) if mark["legal_status"] in LEGAL_STATUS_LABELS else 0,
                format_func=lambda x: LEGAL_STATUS_LABELS.get(x, x),
            )
        with lc2:
            new_action = st.selectbox(
                "Рекомендуемое действие",
                options=["watch", "investigate", "prepare_position", "archive"],
                index=["watch", "investigate", "prepare_position", "archive"].index(mark["recommended_action"] or "watch"),
                format_func=lambda x: {
                    "watch": "Наблюдать",
                    "investigate": "Проверить подробнее",
                    "prepare_position": "Подготовить позицию",
                    "archive": "Архив",
                }.get(x, x),
            )
            new_include = st.checkbox("Включить в отчёт", value=bool(mark["include_in_report"]))
        with lc3:
            new_recheck = st.checkbox("Требуется повторная проверка", value=bool(mark["recheck_needed"]))
            new_comment = st.text_area("Комментарий юриста", value=mark["lawyer_comment"] or "", height=100)

        if st.form_submit_button("💾 Сохранить оценку", type="primary"):
            update_mark(
                mark_id,
                risk_level=new_risk,
                legal_status=new_legal_status,
                recommended_action=new_action,
                include_in_report=1 if new_include else 0,
                recheck_needed=1 if new_recheck else 0,
                lawyer_comment=new_comment,
            )
            st.success("Оценка сохранена.")
            st.rerun()


# Регистрируем функцию глобально для таблицы результатов
if page == "📊 Результаты":
    pass  # функция _show_mark_card уже определена выше


# ─── БЮЛЛЕТЕНЬ ───────────────────────────────────────────────────────────────

elif page == "📰 Бюллетень Kazpatent":
    st.title("Электронный бюллетень Kazpatent")
    st.markdown("Поиск публикаций по дате и ключевым словам в официальном бюллетене.")
    st.info(
        "📌 **Бюллетень vs Реестр:** Бюллетень содержит только **новые** регистрации за конкретный год. "
        "Уже зарегистрированные знаки (например, SERGEK) там не повторяются — они есть только в **Реестре**. "
        "Бюллетень полезен для мониторинга **новых** конкурентных заявок."
    )

    tab_search, tab_browse = st.tabs(["🔍 Поиск", "📅 Обзор выпусков"])

    with tab_search:
        with st.form("bulletin_search"):
            col1, col2, col3 = st.columns(3)
            with col1:
                b_year = st.number_input("Год", min_value=2018, max_value=datetime.now().year, value=datetime.now().year)
                b_date = st.text_input("Дата публикации (ДД.ММ.ГГГГ)", placeholder="18.06.2026")
            with col2:
                b_keywords_raw = st.text_area(
                    "Ключевые слова (каждое с новой строки)",
                    placeholder="SERGEK\nСЕРГЕК\nтоварный знак",
                    height=100,
                )
            with col3:
                b_issue = st.text_input("Номер выпуска (если известен)", placeholder="11")
                st.markdown("**Подсказка:** оставьте пустым — найдёт во всех выпусках года")

            b_submitted = st.form_submit_button("🔍 Найти в бюллетене", type="primary")

        if b_submitted:
            keywords = [k.strip() for k in b_keywords_raw.splitlines() if k.strip()]
            if not keywords:
                st.warning("Введите хотя бы одно ключевое слово.")
            else:
                with st.spinner(f"Поиск в бюллетене за {b_year}... Это может занять несколько минут."):
                    try:
                        from scraper_bulletin import search_bulletin as search_bulletin_new, get_issue_dates
                        # Показываем сколько выпусков будем проверять
                        issues_map = get_issue_dates(int(b_year))
                        if not issues_map:
                            st.warning(f"Нет данных о выпусках бюллетеня за {b_year} г. Попробуйте другой год.")
                        else:
                            issue_count = 1 if b_issue else len(issues_map)
                            st.caption(f"Проверяю {issue_count} выпуск(ов) бюллетеня за {b_year} г...")
                            results = search_bulletin_new(
                                year=int(b_year),
                                keywords=keywords,
                                issue_num=b_issue or None,
                            )
                            if results:
                                st.success(f"Найдено публикаций: {len(results)}")
                                for r in results:
                                    render_bulletin_record(r)
                            else:
                                st.info(
                                    f"По ключевым словам {keywords} за {b_year} г. публикаций не найдено.\n\n"
                                    f"ℹ️ Бюллетень содержит только **новые** публикации года. "
                                    f"Для поиска по всем зарегистрированным знакам используйте раздел **«Реестр Kazpatent»**."
                                )
                    except Exception as e:
                        st.error(f"Ошибка: {e}")

    with tab_browse:
        st.markdown("### Прямые ссылки на выпуски бюллетеня")
        current_year = datetime.now().year
        cols = st.columns(4)
        for i, year in enumerate(range(2018, current_year + 1)):
            with cols[i % 4]:
                url = f"http://ebulletin.kazpatent.kz/#/home?targetYear={year}"
                st.markdown(f"[📅 Бюллетень {year}]({url})")

        st.markdown("---")
        st.info(
            "💡 Для поиска в конкретном выпуске: укажите год и ключевые слова выше. "
            "Или нажмите на ссылку выпуска — откроется официальный сайт бюллетеня."
        )


# ─── МОНИТОРИНГ ЗАКОНОДАТЕЛЬСТВА ─────────────────────────────────────────────

elif page == "⚖️ Мониторинг законодательства":
    st.title("Мониторинг изменений законодательства в сфере ИС")

    creds = credentials_configured()
    if not creds["paragraph"]:
        st.warning(
            "Параграф не настроен. Перейдите в **Настройки → Учётные данные** и введите логин/пароль Параграфа. "
            "Без этого будет использоваться открытый источник — база Adilet (adilet.zan.kz)."
        )

    tab_monitor, tab_docs = st.tabs(["🔄 Проверить изменения", "📋 Найденные документы"])

    with tab_monitor:
        col1, col2 = st.columns(2)
        with col1:
            use_ai = st.checkbox("Анализировать через Gemini AI", value=creds["gemini"])
            if not creds["gemini"] and use_ai:
                st.warning("Gemini API не настроен. Будет использован анализ по ключевым словам.")
        with col2:
            source_choice = st.selectbox(
                "Источник",
                ["Параграф + Adilet", "Только Adilet (открытый)"],
            )

        if st.button("⚖️ Проверить изменения законодательства", type="primary"):
            with st.spinner("Проверяем изменения в законодательстве об ИС..."):
                try:
                    from scraper_paragraph import monitor_legislation_changes, save_docs_cache, get_cached_docs
                    use_adilet_fallback = True
                    docs = monitor_legislation_changes(use_adilet_fallback=use_adilet_fallback)

                    if docs:
                        save_docs_cache(docs)
                        new_docs = [d for d in docs if d.get("is_new")]

                        if new_docs:
                            st.success(f"Найдено новых документов/изменений: {len(new_docs)}")
                        else:
                            st.info("Новых изменений не обнаружено.")

                        if use_ai and creds["gemini"]:
                            st.markdown("### AI-анализ найденных документов")
                            from ai_analyzer import analyze_legal_document
                            for doc in new_docs[:5]:
                                with st.spinner(f"Анализирую: {doc['title'][:50]}..."):
                                    analysis = analyze_legal_document(doc["title"])
                                    if analysis.get("is_ip_relevant"):
                                        st.markdown(f"**{doc['title']}**")
                                        risk_icon = {"высокий": "🔴", "средний": "🟠", "низкий": "🟢"}.get(analysis.get("risk_level", ""), "🔵")
                                        st.write(f"{risk_icon} **Риск:** {analysis.get('risk_level', '—')}")
                                        st.write(f"**Сферы ИС:** {', '.join(analysis.get('ip_areas', []))}")
                                        st.write(f"**Резюме:** {analysis.get('summary', '—')}")
                                        st.write(f"**Действие:** {analysis.get('action_needed', '—')}")
                                        if doc.get("url"):
                                            st.write(f"[Открыть документ]({doc['url']})")
                                        st.divider()
                    else:
                        st.info("Документов не найдено. Проверьте подключение к интернету.")
                except Exception as e:
                    st.error(f"Ошибка: {e}")

    with tab_docs:
        from scraper_paragraph import get_cached_docs
        cached = get_cached_docs()
        if not cached:
            st.info("Нет кэшированных документов. Нажмите «Проверить изменения законодательства».")
        else:
            new_only = st.checkbox("Только новые", value=True)
            docs_to_show = [d for d in cached if d.get("is_new")] if new_only else cached
            st.write(f"Документов: {len(docs_to_show)}")
            for doc in docs_to_show[:50]:
                new_badge = "🆕 " if doc.get("is_new") else ""
                with st.expander(f"{new_badge}{doc['title'][:80]}"):
                    st.write(f"**Источник:** {doc.get('source', '—')}")
                    st.write(f"**Ключевое слово:** {doc.get('keyword', '—')}")
                    st.write(f"**Найдено:** {doc.get('found_at', '—')}")
                    if doc.get("url"):
                        st.write(f"[Открыть документ]({doc['url']})")


# ─── ПРАВОВАЯ БАЗА ────────────────────────────────────────────────────────────

elif page == "📚 Правовая база":
    st.markdown("""
    <div style="margin-bottom:16px;">
        <div style="font-size:22px;font-weight:700;color:#0F172A;">Правовая база</div>
        <div style="font-size:13px;color:#64748B;margin-top:3px;">
            Законодательство Казахстана в сфере ИС · актуальность · понятия · процедуры
        </div>
    </div>
    """, unsafe_allow_html=True)

    from legal_base import (
        get_legal_acts_list, get_all_concepts, search_legal_base,
        LEGAL_ACTS, CONCEPTS
    )

    tab_search, tab_core, tab_actual, tab_codes, tab_ip, tab_intl, tab_sub, tab_concepts, tab_download = st.tabs([
        "🔍 Поиск",
        "📂 Основные документы",
        "🔄 Актуальность",
        "📋 Кодексная база",
        "⚖️ Законы ИС",
        "🌐 Международные договоры",
        "📜 Подзаконные акты",
        "📖 Понятия и процедуры",
        "📥 Скачать законы",
    ])

    with tab_search:
        lb_query = st.text_input("Поиск по правовой базе", placeholder="возражение, сходство, Мадрид, срок охраны, ОКУП...")
        if lb_query:
            results = search_legal_base(lb_query)
            if results:
                st.write(f"Найдено: {len(results)}")
                for r in results:
                    if r["type"] == "act":
                        with st.expander(f"📄 {r['title']}"):
                            st.write(f"**Год:** {r.get('year', '—')} | **Реквизиты:** {r.get('number', '—')}")
                            if r.get("url"):
                                st.link_button("Открыть на Adilet", r["url"])
                    elif r["type"] == "article":
                        with st.expander(f"📌 {r['article']}: {r['title']}"):
                            st.markdown(r["content"])
                            st.caption(f"Источник: {r['act_title']}")
                    elif r["type"] == "concept":
                        with st.expander(f"💡 {r['title']}"):
                            st.markdown(r["content"])
            else:
                st.info("Ничего не найдено. Попробуйте другой запрос.")

    with tab_core:
        # Документы сгруппированы по категории
        CORE_DOCS_BY_CAT = {
            "Законы Республики Казахстан": [
                ("Закон_о_товарных_знаках.docx",
                 "Закон РК «О товарных знаках, знаках обслуживания и НМПТ»",
                 "1999"),
                ("Закон_об_авторском_праве.docx",
                 "Закон РК «Об авторском праве и смежных правах»",
                 "1996"),
            ],
            "Кодексы": [
                ("ГК_РК_Общая_часть.docx",
                 "Гражданский кодекс РК — Общая часть",
                 "1994"),
                ("ГК_РК_Особенная_часть.docx",
                 "Гражданский кодекс РК — Особенная часть",
                 "1999"),
            ],
            "Нормативные постановления": [
                ("НП_ВС_РК_2007_N11_авторское_право.docx",
                 "НП ВС РК № 11 «О применении судами законодательства об авторском праве»",
                 "2007"),
            ],
            "Международные договоры": [
                ("Бернская_конвенция.docx",
                 "Бернская конвенция об охране лит. и худ. произведений",
                 "1971"),
                ("ТРИПС.docx",
                 "Соглашение ТРИПС — торговые аспекты прав ИС",
                 "1994"),
                ("ЕАЭС_Приложение26_ИС.docx",
                 "ЕАЭС Приложение № 26 — Протокол об охране прав ИС",
                 "2014"),
                ("Всемирная_конвенция_авторское_право_1952.docx",
                 "Всемирная конвенция об авторском праве",
                 "1952"),
                ("ВОИС_WCT.docx",
                 "Договор ВОИС по авторскому праву (WCT)",
                 "1996"),
            ],
        }

        _core_dir = Path(__file__).parent.parent / "laws" / "core_docs"

        def _extract_docx_text(path: Path) -> list[str]:
            """Возвращает список абзацев документа."""
            try:
                from docx import Document as _DocxDoc
                doc = _DocxDoc(str(path))
                return [p.text for p in doc.paragraphs if p.text.strip()]
            except Exception as e:
                return [f"Ошибка чтения файла: {e}"]

        def _fmt_size(path: Path) -> str:
            kb = path.stat().st_size / 1024
            return f"{kb:.0f} КБ" if kb < 1024 else f"{kb/1024:.1f} МБ"

        # Текущий открытый документ
        if "core_doc_open" not in st.session_state:
            st.session_state.core_doc_open = None

        # ── Список документов ─────────────────────────────────────────────────
        for cat, docs in CORE_DOCS_BY_CAT.items():
            st.markdown(
                f'<div style="font-size:11px;font-weight:700;letter-spacing:1px;'
                f'text-transform:uppercase;color:#94A3B8;margin:16px 0 6px;">{cat}</div>',
                unsafe_allow_html=True,
            )
            for fname, title, year in docs:
                fpath = _core_dir / fname
                exists = fpath.exists()
                is_open = st.session_state.core_doc_open == fname

                # Подсветка открытого документа
                card_border = "border:1px solid #3B82F6;" if is_open else "border:1px solid #E2E8F0;"
                card_bg = "background:#F0F7FF;" if is_open else "background:white;"

                col_icon, col_info, col_year, col_size, col_btns = st.columns([0.4, 5, 1, 1, 2])

                with col_icon:
                    st.markdown(
                        f'<div style="padding-top:10px;font-size:18px;">'
                        f'{"📄" if exists else "⚠️"}</div>',
                        unsafe_allow_html=True,
                    )
                with col_info:
                    st.markdown(
                        f'<div style="padding-top:8px;font-size:14px;font-weight:500;color:#0F172A;">{title}</div>',
                        unsafe_allow_html=True,
                    )
                with col_year:
                    st.markdown(
                        f'<div style="padding-top:10px;font-size:12px;color:#94A3B8;">{year}</div>',
                        unsafe_allow_html=True,
                    )
                with col_size:
                    if exists:
                        st.markdown(
                            f'<div style="padding-top:10px;font-size:12px;color:#94A3B8;">{_fmt_size(fpath)}</div>',
                            unsafe_allow_html=True,
                        )
                with col_btns:
                    if exists:
                        bc1, bc2 = st.columns(2)
                        with bc1:
                            with open(fpath, "rb") as _f:
                                st.download_button(
                                    "⬇ Скачать",
                                    data=_f.read(),
                                    file_name=fname,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"dl_{fname}",
                                    use_container_width=True,
                                )
                        with bc2:
                            view_label = "✕ Закрыть" if is_open else "📖 Читать"
                            if st.button(view_label, key=f"view_{fname}", use_container_width=True):
                                st.session_state.core_doc_open = None if is_open else fname
                                st.rerun()

                st.markdown("<hr style='margin:2px 0;border:none;border-top:1px solid #F1F5F9;'>", unsafe_allow_html=True)

                # ── Встроенный ридер ──────────────────────────────────────────
                if is_open and exists:
                    paragraphs = _extract_docx_text(fpath)
                    # Первые строки — заголовок/шапка документа
                    header_lines = paragraphs[:6]
                    body_lines = paragraphs[6:]

                    header_html = "".join(
                        f'<p style="margin:2px 0;font-weight:600;color:#1E3A8A;">{l}</p>'
                        for l in header_lines
                    )
                    body_html = "".join(
                        f'<p style="margin:4px 0;color:#1E293B;line-height:1.6;">{l}</p>'
                        for l in body_lines
                    )

                    st.markdown(f"""
                    <div style="background:#F8FAFF;border:1px solid #BFDBFE;border-radius:10px;
                                padding:20px 24px;margin:4px 0 12px;max-height:560px;
                                overflow-y:auto;font-size:13px;font-family:Georgia,serif;">
                        <div style="margin-bottom:12px;padding-bottom:10px;
                                    border-bottom:1px solid #BFDBFE;">{header_html}</div>
                        <div>{body_html}</div>
                    </div>
                    """, unsafe_allow_html=True)

    with tab_actual:
        from actuality_checker import CORE_DOC_REGISTRY, check_doc, check_all_docs

        st.markdown("""
        <div style="background:#EFF6FF;border:1px solid #BFDBFE;border-left:4px solid #3B82F6;
                    border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px;color:#1E3A8A;">
            <strong>Мониторинг актуальности законодательства</strong><br>
            Система проверяет наличие изменений в документах по данным Adilet (adilet.zan.kz).
            Для скачивания актуальных редакций используйте вкладку «Скачать законы» (Параграф).
        </div>
        """, unsafe_allow_html=True)

        # Инициализация хранилища результатов в session_state
        if "actuality_results" not in st.session_state:
            st.session_state.actuality_results = {}

        col_act1, col_act2 = st.columns([4, 1])
        with col_act2:
            check_all = st.button("🔄 Проверить все", type="primary", use_container_width=True,
                                  help="Проверяет актуальность всех документов на Adilet (~30-60 сек)")
        with col_act1:
            st.markdown(
                '<div style="font-size:13px;color:#64748B;padding-top:8px;">'
                f'Документов в реестре: {len(CORE_DOC_REGISTRY)}</div>',
                unsafe_allow_html=True,
            )

        if check_all:
            results_list = []
            prog_bar = st.progress(0, "Проверка документов на Adilet...")
            total = len(CORE_DOC_REGISTRY)
            for i, key in enumerate(CORE_DOC_REGISTRY):
                prog_bar.progress((i + 1) / total, f"[{i+1}/{total}] {CORE_DOC_REGISTRY[key]['title'][:50]}...")
                res = check_doc(key)
                res["key"] = key
                results_list.append(res)
                st.session_state.actuality_results[key] = res
            prog_bar.empty()
            st.success(f"Проверка завершена. Обработано документов: {total}.")

        # Отображение результатов по категориям
        STATUS_PILL = {
            "current":      ('<span style="background:#DCFCE7;color:#166534;padding:2px 10px;'
                             'border-radius:12px;font-size:11px;font-weight:700;">✓ Актуален</span>'),
            "amended":      ('<span style="background:#FEF3C7;color:#92400E;padding:2px 10px;'
                             'border-radius:12px;font-size:11px;font-weight:700;">⚠ Изменён</span>'),
            "amended_new":  ('<span style="background:#FEE2E2;color:#991B1B;padding:2px 10px;'
                             'border-radius:12px;font-size:11px;font-weight:700;">🔴 Новые изменения</span>'),
            "revoked":      ('<span style="background:#F1F5F9;color:#475569;padding:2px 10px;'
                             'border-radius:12px;font-size:11px;font-weight:700;">✗ Утратил силу</span>'),
            "error":        ('<span style="background:#F1F5F9;color:#94A3B8;padding:2px 10px;'
                             'border-radius:12px;font-size:11px;font-weight:700;">— Нет данных</span>'),
        }

        CATEGORIES_ORDER = ["Законы ИС", "Кодексы", "Международные договоры", "Судебная практика", "Подзаконные акты"]

        by_cat: dict = {}
        for key, meta in CORE_DOC_REGISTRY.items():
            cat = meta["category"]
            by_cat.setdefault(cat, []).append((key, meta))

        for cat in CATEGORIES_ORDER:
            if cat not in by_cat:
                continue
            st.markdown(f"**{cat}**")
            rows_html = ""
            for key, meta in by_cat[cat]:
                cached = st.session_state.actuality_results.get(key)
                status = cached["status"] if cached else "error"
                pill = STATUS_PILL.get(status, STATUS_PILL["error"])
                last_mod = cached.get("last_modified", "—") if cached else "—"
                checked_at = cached.get("checked_at", "—") if cached else "—"
                notes = cached.get("notes") or cached.get("error", "") if cached else "Нажмите «Проверить все»"
                adilet_url = meta["adilet_url"]
                prg_id = meta.get("prg_doc_id")
                prg_link = (
                    f'<a href="https://online.prg.kz/lawyer/doc/{prg_id}" target="_blank" '
                    f'style="color:#3B82F6;font-size:11px;text-decoration:none;">Параграф ↗</a>'
                    if prg_id else ""
                )
                rows_html += f"""
                <tr>
                    <td style="padding:9px 12px;font-size:13px;color:#0F172A;border-bottom:1px solid #F1F5F9;">
                        <a href="{adilet_url}" target="_blank"
                           style="color:#0F172A;text-decoration:none;font-weight:500;">{meta['title']}</a>
                    </td>
                    <td style="padding:9px 12px;border-bottom:1px solid #F1F5F9;">{pill}</td>
                    <td style="padding:9px 12px;font-size:12px;color:#64748B;border-bottom:1px solid #F1F5F9;">{last_mod}</td>
                    <td style="padding:9px 12px;font-size:11px;color:#94A3B8;border-bottom:1px solid #F1F5F9;max-width:200px;">{notes[:80]}</td>
                    <td style="padding:9px 12px;font-size:11px;color:#94A3B8;border-bottom:1px solid #F1F5F9;">
                        <a href="{adilet_url}" target="_blank" style="color:#3B82F6;text-decoration:none;">Adilet ↗</a>
                        {'&nbsp;&nbsp;' + prg_link if prg_link else ''}
                    </td>
                </tr>"""

            st.markdown(f"""
            <div style="background:white;border:1px solid #E2E8F0;border-radius:10px;overflow:hidden;margin-bottom:16px;">
                <table style="width:100%;border-collapse:collapse;">
                    <thead>
                        <tr style="background:#F8FAFC;">
                            <th style="padding:7px 12px;text-align:left;font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:#64748B;">Документ</th>
                            <th style="padding:7px 12px;text-align:left;font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:#64748B;">Статус</th>
                            <th style="padding:7px 12px;text-align:left;font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:#64748B;">Изменён</th>
                            <th style="padding:7px 12px;text-align:left;font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:#64748B;">Примечание</th>
                            <th style="padding:7px 12px;text-align:left;font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:#64748B;">Ссылки</th>
                        </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
            """, unsafe_allow_html=True)

        if not st.session_state.actuality_results:
            st.info("Нажмите «🔄 Проверить все» для проверки актуальности документов на Adilet.")

    def _render_acts(acts):
        for act in acts:
            priority_badge = " 🔴" if act.get("priority") == "high" else ""
            with st.expander(f"📄 {act['title']} ({act['year']}){priority_badge}"):
                st.write(f"**Реквизиты:** {act['number']}")
                if act.get("url"):
                    st.link_button("Открыть на Adilet", act["url"])
                if act.get("key_articles"):
                    st.markdown("**Ключевые положения:**")
                    for art in act["key_articles"]:
                        st.markdown(f"**{art['article']} — {art['title']}**")
                        st.markdown(f"> {art['content']}")
                        st.markdown("")

    with tab_codes:
        st.markdown("### Кодексная база (12 актов)")
        st.caption("Конституция, Гражданский, Уголовный, КоАП, ГПК, АППК, Таможенный, Налоговый кодексы.")
        _render_acts(LEGAL_ACTS.get("codes", []))

    with tab_ip:
        st.markdown("### Специальные законы в сфере ИС")
        st.caption("Авторское право, товарные знаки, патент, селекция, ИМС, НИИС, наука, цифровые законы.")
        _render_acts(LEGAL_ACTS.get("ip_laws", []))

    with tab_intl:
        st.markdown("### Международные договоры (24 акта)")
        st.caption("ВОИС, Бернская, Парижская, Мадридский протокол, ТРИПС, WCT, WPPT, PCT, ЕАПК, МКТУ, Марракеш и др.")
        _render_acts(LEGAL_ACTS.get("international", []))

    with tab_sub:
        st.markdown("### Подзаконные акты")
        st.caption("Приказы МЮ РК: авторское право, промышленная собственность, передача прав, патентные поверенные.")
        _render_acts(LEGAL_ACTS.get("subordinate", []))

    with tab_concepts:
        st.markdown("### Ключевые понятия и процедуры")
        for cid, concept in CONCEPTS.items():
            with st.expander(f"💡 {concept['title']}"):
                st.markdown(concept["content"])

    with tab_download:
        st.markdown("### Скачать законы в Word")
        st.markdown(
            "Актуальные тексты законов РК по интеллектуальной собственности "
            "в формате *.docx* из системы **Параграф** и **Adilet**."
        )

        from paths import LAWS_DIR as LAWS_ROOT
        prg_dir = LAWS_ROOT / "Параграф"

        from paragraph_downloader import TARGET_LAWS as PRG_LAWS

        col_dl1, col_dl2 = st.columns([3, 1])
        with col_dl2:
            if st.button("Обновить все файлы", type="primary", use_container_width=True,
                         help="Перескачать все законы из Параграфа (требует авторизации)"):
                from paragraph_downloader import download_all as prg_download_all
                prog = st.progress(0, "Загрузка...")
                def _prog_cb(i, total, name):
                    prog.progress(i / total, f"[{i+1}/{total}] {name}...")
                summary = prg_download_all(headless=True, progress_callback=_prog_cb)
                prog.empty()
                ok = summary.get("downloaded", 0)
                err = summary.get("errors", 0)
                if ok > 0:
                    st.success(f"Скачано: {ok} файл(ов). Ошибок: {err}.")
                else:
                    st.error(f"Не удалось скачать файлы. Ошибок: {err}.")
                st.rerun()

        # Показываем список файлов по категориям
        CATEGORIES = {
            "Основные законы по ИС": [
                "Закон_о_ТЗ", "Закон_об_авторском_праве", "Патентный_закон", "Закон_о_селекции",
                "Закон_о_топологиях_ИМС", "Закон_о_НИИС",
            ],
            "Кодексы": [
                "ГК_РК_общая", "ГК_РК_особенная", "УК_РК", "КоАП_РК", "ГПК_РК",
                "Таможенный_кодекс",
            ],
            "Международные договоры": [
                "Парижская_конвенция", "Мадридское_соглашение", "Протокол_Мадрид",
                "Бернская_конвенция", "WCT_договор", "WPPT_договор",
                "Договор_PCT", "ТРИПС",
            ],
            "Подзаконные акты": ["Правила_регистрации_ТЗ", "Правила_экспертизы_ИС"],
            "Судебная практика": ["Судебная_практика_ИС"],
        }
        TITLES = {t[2]: t[0] for t in PRG_LAWS}

        for cat, fnames in CATEGORIES.items():
            st.markdown(f"**{cat}**")
            for fname in fnames:
                fpath = prg_dir / f"{fname}.docx"
                title = TITLES.get(fname, fname.replace("_", " "))
                col_a, col_b, col_c = st.columns([4, 1, 1])
                with col_a:
                    st.write(f"📄 {title}")
                with col_b:
                    if fpath.exists():
                        mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
                        st.caption(f"обновлён {mtime.strftime('%d.%m.%Y')}")
                    else:
                        st.caption("не скачан")
                with col_c:
                    if fpath.exists():
                        with open(fpath, "rb") as f:
                            st.download_button(
                                label="⬇",
                                data=f.read(),
                                file_name=f"{fname}.docx",
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                key=f"dl_{fname}",
                            )
                    else:
                        st.write("—")
            st.markdown("")


# ─── ОТЧЁТЫ ──────────────────────────────────────────────────────────────────

elif page == "📝 Отчёты":
    st.title("Формирование отчётов")

    with st.form("report_form"):
        st.markdown("### Параметры отчёта")
        report_title = st.text_input("Название отчёта", value=f"Отчёт по мониторингу ТЗ — {datetime.now().strftime('%d.%m.%Y')}")
        col1, col2 = st.columns(2)
        with col1:
            period_from = st.date_input("Период с", value=date.today().replace(day=1))
        with col2:
            period_to = st.date_input("Период по", value=date.today())

        profiles = get_profiles()
        selected_profile_ids = st.multiselect(
            "Профили (оставьте пустым — все)",
            options=[p["id"] for p in profiles],
            format_func=lambda x: next((p["name"] for p in profiles if p["id"] == x), str(x)),
        )
        selected_sources = st.multiselect(
            "Источники (оставьте пустым — все)",
            options=list(SOURCE_LABELS.keys()),
            format_func=lambda x: SOURCE_LABELS.get(x, x),
        )
        only_report = st.checkbox("Только записи с отметкой «В отчёт»", value=True)

        submitted = st.form_submit_button("📥 Сформировать Excel-отчёт", type="primary")

    if submitted:
        filters = {}
        if only_report:
            filters["include_in_report"] = True
        if selected_profile_ids:
            filters["profile_id"] = selected_profile_ids[0]
        marks_raw = get_marks(filters)
        marks = [dict(m) for m in marks_raw]

        profile_names = [p["name"] for p in profiles if not selected_profile_ids or p["id"] in selected_profile_ids]
        source_list = selected_sources or list(SOURCE_LABELS.keys())

        try:
            path = generate_report(
                marks=marks,
                title=report_title,
                period_from=str(period_from),
                period_to=str(period_to),
                profiles=profile_names,
                sources=source_list,
            )
            st.success(f"Отчёт сформирован: `{path}`")
            with open(path, "rb") as f:
                st.download_button(
                    "⬇️ Скачать отчёт",
                    data=f,
                    file_name=Path(path).name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        except Exception as e:
            st.error(f"Ошибка при формировании отчёта: {e}")


# ─── ЖУРНАЛ ПРОВЕРОК ─────────────────────────────────────────────────────────

elif page == "📖 Журнал проверок":
    st.title("Журнал проверок")

    runs = get_runs()
    if not runs:
        st.info("Проверки ещё не запускались.")
    else:
        run_data = []
        for r in runs:
            run_data.append({
                "Дата/время": fmt_date(r["started_at"]),
                "Источник": SOURCE_LABELS.get(r["source_code"], r["source_code"]),
                "Профиль": r["profile_name"] or "—",
                "Статус": "✅ Успешно" if r["status"] == "success" else ("⏳ Выполняется" if r["status"] == "running" else "❌ Ошибка"),
                "Найдено": r["found_total"] or 0,
                "Новых": r["found_new"] or 0,
                "Завершено": fmt_date(r["finished_at"]),
                "Ошибка": r["error_text"] or "—",
            })
        st.dataframe(pd.DataFrame(run_data), use_container_width=True, hide_index=True)


# ─── ВОЗРАЖЕНИЯ ──────────────────────────────────────────────────────────────

elif page == "📄 Возражения":

    try:
        from opposition_generator import (
            generate_opposition,
            generate_opposition_from_ai_text,
            extract_text_from_file,
            opposition_filename,
        )
        from ai_analyzer import generate_opposition_text
        from config_manager import get_gemini_key
        from bin_lookup import lookup_company_by_bin
    except ImportError as _ie:
        st.error(f"Не удалось загрузить модули: {_ie}")
        st.stop()

    _has_ai = bool(get_gemini_key())

    # ── session_state ────────────────────────────────────────────────────────
    if "opp_contested" not in st.session_state:
        st.session_state["opp_contested"] = [{"number": "", "name": ""}]
    if "opp_our" not in st.session_state:
        st.session_state["opp_our"] = [{"number": "", "name": ""}]
    if "opp_use_ai" not in st.session_state:
        st.session_state["opp_use_ai"] = _has_ai

    # ── Герой-блок ───────────────────────────────────────────────────────────
    st.markdown("""
    <div class="opp-hero">
        <div class="opp-hero-text">
            <h1>Генератор возражений</h1>
            <p>ИИ составит текст возражения в Апелляционный совет МЮ РК
            по данным дела. Работает для любого клиента и любых товарных знаков.</p>
        </div>
        <div class="opp-hero-art">🤖📄</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Режим работы (pill-кнопки через radio) ───────────────────────────────
    if not _has_ai:
        st.warning("Gemini API не настроен — доступен только шаблонный режим. Добавьте ключ в ⚙️ Настройки.")

    _mode_opts = ["✨ ИИ-генерация (Gemini)", "📋 Фиксированный шаблон"]
    _mode_idx  = 0 if st.session_state["opp_use_ai"] else 1
    _gen_mode  = st.radio("Режим работы", _mode_opts, index=_mode_idx,
                          horizontal=True, disabled=not _has_ai, key="opp_mode_radio")
    use_ai = _gen_mode.startswith("✨") and _has_ai
    st.session_state["opp_use_ai"] = use_ai

    # ── 2-колоночный лейаут: форма | правая панель ───────────────────────────
    _form_col, _help_col = st.columns([3, 2], gap="large")

    with _form_col:

        # ── Блок 1: Заявитель ────────────────────────────────────────────────
        st.markdown('<div class="step-header"><div class="step-num">1</div>'
                    '<div class="step-title">Заявитель (наш клиент)</div></div>',
                    unsafe_allow_html=True)

        _b1, _b2 = st.columns([4, 1])
        with _b1:
            applicant_bin = st.text_input("БИН / ИИН заявителя",
                placeholder="110340003601", key="opp_bin", label_visibility="collapsed")
        with _b2:
            _do_lookup = st.button("🔍 Найти", key="opp_bin_lookup", use_container_width=True)

        if _do_lookup and applicant_bin:
            with st.spinner("Ищем в реестрах…"):
                _found = lookup_company_by_bin(applicant_bin)
            if _found.get("name"):
                st.session_state["opp_applicant_name"]    = _found["name"]
                st.session_state["opp_applicant_address"] = _found.get("address", "")
                st.success(f"✓ {_found['name']}")
            else:
                st.warning(_found.get("error", "Не найдено") + ". Введите вручную.")

        _f1, _f2 = st.columns(2)
        with _f1:
            applicant_name = st.text_input("Наименование / ФИО",
                value=st.session_state.get("opp_applicant_name", ""),
                placeholder="ТОО «…» или Иванов И.И.", key="opp_aname")
            applicant_address = st.text_input("Юридический адрес",
                value=st.session_state.get("opp_applicant_address", ""),
                placeholder="г. Алматы, ул. …", key="opp_aaddr")
        with _f2:
            applicant_iik  = st.text_input("ИИК", placeholder="KZ…", key="opp_iik")
            applicant_bank = st.text_input("Банк", placeholder="АО «…»", key="opp_bank")
            applicant_bik  = st.text_input("БИК", placeholder="HSBKKZKX", key="opp_bik")

        # ── Блок 2: Представитель (коллапс) ─────────────────────────────────
        with st.expander("2. Представитель (если подаёт представитель)"):
            _r1, _r2 = st.columns(2)
            with _r1:
                rep_name    = st.text_input("ФИО", placeholder="Иванова А.Б.", key="opp_rname")
                rep_iin     = st.text_input("ИИН", placeholder="000000000000", key="opp_riin")
                rep_address = st.text_input("Адрес", placeholder="г. Астана, …", key="opp_raddr")
            with _r2:
                rep_phone = st.text_input("Телефон", placeholder="+7 700 000 00 00", key="opp_rphone")
                rep_email = st.text_input("E-mail", placeholder="email@example.com", key="opp_remail")

        # ── Блок 3: Оспариваемые знаки ──────────────────────────────────────
        st.markdown('<div class="step-header"><div class="step-num">3</div>'
                    '<div class="step-title">Оспариваемые товарные знаки</div></div>',
                    unsafe_allow_html=True)
        st.caption("Введите номер свидетельства и название. Нажмите ＋ для добавления.")

        # ── БИН владельца ──
        _ob1, _ob2 = st.columns([4, 1])
        with _ob1:
            owner_bin = st.text_input("БИН владельца оспариваемых знаков",
                placeholder="110340003601", key="opp_obin", label_visibility="collapsed")
        with _ob2:
            _do_owner_lookup = st.button("🔍 Найти", key="opp_obin_lookup", use_container_width=True)

        if _do_owner_lookup and owner_bin:
            with st.spinner("Ищем…"):
                _of = lookup_company_by_bin(owner_bin)
            if _of.get("name"):
                st.session_state["opp_owner_name"]    = _of["name"]
                st.session_state["opp_owner_address"] = _of.get("address", "")
                st.success(f"✓ {_of['name']}")
            else:
                st.warning(_of.get("error", "Не найдено") + ". Введите вручную.")

        _ow1, _ow2 = st.columns(2)
        with _ow1:
            owner_name = st.text_input("Наименование владельца",
                value=st.session_state.get("opp_owner_name", ""),
                placeholder="ТОО «…»", key="opp_oname")
        with _ow2:
            owner_address = st.text_input("Адрес владельца",
                value=st.session_state.get("opp_owner_address", ""),
                placeholder="г. …", key="opp_oaddr")

        # Динамический список оспариваемых знаков
        _contested_to_remove = None
        for _ci, _cm in enumerate(st.session_state["opp_contested"]):
            _cc1, _cc2, _cc3 = st.columns([2, 4, 1])
            with _cc1:
                st.session_state["opp_contested"][_ci]["number"] = st.text_input(
                    "№", value=_cm["number"], placeholder="85439", key=f"cm_num_{_ci}")
            with _cc2:
                st.session_state["opp_contested"][_ci]["name"] = st.text_input(
                    "Название / обозначение", value=_cm["name"],
                    placeholder="SERGEK PRO", key=f"cm_name_{_ci}")
            with _cc3:
                st.write("")
                if st.button("✕", key=f"cm_del_{_ci}") and len(st.session_state["opp_contested"]) > 1:
                    _contested_to_remove = _ci

        if _contested_to_remove is not None:
            st.session_state["opp_contested"].pop(_contested_to_remove)
            st.rerun()

        st.markdown('<div class="inline-add-btn">', unsafe_allow_html=True)
        if st.button("＋  Добавить оспариваемый знак", key="cm_add"):
            st.session_state["opp_contested"].append({"number": "", "name": ""})
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        contested_marks = [
            {"name": m["name"], "number": m["number"],
             "app_number": "", "priority_date": "", "reg_date": "",
             "expiry_date": "", "classes": []}
            for m in st.session_state["opp_contested"]
        ]

        # ── Блок 4: Наши знаки ───────────────────────────────────────────────
        st.markdown('<div class="step-header"><div class="step-num">4</div>'
                    '<div class="step-title">Наши товарные знаки (более ранние права)</div></div>',
                    unsafe_allow_html=True)
        st.caption("Номер свидетельства + название. Нажмите ＋ для добавления.")

        _our_to_remove = None
        for _oi, _om in enumerate(st.session_state["opp_our"]):
            _oc1, _oc2, _oc3 = st.columns([2, 4, 1])
            with _oc1:
                st.session_state["opp_our"][_oi]["number"] = st.text_input(
                    "№", value=_om["number"], placeholder="56289", key=f"om_num_{_oi}")
            with _oc2:
                st.session_state["opp_our"][_oi]["name"] = st.text_input(
                    "Название / обозначение", value=_om["name"],
                    placeholder="«СЕРГЕК»", key=f"om_name_{_oi}")
            with _oc3:
                st.write("")
                if st.button("✕", key=f"om_del_{_oi}") and len(st.session_state["opp_our"]) > 1:
                    _our_to_remove = _oi

        if _our_to_remove is not None:
            st.session_state["opp_our"].pop(_our_to_remove)
            st.rerun()

        st.markdown('<div class="inline-add-btn">', unsafe_allow_html=True)
        if st.button("＋  Добавить наш знак", key="om_add"):
            st.session_state["opp_our"].append({"number": "", "name": ""})
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        our_marks = [
            {"name": m["name"], "number": m["number"],
             "priority_date": "", "reg_date": "", "expiry_date": "", "classes": []}
            for m in st.session_state["opp_our"]
        ]

        # ── Блок 5: Материалы дела ───────────────────────────────────────────
        st.markdown('<div class="step-header"><div class="step-num">5</div>'
                    '<div class="step-title">Материалы дела</div></div>',
                    unsafe_allow_html=True)

        uploaded_files = st.file_uploader(
            "Загрузите документы: свидетельства, выписки, договоры, примеры возражений",
            type=["docx", "pdf", "xlsx", "xls"],
            accept_multiple_files=True,
            key="opp_uploads",
        )
        reference_text = ""
        if uploaded_files:
            _parts = []
            for _uf in uploaded_files:
                _txt = extract_text_from_file(_uf.read(), _uf.name)
                if _txt:
                    _parts.append(f"[{_uf.name}]\n{_txt[:4000]}")
            if _parts:
                reference_text = "\n\n".join(_parts)
                st.success(f"Текст извлечён из {len(_parts)} файл(ов) — ИИ учтёт при составлении.")

        extra_context = st.text_area(
            "Дополнительные факты и аргументы для ИИ",
            placeholder=(
                "История использования знака, сфера деятельности, "
                "факты недобросовестности ответчика, результаты маркетинговых "
                "исследований, судебная практика, иные обстоятельства…"
            ),
            height=110,
            key="opp_extra",
        )

    # ── Правая панель ────────────────────────────────────────────────────────
    with _help_col:
        st.markdown("""
        <div class="help-card">
            <div class="help-card-title">Как это работает?</div>
            <div class="help-step">
                <div class="help-step-num">1</div>
                <div>Заполните данные о заявителе — введите БИН и нажмите 🔍, реквизиты подтянутся автоматически</div>
            </div>
            <div class="help-step">
                <div class="help-step-num">2</div>
                <div>Укажите информацию об оспариваемых товарных знаках (номер + название) и ваших более ранних знаках</div>
            </div>
            <div class="help-step">
                <div class="help-step-num">3</div>
                <div>При желании загрузите документы (.docx, .pdf, .xlsx) — ИИ учтёт их как контекст</div>
            </div>
            <div class="help-step">
                <div class="help-step-num">4</div>
                <div>Нажмите «Сгенерировать возражение» — ИИ подготовит текст за 20–40 секунд</div>
            </div>
        </div>

        <div class="help-card">
            <div class="help-card-title">Советы</div>
            <div class="tip-row">
                <div class="tip-icon">☆</div>
                <div>Указывайте максимально полные данные для лучшего результата</div>
            </div>
            <div class="tip-row">
                <div class="tip-icon">🛡️</div>
                <div>Проверьте данные перед генерацией документа</div>
            </div>
            <div class="tip-row">
                <div class="tip-icon">✏️</div>
                <div>Вы можете редактировать сгенерированный текст перед скачиванием</div>
            </div>
            <div class="tip-row">
                <div class="tip-icon">📎</div>
                <div>Загрузите примеры прошлых возражений — ИИ возьмёт стиль и структуру</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Кнопка генерации в правой панели (sticky) ────────────────────────
        st.markdown('<div class="gen-btn-wrap">', unsafe_allow_html=True)

        _btn_lbl = "✨  Сгенерировать возражение" if use_ai else "📋  Сформировать по шаблону"
        _do_gen  = st.button(_btn_lbl, type="primary", use_container_width=True, key="opp_gen_btn")
        st.markdown(
            '<div class="gen-btn-sub">ИИ подготовит текст документа за несколько секунд</div>'
            if use_ai else
            '<div class="gen-btn-sub">Создаст стандартный документ по шаблону</div>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Обработка нажатия ────────────────────────────────────────────────────
    applicant_name_val = st.session_state.get("opp_aname", "")
    if _do_gen:
        _an = applicant_name if "applicant_name" in dir() else ""
        if not _an:
            st.error("Укажите наименование заявителя (Блок 1).")
        elif not any(m["name"] or m["number"] for m in contested_marks):
            st.error("Заполните хотя бы один оспариваемый знак (Блок 3).")
        else:
            case_data = {
                "applicant_name":    applicant_name,
                "applicant_bin":     applicant_bin,
                "applicant_address": applicant_address,
                "applicant_iik":     applicant_iik,
                "applicant_bank":    applicant_bank,
                "applicant_bik":     applicant_bik,
                "rep_name":          rep_name    if "rep_name"    in dir() else "",
                "rep_iin":           rep_iin     if "rep_iin"     in dir() else "",
                "rep_address":       rep_address if "rep_address" in dir() else "",
                "rep_phone":         rep_phone   if "rep_phone"   in dir() else "",
                "rep_email":         rep_email   if "rep_email"   in dir() else "",
                "owner_name":        owner_name,
                "owner_address":     owner_address,
                "our_marks":         [m for m in our_marks if m["name"] or m["number"]],
                "contested_marks":   [m for m in contested_marks if m["name"] or m["number"]],
                "extra_context":     extra_context,
                "reference_text":    reference_text,
            }
            fname = opposition_filename(contested_marks)

            if use_ai:
                with st.spinner("ИИ составляет возражение… обычно 20–45 секунд"):
                    try:
                        _ai_text = generate_opposition_text(case_data)
                        if not _ai_text:
                            st.error("ИИ вернул пустой ответ. Проверьте Gemini API ключ в ⚙️ Настройки.")
                            st.stop()
                        st.session_state["opp_ai_text"]   = _ai_text
                        st.session_state["opp_case_data"] = case_data
                        st.session_state["opp_fname"]     = fname
                    except Exception as exc:
                        st.error(f"Ошибка ИИ: {exc}")
                        st.stop()
            else:
                with st.spinner("Формируем документ…"):
                    try:
                        _bytes = generate_opposition(
                            contested_marks=contested_marks,
                            owner={"name": owner_name, "address": owner_address},
                            our_marks=our_marks,
                            client={"name": applicant_name, "bin": applicant_bin,
                                    "address": applicant_address, "iik": applicant_iik,
                                    "bank": applicant_bank, "bik": applicant_bik},
                            representative={
                                "name":    rep_name    if "rep_name"    in dir() else "",
                                "iin":     rep_iin     if "rep_iin"     in dir() else "",
                                "address": rep_address if "rep_address" in dir() else "",
                                "phone":   rep_phone   if "rep_phone"   in dir() else "",
                                "email":   rep_email   if "rep_email"   in dir() else "",
                            },
                        )
                        st.success("Документ готов.")
                        st.download_button(
                            f"⬇️ Скачать {fname}", data=_bytes, file_name=fname,
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            use_container_width=True,
                        )
                    except Exception as exc:
                        st.error(f"Ошибка генерации: {exc}")
                        import traceback; st.code(traceback.format_exc())

    # ── Результат ИИ (редактируемый текст + скачать) ─────────────────────────
    if st.session_state.get("opp_ai_text"):
        st.markdown("---")
        st.markdown("### 📝 Текст возражения от ИИ")
        st.caption("Просмотрите и при необходимости отредактируйте. Затем скачайте .docx.")
        _edited = st.text_area(
            "Текст возражения", value=st.session_state["opp_ai_text"],
            height=600, key="opp_text_edit",
        )
        _cd  = st.session_state.get("opp_case_data", {})
        _fn  = st.session_state.get("opp_fname", "Возражение.docx")
        try:
            _docx = generate_opposition_from_ai_text(_edited or st.session_state["opp_ai_text"], _cd)
            st.download_button(
                f"⬇️ Скачать {_fn}", data=_docx, file_name=_fn,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True, type="primary",
            )
        except Exception as exc:
            st.error(f"Ошибка формирования .docx: {exc}")


# ─── НАСТРОЙКИ ───────────────────────────────────────────────────────────────

elif page == "⚙️ Настройки":
    st.markdown("""
    <div style="margin-bottom:16px;">
        <div style="font-size:22px;font-weight:700;color:#0F172A;">Настройки</div>
        <div style="font-size:13px;color:#64748B;margin-top:3px;">
            Подключения, пользователи, Supabase
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Проверка Supabase / GRANT ──────────────────────────────────────────────
    with st.expander("🗄️ Диагностика базы данных Supabase", expanded=False):
        st.markdown("""
**Если страница «Результаты» показывает ошибку**, убедитесь, что в Supabase выданы права на выполнение функций.

Откройте **Supabase → SQL Editor** и выполните следующий SQL:
        """)
        st.code("""
-- Права на выполнение RPC-функций
GRANT EXECUTE ON FUNCTION run_query(text) TO service_role;
GRANT EXECUTE ON FUNCTION run_exec(text)  TO service_role;
GRANT EXECUTE ON FUNCTION run_query(text) TO anon;
GRANT EXECUTE ON FUNCTION run_exec(text)  TO anon;

-- Права на таблицы
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
        """, language="sql")
        st.caption("После выполнения обновите страницу приложения.")

        if st.button("🔍 Проверить соединение с Supabase"):
            try:
                with get_connection() as _tc:
                    _tc.execute("SELECT 1 AS ok")
                st.success("✅ Supabase подключён успешно.")
            except Exception as _e:
                st.error(f"❌ Ошибка: {_e}")

    # ── Учётные данные ──
    st.markdown("### 🔐 Учётные данные")
    creds = credentials_configured()

    with st.expander("Параграф (online.prg.kz/lawyer)", expanded=not creds["paragraph"]):
        st.markdown("Введите логин и пароль для доступа к системе Параграф.")
        with st.form("paragraph_creds"):
            p_login = st.text_input("Логин Параграф")
            p_password = st.text_input("Пароль Параграф", type="password")
            if st.form_submit_button("💾 Сохранить данные Параграф"):
                if p_login and p_password:
                    save_credentials({"paragraph": {"url": "https://online.prg.kz/lawyer", "login": p_login, "password": p_password}})
                    st.success("Данные Параграф сохранены в config/credentials.json")
                    st.rerun()
                else:
                    st.error("Введите логин и пароль.")
        if creds["paragraph"]:
            st.success("✅ Параграф настроен")

    with st.expander("Google Gemini AI", expanded=not creds["gemini"]):
        st.markdown(
            "Введите API-ключ Gemini для AI-анализа документов и товарных знаков. "
            "Получить бесплатный ключ: [Google AI Studio](https://aistudio.google.com/apikey)"
        )
        with st.form("gemini_creds"):
            g_key = st.text_input("Gemini API Key", type="password")
            g_model = st.selectbox("Модель", ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"])
            if st.form_submit_button("💾 Сохранить Gemini API"):
                if g_key:
                    save_credentials({"gemini": {"api_key": g_key, "model": g_model}})
                    st.success("Gemini API сохранён.")
                    st.rerun()
                else:
                    st.error("Введите API-ключ.")
        if creds["gemini"]:
            st.success("✅ Gemini AI настроен")

    from telegram_notifier import is_configured as tg_is_configured, test_connection as tg_test, reload_config as tg_reload
    tg_ok = tg_is_configured()
    with st.expander("Telegram-уведомления", expanded=not tg_ok):
        st.markdown(
            "Получайте уведомления в Telegram когда мониторинг находит новые совпадения.\n\n"
            "**Инструкция:**\n"
            "1. Создайте бота через [@BotFather](https://t.me/BotFather) — получите токен\n"
            "2. Узнайте свой Telegram ID через [@userinfobot](https://t.me/userinfobot)\n"
            "3. Напишите боту `/start` (иначе он не сможет вам писать)\n"
        )
        with st.form("telegram_creds"):
            tg_token = st.text_input("Bot Token (от @BotFather)", type="password",
                                     help="Вид: 1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
            tg_chat = st.text_input("Ваш Telegram ID (от @userinfobot)",
                                    help="Числовой ID, например: 123456789")
            tg_submitted = st.form_submit_button("💾 Сохранить настройки Telegram")
            if tg_submitted:
                if tg_token and tg_chat:
                    save_credentials({"telegram": {"bot_token": tg_token, "chat_id": tg_chat}})
                    tg_reload()
                    st.success("Настройки Telegram сохранены!")
                    st.rerun()
                else:
                    st.error("Заполните оба поля.")
        if tg_ok:
            st.success("✅ Telegram настроен")
            if st.button("📨 Отправить тестовое сообщение"):
                ok, msg = tg_test()
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    st.markdown("---")
    st.markdown("### 📦 Полная выгрузка реестра Kazpatent")
    st.markdown("Загрузить все товарные знаки из реестра на локальный компьютер.")

    with st.expander("Настройки выгрузки"):
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            dl_type = st.selectbox(
                "Тип объектов",
                ["trademark", "well_known", "international"],
                format_func=lambda x: {"trademark": "Товарные знаки", "well_known": "Общеизвестные ТЗ", "international": "Международные ТЗ"}.get(x, x),
            )
            dl_query = st.text_input("Фильтр по обозначению (пусто = все)")
        with dl_col2:
            dl_max_pages = st.number_input("Максимум страниц", min_value=1, max_value=500, value=50)
            st.caption("1 страница ≈ 20-50 записей")

        if st.button("⬇️ Начать выгрузку реестра", type="primary"):
            progress = st.progress(0, text="Инициализация...")
            status = st.empty()
            total_found = [0]

            def update_progress(page_num, found):
                total_found[0] = found
                pct = min(page_num / dl_max_pages, 1.0)
                progress.progress(pct, text=f"Страница {page_num} / ~{dl_max_pages} | Записей: {found}")
                status.write(f"Обрабатываю страницу {page_num}...")

            try:
                from scraper_kazpatent import search_trademarks
                from monitor import _save_mark
                from similarity import compare

                records = search_trademarks(
                    query=dl_query,
                    object_type=dl_type,
                    max_pages=int(dl_max_pages),
                    progress_callback=update_progress,
                )
                progress.progress(1.0, text="Сохраняем в базу данных...")

                saved = 0
                skipped = 0
                with get_connection() as conn:
                    for record in records:
                        # Полная выгрузка: сохраняем каждую запись один раз (без привязки к профилю)
                        no_profile = {"is_match": False, "risk_level": "informational",
                                      "score": 0, "match_types": [], "reason": "Выгрузка реестра"}
                        is_new = _save_mark(conn, None, record["source_code"], record, no_profile)
                        if is_new:
                            saved += 1
                        else:
                            skipped += 1
                    conn.commit()

                status.empty()
                msg = f"Выгрузка завершена. Записей получено: {len(records)}, новых сохранено: {saved}"
                if skipped:
                    msg += f", уже в базе: {skipped}"
                st.success(msg)
            except Exception as e:
                st.error(f"Ошибка выгрузки: {e}")

    st.markdown("---")
    st.markdown("### База данных")
    from paths import DB_PATH as db_path
    st.code(str(db_path))
    if db_path.exists():
        size_kb = db_path.stat().st_size / 1024
        st.write(f"Размер файла БД: {size_kb:.1f} КБ")

    st.markdown("### Пути к папкам")
    base = Path(__file__).parent.parent
    for folder in ["data/reports", "data/downloads", "data/screenshots", "data/logs"]:
        st.code(str(base / folder))

    # ── Управление пользователями ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 👤 Управление пользователями")

    _current_user = st.session_state.get("username", "")
    _current_role = st.session_state.get("roles", ["user"])[0] if st.session_state.get("roles") else "user"

    tab_users, tab_pwd = st.tabs(["👥 Пользователи (admin)", "🔑 Сменить пароль"])

    with tab_users:
        try:
            _creds = st.secrets["credentials"]["usernames"]
            st.markdown("**Текущие пользователи:**")
            for uname, udata in _creds.items():
                col_u, col_r = st.columns([3, 1])
                with col_u:
                    st.write(f"🧑 **{udata.get('name', uname)}** (`{uname}`) — {udata.get('email', '—')}")
                with col_r:
                    st.caption(udata.get("role", "user"))
        except Exception:
            st.info("Список пользователей доступен только на облачном деплое.")

        st.markdown("---")
        st.markdown("**Добавить нового пользователя:**")
        st.caption("Заполните данные — система сгенерирует строку для вставки в Streamlit Secrets.")
        with st.form("add_user_form"):
            new_login = st.text_input("Логин (латиница, без пробелов)", placeholder="a.ivanova")
            new_name  = st.text_input("Имя (отображается в приложении)", placeholder="Айгерим Иванова")
            new_email = st.text_input("Email", placeholder="a.ivanova@sergekgroup.kz")
            new_pwd   = st.text_input("Временный пароль", type="password")
            new_role  = st.selectbox("Роль", ["user", "admin"])
            if st.form_submit_button("🔐 Сгенерировать запись"):
                if new_login and new_name and new_pwd:
                    import bcrypt
                    hashed = bcrypt.hashpw(new_pwd.encode(), bcrypt.gensalt(12)).decode()
                    toml_snippet = (
                        f'\n[credentials.usernames."{new_login}"]\n'
                        f'email = "{new_email}"\n'
                        f'name = "{new_name}"\n'
                        f'password = "{hashed}"\n'
                        f'role = "{new_role}"\n'
                    )
                    st.success("Скопируйте строку ниже и вставьте в Streamlit Secrets → Save:")
                    st.code(toml_snippet, language="toml")
                else:
                    st.error("Заполните логин, имя и пароль.")

    with tab_pwd:
        st.markdown(f"Вы вошли как **{_current_user}**. Смените пароль:")
        with st.form("change_pwd_form"):
            old_pwd  = st.text_input("Текущий пароль", type="password")
            new_pwd1 = st.text_input("Новый пароль", type="password")
            new_pwd2 = st.text_input("Повторите новый пароль", type="password")
            if st.form_submit_button("💾 Сменить пароль"):
                if not old_pwd or not new_pwd1:
                    st.error("Заполните все поля.")
                elif new_pwd1 != new_pwd2:
                    st.error("Новые пароли не совпадают.")
                elif len(new_pwd1) < 8:
                    st.error("Пароль должен быть не менее 8 символов.")
                else:
                    try:
                        import bcrypt
                        stored = st.secrets["credentials"]["usernames"][_current_user]["password"]
                        if bcrypt.checkpw(old_pwd.encode(), stored.encode()):
                            new_hash = bcrypt.hashpw(new_pwd1.encode(), bcrypt.gensalt(12)).decode()
                            toml_line = f'password = "{new_hash}"'
                            st.success("Пароль подтверждён. Обновите строку в Streamlit Secrets:")
                            st.code(
                                f'[credentials.usernames."{_current_user}"]\n'
                                f'password = "{new_hash}"',
                                language="toml",
                            )
                            st.caption("Замените только строку password= в своём блоке credentials и нажмите Save.")
                        else:
                            st.error("Неверный текущий пароль.")
                    except Exception as e:
                        st.error(f"Ошибка: {e}")

    st.markdown("### О системе")
    st.info(
        "**IP Watch KZ** — система мониторинга товарных знаков Serge Group.\n\n"
        "v1.0 — реестр и бюллетень Kazpatent.\n"
        "v2.0 — WIPO Global Brand Database, Madrid Monitor, автозапуск по расписанию."
    )

    st.markdown("### Сброс данных")
    st.warning("Следующие действия необратимы.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Очистить все найденные записи", type="secondary"):
            with get_connection() as conn:
                conn.execute("DELETE FROM found_marks")
                conn.execute("DELETE FROM mark_classes")
                conn.execute("DELETE FROM legal_reviews")
                conn.commit()
            st.success("Все найденные записи удалены.")
    with col2:
        if st.button("🗑️ Очистить журнал проверок", type="secondary"):
            with get_connection() as conn:
                conn.execute("DELETE FROM search_runs")
                conn.commit()
            st.success("Журнал проверок очищен.")
