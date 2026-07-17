"""
Анализ правовых изменений через Gemini AI.
Определяет: затрагивает ли документ ИС, что именно изменилось.
"""

import logging
from config_manager import get_gemini_key, get_gemini_model, get_openrouter_key

logger = logging.getLogger(__name__)

IP_ANALYSIS_PROMPT = """Ты — эксперт по интеллектуальной собственности в Казахстане.
Проанализируй следующий нормативный документ или его изменения.

Документ: {title}
Содержание: {content}

Ответь строго в JSON-формате:
{{
  "is_ip_relevant": true/false,
  "ip_areas": ["товарные знаки", "авторское право", "патенты", ...],
  "key_changes": ["конкретное изменение 1", "конкретное изменение 2", ...],
  "impact": "краткое описание влияния на практику (1-2 предложения)",
  "risk_level": "высокий/средний/низкий/нет",
  "action_needed": "что нужно сделать юристу (или 'мониторинг')",
  "summary": "краткое резюме на русском языке (3-5 предложений)"
}}

Если документ не касается интеллектуальной собственности — is_ip_relevant: false, остальные поля пустые.
"""

TRADEMARK_SIMILARITY_PROMPT = """Ты — эксперт по товарным знакам в Казахстане.
Оцени степень сходства двух обозначений с точки зрения возможности смешения потребителями.

Контрольный знак: {control}
Найденный знак: {candidate}
Классы МКТУ контрольного знака: {control_classes}
Классы МКТУ найденного знака: {candidate_classes}
Правообладатель найденного знака: {owner}
Техническая оценка системы: {tech_assessment}

Ответь в JSON:
{{
  "confusion_possible": true/false,
  "similarity_type": ["визуальное", "звуковое", "смысловое"],
  "dominant_element": "главный элемент обозначения",
  "legal_risk": "высокий/средний/низкий",
  "reasoning": "обоснование (2-4 предложения)",
  "recommendation": "наблюдать/направить претензию/подать возражение/нет риска"
}}
"""


def analyze_legal_document(title: str, content: str = "") -> dict:
    """
    Анализирует нормативный документ на предмет затронутых вопросов ИС.
    Возвращает структурированный анализ.
    """
    api_key = get_gemini_key()
    if not api_key:
        return _fallback_keyword_analysis(title, content)

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(get_gemini_model())

        prompt = IP_ANALYSIS_PROMPT.format(
            title=title,
            content=content[:3000] if content else "Содержание недоступно",
        )

        response = model.generate_content(prompt)
        text = response.text.strip()

        # Извлекаем JSON из ответа
        import json, re
        json_match = re.search(r'\{[\s\S]+\}', text)
        if json_match:
            return json.loads(json_match.group())
        return {"error": "Не удалось разобрать ответ AI", "raw": text[:500]}

    except Exception as e:
        logger.error(f"Ошибка Gemini AI: {e}")
        return _fallback_keyword_analysis(title, content)


def analyze_trademark_similarity(
    control: str,
    candidate: str,
    control_classes: list = None,
    candidate_classes: list = None,
    owner: str = "",
    tech_assessment: str = "",
) -> dict:
    """
    AI-оценка сходства товарных знаков до степени смешения.
    """
    api_key = get_gemini_key()
    if not api_key:
        return {"error": "Gemini API ключ не настроен", "reasoning": "Настройте Gemini API в разделе Настройки"}

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(get_gemini_model())

        prompt = TRADEMARK_SIMILARITY_PROMPT.format(
            control=control,
            candidate=candidate,
            control_classes=", ".join(str(c) for c in (control_classes or [])) or "все",
            candidate_classes=", ".join(str(c) for c in (candidate_classes or [])) or "не указаны",
            owner=owner or "не указан",
            tech_assessment=tech_assessment or "не выполнена",
        )

        response = model.generate_content(prompt)
        text = response.text.strip()

        import json, re
        json_match = re.search(r'\{[\s\S]+\}', text)
        if json_match:
            return json.loads(json_match.group())
        return {"error": "Не удалось разобрать ответ AI", "raw": text[:500]}

    except Exception as e:
        logger.error(f"Ошибка Gemini AI: {e}")
        return {"error": str(e)}


OPPOSITION_PROMPT = """Ты — опытный казахстанский патентный поверенный и юрист по интеллектуальной собственности с опытом работы в Апелляционном совете МЮ РК.

Напиши полный текст ВОЗРАЖЕНИЯ в Апелляционный совет Министерства юстиции Республики Казахстан.

═══════════════════════════════════════
ДАННЫЕ ДЕЛА:
{case_facts}
═══════════════════════════════════════
{reference_context}
═══════════════════════════════════════

ТРЕБОВАНИЯ К ДОКУМЕНТУ:
- Язык: официально-деловой русский
- Структура: вводный абзац → пронумерованные разделы с аргументацией → просительная часть («ПРОСИМ:») → список приложений
- Правовая база: Закон РК «О товарных знаках» (ст.23, подп.1) п.3 ст.6, подп.1) п.1 ст.7), ГК РК ст.1025-1030
- Минимум 3 раздела: (1) более ранние права заявителя, (2) сходство до степени смешения, (3) отсутствие самостоятельной различительной способности оспариваемого знака. При наличии доп. оснований — добавь разделы.
- Ссылайся только на приведённые факты. Не придумывай данные, которых нет в задании.
- Просительная часть: по каждому оспариваемому знаку отдельная просьба о признании недействительным.
- Список приложений: перечисли документы, логически необходимые для данного дела.

Напиши ТОЛЬКО тело возражения (без шапки с адресатом и без строки подписи — они добавляются отдельно).
Используй формат:
## Раздел N. <название>
<текст раздела>

## ПРОСИМ:
<просительная часть>

## Приложения:
<список>
"""


HERMES_API_URL  = "http://localhost:8642/v1/chat/completions"
HERMES_API_KEY  = "ipwatch-hermes-key"
HERMES_MODEL    = "hermes-agent"

OPENROUTER_URL  = "https://openrouter.ai/api/v1/chat/completions"
# Бесплатные модели в порядке приоритета — перебираем при 429
OPENROUTER_FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "openai/gpt-oss-120b:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "google/gemma-4-31b-it:free",
]


def _is_hermes_running() -> bool:
    try:
        import requests as _req
        r = _req.get("http://localhost:8642/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _call_hermes(prompt: str) -> str:
    import requests as _req
    payload = {"model": HERMES_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False}
    headers = {"Authorization": f"Bearer {HERMES_API_KEY}", "Content-Type": "application/json"}
    r = _req.post(HERMES_API_URL, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_openrouter(prompt: str, api_key: str) -> str:
    """Вызывает OpenRouter, перебирая бесплатные модели при 429."""
    import requests as _req
    import time
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ipwatch.sergekgroup.kz",
        "X-Title": "IP Watch KZ",
    }
    last_err = ""
    for model in OPENROUTER_FREE_MODELS:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4000,
        }
        try:
            r = _req.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
            if r.status_code == 200:
                logger.info(f"OpenRouter: использована модель {model}")
                return r.json()["choices"][0]["message"]["content"].strip()
            elif r.status_code == 429:
                retry = r.json().get("error", {}).get("metadata", {}).get("retry_after_seconds", 5)
                logger.warning(f"OpenRouter 429 для {model}, retry через {retry}s")
                time.sleep(min(float(retry), 10))
                # повтор той же модели один раз
                r2 = _req.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
                if r2.status_code == 200:
                    return r2.json()["choices"][0]["message"]["content"].strip()
                last_err = f"{model}: 429"
            else:
                last_err = f"{model}: HTTP {r.status_code}"
                logger.warning(f"OpenRouter {r.status_code} для {model}: {r.text[:200]}")
        except Exception as e:
            last_err = str(e)
            logger.warning(f"OpenRouter ошибка для {model}: {e}")
    raise RuntimeError(f"Все модели OpenRouter недоступны. Последняя ошибка: {last_err}")


def _build_case_facts(case_data: dict) -> tuple[str, str]:
    """Возвращает (case_facts, reference_context) строки из case_data."""
    our_lines = []
    for m in case_data.get("our_marks", []):
        classes = ", ".join(str(c) for c in m.get("classes", []))
        our_lines.append(
            f"  • ТЗ {m.get('name', '')} №{m.get('number', '')} — "
            f"приоритет {m.get('priority_date', '')}, рег. {m.get('reg_date', '')}, "
            f"действует до {m.get('expiry_date', '')}, классы МКТУ: {classes}"
        )

    cont_lines = []
    for m in case_data.get("contested_marks", []):
        classes = ", ".join(str(c) for c in m.get("classes", []))
        cont_lines.append(
            f"  • ТЗ «{m.get('name', '')}» №{m.get('number', '')} "
            f"(заявка №{m.get('app_number', '')}), "
            f"приоритет {m.get('priority_date', '')}, рег. {m.get('reg_date', '')}, "
            f"действует до {m.get('expiry_date', '')}, классы МКТУ: {classes}"
        )

    case_facts = f"""
ЗАЯВИТЕЛЬ: {case_data.get('applicant_name', '')}
{'БИН: ' + case_data['applicant_bin'] if case_data.get('applicant_bin') else ''}
{'Адрес: ' + case_data['applicant_address'] if case_data.get('applicant_address') else ''}
{'Представитель: ' + case_data['rep_name'] if case_data.get('rep_name') else ''}

ВЛАДЕЛЕЦ ОСПАРИВАЕМЫХ РЕГИСТРАЦИЙ: {case_data.get('owner_name', '')}
{'Адрес: ' + case_data['owner_address'] if case_data.get('owner_address') else ''}

НАШИ (БОЛЕЕ РАННИЕ) ТОВАРНЫЕ ЗНАКИ ЗАЯВИТЕЛЯ:
{chr(10).join(our_lines) if our_lines else '  (не указаны)'}

ОСПАРИВАЕМЫЕ ТОВАРНЫЕ ЗНАКИ:
{chr(10).join(cont_lines) if cont_lines else '  (не указаны)'}

ДОПОЛНИТЕЛЬНЫЕ ФАКТЫ И ОБСТОЯТЕЛЬСТВА:
{case_data.get('extra_context', 'не указаны')}
"""
    ref = case_data.get("reference_text", "")
    reference_context = (
        f"ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ ИЗ ЗАГРУЖЕННЫХ ДОКУМЕНТОВ:\n{ref[:4000]}"
        if ref else ""
    )
    return case_facts.strip(), reference_context


def generate_opposition_text(case_data: dict) -> str:
    """
    Генерирует текст возражения.
    Приоритет: Hermes (localhost:8642) → Gemini API.

    case_data ключи:
        applicant_name, applicant_bin, applicant_address  — заявитель
        rep_name, rep_iin, rep_address, rep_phone, rep_email  — представитель (опц.)
        our_marks  — list[dict]: name, number, priority_date, reg_date, expiry_date, classes
        contested_marks  — list[dict]: name, number, app_number, priority_date, reg_date, expiry_date, classes
        owner_name, owner_address  — владелец оспариваемых знаков
        extra_context  — str: доп. факты/аргументы
        reference_text — str: текст из загруженных файлов
    """
    case_facts, reference_context = _build_case_facts(case_data)
    prompt = OPPOSITION_PROMPT.format(
        case_facts=case_facts,
        reference_context=reference_context,
    )

    # ── Попытка 1: OpenRouter (прямой вызов) ────────────────────────────────
    or_key = get_openrouter_key()
    if or_key:
        logger.info("Используем OpenRouter API")
        try:
            return _call_openrouter(prompt, or_key)
        except Exception as e:
            logger.warning(f"OpenRouter недоступен, пробуем Gemini: {e}")

    # ── Попытка 2: Hermes (если запущен) ────────────────────────────────────
    if _is_hermes_running():
        logger.info("Используем Hermes API (localhost:8642)")
        try:
            return _call_hermes(prompt)
        except Exception as e:
            logger.warning(f"Hermes ошибка, пробуем Gemini: {e}")

    # ── Попытка 3: Gemini напрямую ───────────────────────────────────────────
    api_key = get_gemini_key()
    if not api_key:
        raise RuntimeError(
            "Нет доступных AI-провайдеров. "
            "Добавьте OpenRouter или Gemini ключ в ⚙️ Настройки."
        )
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(get_gemini_model())
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        err = str(e)
        logger.error(f"Ошибка Gemini: {err}")
        if "429" in err or "quota" in err.lower():
            raise RuntimeError(
                "Все AI-провайдеры временно недоступны (квоты исчерпаны). "
                "Попробуйте через несколько минут."
            ) from e
        if "api_key" in err.lower() or "invalid" in err.lower():
            raise RuntimeError("Неверный Gemini API ключ. Проверьте ключ в ⚙️ Настройки.") from e
        raise


def _fallback_keyword_analysis(title: str, content: str) -> dict:
    """Анализ без AI — по ключевым словам."""
    from scraper_paragraph import IP_KEYWORDS

    combined = (title + " " + content).lower()
    matched = [kw for kw in IP_KEYWORDS if kw in combined]

    is_relevant = len(matched) > 0
    areas = []
    if any(w in combined for w in ["товарный знак", "знак обслуживания"]):
        areas.append("товарные знаки")
    if any(w in combined for w in ["авторское право", "смежные права"]):
        areas.append("авторское право")
    if "патент" in combined:
        areas.append("патенты")

    return {
        "is_ip_relevant": is_relevant,
        "ip_areas": areas,
        "key_changes": [],
        "impact": "Документ затрагивает сферу ИС" if is_relevant else "Документ не касается ИС",
        "risk_level": "средний" if is_relevant else "нет",
        "action_needed": "Ознакомиться с документом" if is_relevant else "мониторинг",
        "summary": f"Документ содержит ключевые слова ИС: {', '.join(matched[:5])}" if matched else "Документ не содержит ИС-тематики",
        "ai_used": False,
    }
