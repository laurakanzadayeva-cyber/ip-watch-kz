"""
Управление учётными данными и настройками.
Файл credentials.json хранится в config/ и не передаётся никому.
"""

import json
from pathlib import Path
from paths import CONFIG_DIR

CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TEMPLATE_FILE = CONFIG_DIR / "credentials.template.json"


def load_credentials() -> dict:
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_credentials(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_credentials()
    existing.update(data)
    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def get_paragraph_creds() -> tuple[str, str, str]:
    creds = load_credentials()
    p = creds.get("paragraph", {})
    return (
        p.get("url", "https://online.prg.kz/lawyer"),
        p.get("login", ""),
        p.get("password", ""),
    )


def get_gemini_key() -> str:
    creds = load_credentials()
    return creds.get("gemini", {}).get("api_key", "")


def get_gemini_model() -> str:
    creds = load_credentials()
    return creds.get("gemini", {}).get("model", "gemini-1.5-flash")


def get_openrouter_key() -> str:
    creds = load_credentials()
    key = creds.get("openrouter", {}).get("api_key", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("openrouter", {}).get("api_key", "")
        except Exception:
            pass
    return key


def get_telegram_config() -> dict:
    creds = load_credentials()
    return creds.get("telegram", {})


def credentials_configured() -> dict:
    creds = load_credentials()
    return {
        "paragraph": bool(creds.get("paragraph", {}).get("login")),
        "gemini": bool(creds.get("gemini", {}).get("api_key")),
        "openrouter": bool(creds.get("openrouter", {}).get("api_key")),
        "telegram": bool(creds.get("telegram", {}).get("bot_token")),
    }
