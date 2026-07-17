"""
Алгоритм сравнения словесных обозначений.
Нормализация, типы совпадений, риск-скоринг.
"""

import re
import unicodedata

TRANSLIT_CYR_TO_LAT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    # казахские буквы
    'ә': 'a', 'ғ': 'gh', 'қ': 'q', 'ң': 'ng', 'ө': 'o', 'ұ': 'u',
    'ү': 'u', 'һ': 'h', 'і': 'i',
}

TRANSLIT_LAT_TO_CYR = {v: k for k, v in TRANSLIT_CYR_TO_LAT.items() if v}


def normalize(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r'[\s\-_\.\"\'«»„"]+', ' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def transliterate_cyr_to_lat(text: str) -> str:
    result = []
    for ch in text.lower():
        result.append(TRANSLIT_CYR_TO_LAT.get(ch, ch))
    return ''.join(result)


def transliterate_lat_to_cyr(text: str) -> str:
    result = text.lower()
    for lat, cyr in sorted(TRANSLIT_LAT_TO_CYR.items(), key=lambda x: -len(x[0])):
        result = result.replace(lat, cyr)
    return result


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


def _is_cyrillic(text: str) -> bool:
    return bool(re.search(r'[а-яёА-ЯЁәғқңөұүһіӘҒҚҢӨҰҮҺІ]', text))


def compare(control: str, candidate: str) -> dict:
    """
    Сравнивает контрольное обозначение с кандидатом.
    Возвращает словарь: match_type, risk_level, reason, score.
    """
    ctrl_norm = normalize(control)
    cand_norm = normalize(candidate)

    reasons = []
    match_types = []
    score = 0  # 0–100

    # --- полное совпадение ---
    if ctrl_norm == cand_norm:
        match_types.append('exact')
        reasons.append('Полное совпадение обозначений')
        score = 100

    # --- включение ---
    if not match_types:
        if ctrl_norm in cand_norm or cand_norm in ctrl_norm:
            match_types.append('inclusion')
            reasons.append(f'Обозначение включает/включено в найденный знак')
            score = max(score, 90)

    # --- транслитерация ---
    ctrl_is_cyr = _is_cyrillic(ctrl_norm)
    cand_is_cyr = _is_cyrillic(cand_norm)

    ctrl_translit = transliterate_cyr_to_lat(ctrl_norm) if ctrl_is_cyr else transliterate_lat_to_cyr(ctrl_norm)
    cand_translit = transliterate_cyr_to_lat(cand_norm) if cand_is_cyr else transliterate_lat_to_cyr(cand_norm)

    if ctrl_is_cyr != cand_is_cyr:  # разные алфавиты
        if ctrl_norm == cand_translit or ctrl_translit == cand_norm or ctrl_translit == cand_translit:
            match_types.append('transliteration')
            reasons.append('Транслитерационное совпадение (кирилл./латин.)')
            score = max(score, 90)

    # --- расстояние Левенштейна ---
    dist = levenshtein(ctrl_norm, cand_norm)
    dist_translit = levenshtein(ctrl_translit, cand_norm) if ctrl_translit else dist

    effective_dist = min(dist, dist_translit)
    ctrl_len = max(len(ctrl_norm), 1)

    if effective_dist == 0 and not match_types:
        match_types.append('exact')
        reasons.append('Точное совпадение после нормализации')
        score = max(score, 100)
    elif effective_dist == 1:
        match_types.append('diff_1')
        reasons.append(f'Отличие на 1 символ (расстояние Левенштейна = 1)')
        score = max(score, 88)
    elif effective_dist == 2:
        match_types.append('diff_2')
        reasons.append(f'Отличие на 2 символа (расстояние Левенштейна = 2)')
        score = max(score, 72)
    elif effective_dist <= max(2, ctrl_len // 4):
        match_types.append('partial')
        reasons.append(f'Частичное совпадение (расстояние = {effective_dist})')
        score = max(score, 50)

    # --- фонетическое сходство (упрощённый soundex-подобный) ---
    if not match_types or score < 60:
        ctrl_phone = _simple_phonetic(ctrl_norm)
        cand_phone = _simple_phonetic(cand_norm)
        if ctrl_phone and cand_phone and ctrl_phone == cand_phone:
            match_types.append('phonetic')
            reasons.append('Фонетическое сходство')
            score = max(score, 65)

    # --- слово из контроля содержится в кандидате (токены) ---
    if not match_types or score < 40:
        ctrl_tokens = set(ctrl_norm.split())
        cand_tokens = set(cand_norm.split())
        common = ctrl_tokens & cand_tokens
        if common and len(common) / max(len(ctrl_tokens), 1) >= 0.5:
            match_types.append('token_overlap')
            reasons.append(f'Общие значимые элементы: {", ".join(common)}')
            score = max(score, 45)

    if not match_types:
        return {
            'match_types': [],
            'risk_level': None,
            'reason': '',
            'score': 0,
            'is_match': False,
        }

    risk_level = _score_to_risk(score)

    return {
        'match_types': match_types,
        'risk_level': risk_level,
        'reason': '; '.join(reasons),
        'score': score,
        'is_match': True,
    }


def _simple_phonetic(text: str) -> str:
    t = text.replace(' ', '')
    # убираем гласные кроме первой
    if not t:
        return t
    result = t[0]
    for ch in t[1:]:
        if ch not in 'аеёиоуыэюяaeiou':
            result += ch
    return result


def _score_to_risk(score: int) -> str:
    if score >= 85:
        return 'high'
    elif score >= 60:
        return 'medium'
    elif score >= 35:
        return 'low'
    else:
        return 'informational'


RISK_LABELS = {
    'high': 'Высокий',
    'medium': 'Средний',
    'low': 'Низкий',
    'informational': 'Информационный',
}

RISK_COLORS = {
    'high': '#d32f2f',
    'medium': '#f57c00',
    'low': '#388e3c',
    'informational': '#1976d2',
}
