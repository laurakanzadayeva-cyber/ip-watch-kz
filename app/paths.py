"""
Централизованное разрешение путей.
Режим разработки: папка проекта.
Установлено в Program Files: данные хранятся в APPDATA/IP Watch KZ.
"""
import os
from pathlib import Path

_APP_DIR = Path(__file__).parent
_INSTALL_DIR = _APP_DIR.parent

# Определяем: установлено в Program Files или запущено из исходников
_in_program_files = any(
    p in str(_INSTALL_DIR).lower()
    for p in ("program files", "program files (x86)")
)

if _in_program_files:
    # Данные пользователя — в %APPDATA%\IP Watch KZ (всегда доступно для записи)
    USER_DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "IP Watch KZ"
else:
    # Режим разработки — рядом с проектом
    USER_DATA_DIR = _INSTALL_DIR

# Папки данных (перезаписываемые)
CONFIG_DIR   = USER_DATA_DIR / "config"
DATA_DIR     = USER_DATA_DIR / "data"
LAWS_DIR     = USER_DATA_DIR / "laws"
REPORTS_DIR  = DATA_DIR / "reports"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
DOWNLOADS_DIR   = DATA_DIR / "downloads"
DB_PATH      = DATA_DIR / "database.sqlite"

# Папка с исходниками приложения (только чтение при установке)
APP_DIR = _APP_DIR
INSTALL_DIR = _INSTALL_DIR


def init_user_dirs():
    """Создаёт нужные папки и копирует начальные файлы при первом запуске."""
    for d in [CONFIG_DIR, DATA_DIR, LAWS_DIR, REPORTS_DIR, SCREENSHOTS_DIR, DOWNLOADS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    # Копируем credentials.json из установки если ещё нет
    src_creds = _INSTALL_DIR / "config" / "credentials.json"
    dst_creds = CONFIG_DIR / "credentials.json"
    if src_creds.exists() and not dst_creds.exists():
        import shutil
        shutil.copy2(src_creds, dst_creds)

    # Копируем шаблон
    src_tmpl = _INSTALL_DIR / "config" / "credentials.template.json"
    dst_tmpl = CONFIG_DIR / "credentials.template.json"
    if src_tmpl.exists() and not dst_tmpl.exists():
        import shutil
        shutil.copy2(src_tmpl, dst_tmpl)

    # Копируем законы из установки если ещё нет
    src_laws = _INSTALL_DIR / "laws"
    if src_laws.exists() and not any(LAWS_DIR.iterdir() if LAWS_DIR.exists() else []):
        import shutil
        shutil.copytree(src_laws, LAWS_DIR, dirs_exist_ok=True)
