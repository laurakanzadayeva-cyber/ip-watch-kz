"""
IP Watch KZ — лаунчер приложения.
Запускает Streamlit-сервер и открывает браузер.
"""
import subprocess
import webbrowser
import time
import sys
import os
import threading
import socket

# При запуске через PyInstaller используем путь к .exe, а не к временному __file__
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APP_DIR = os.path.join(BASE_DIR, "app")
MAIN_PY = os.path.join(APP_DIR, "main.py")
PORT = 8501
URL = f"http://localhost:{PORT}"


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("localhost", port)) == 0


def wait_and_open():
    for _ in range(40):  # ждём до 20 секунд
        if is_port_open(PORT):
            webbrowser.open(URL)
            return
        time.sleep(0.5)
    webbrowser.open(URL)


def find_python() -> str:
    """Находит Python-интерпретатор в системе."""
    if not getattr(sys, "frozen", False):
        return sys.executable

    import shutil

    # 1. Windows Python Launcher py.exe — всегда в C:\Windows при стандартной установке
    py_launcher = shutil.which("py")
    if py_launcher and os.path.exists(py_launcher):
        return py_launcher

    # 2. python/python3 в PATH
    for name in ("python", "python3", "python.exe"):
        p = shutil.which(name)
        if p:
            return p

    # 3. Реестр Windows — Python регистрируется там при установке
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for subkey in (
                r"SOFTWARE\Python\PythonCore",
                r"SOFTWARE\WOW6432Node\Python\PythonCore",
            ):
                try:
                    with winreg.OpenKey(hive, subkey) as root:
                        i = 0
                        while True:
                            try:
                                ver = winreg.EnumKey(root, i)
                                try:
                                    with winreg.OpenKey(root, rf"{ver}\InstallPath") as kpath:
                                        exe, _ = winreg.QueryValueEx(kpath, "ExecutablePath")
                                        if exe and os.path.exists(exe):
                                            return exe
                                except OSError:
                                    pass
                                i += 1
                            except OSError:
                                break
                except OSError:
                    pass
    except Exception:
        pass

    # 4. Расширенный список стандартных путей Windows
    lad = os.environ.get("LOCALAPPDATA", "")
    home = os.path.expanduser("~")
    candidates = []
    for ver in ("3.14", "3.13", "3.12", "3.11", "3.10", "3.9"):
        vc = ver.replace(".", "")
        candidates += [
            os.path.join(lad, f"Programs\\Python\\Python{vc}\\python.exe"),
            os.path.join(lad, f"Python\\pythoncore-{ver}-64\\python.exe"),
            os.path.join(lad, f"Python\\pythoncore-{ver}-32\\python.exe"),
            os.path.join(lad, f"Microsoft\\WindowsApps\\python3.exe"),
            f"C:\\Python{vc}\\python.exe",
            f"C:\\Python{vc}-64\\python.exe",
        ]
    # Anaconda / Miniconda
    for base in (home, "C:\\ProgramData", "C:\\"):
        for name in ("anaconda3", "miniconda3", "Anaconda3", "Miniconda3"):
            candidates.append(os.path.join(base, name, "python.exe"))
    for c in candidates:
        if os.path.exists(c):
            return c

    return ""   # не найден — обработаем ниже


if __name__ == "__main__":
    if is_port_open(PORT):
        webbrowser.open(URL)
        sys.exit(0)

    if not os.path.isdir(APP_DIR):
        # Ищем app в стандартных местах установки
        fallback_dirs = [
            r"C:\Program Files\IP Watch KZ",
            r"C:\Program Files (x86)\IP Watch KZ",
            os.path.join(os.environ.get("APPDATA", ""), "IP Watch KZ", "app"),
        ]
        found = False
        for fb in fallback_dirs:
            candidate = os.path.join(fb, "app") if not fb.endswith("app") else fb
            if os.path.isdir(candidate):
                APP_DIR = candidate
                MAIN_PY = os.path.join(APP_DIR, "main.py")
                found = True
                break
        if not found:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "Папка приложения не найдена.\n\n"
                "Запустите файл IPWatchKZ.exe из папки установки\n"
                "(C:\\Program Files\\IP Watch KZ\\),\n"
                "а не с рабочего стола.\n\n"
                "Или переустановите IP Watch KZ.",
                "IP Watch KZ — ошибка",
                0x10,
            )
            sys.exit(1)

    python = find_python()
    if not python:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            "Python не найден на этом компьютере.\n\n"
            "Установите Python 3.10 или новее:\n"
            "https://www.python.org/downloads/\n\n"
            "После установки перезапустите IP Watch KZ.",
            "IP Watch KZ — Python не найден",
            0x10,
        )
        sys.exit(1)

    # Проверяем наличие streamlit в найденном Python
    check = subprocess.run(
        [python, "-c", "import streamlit"],
        capture_output=True,
    )
    if check.returncode != 0:
        import ctypes
        # Пробуем установить автоматически
        inst = subprocess.run(
            [python, "-m", "pip", "install", "streamlit", "playwright", "python-docx",
             "python-telegram-bot", "schedule", "--quiet"],
            capture_output=True,
        )
        if inst.returncode != 0:
            ctypes.windll.user32.MessageBoxW(
                0,
                "Не удалось установить зависимости автоматически.\n\n"
                "Выполните в командной строке:\n"
                f"  {python} -m pip install streamlit playwright python-docx\n\n"
                "Затем перезапустите IP Watch KZ.",
                "IP Watch KZ — ошибка установки",
                0x10,
            )
            sys.exit(1)

    threading.Thread(target=wait_and_open, daemon=True).start()

    py_args = [python]
    # py.exe нужен флаг версии для запуска модуля
    if os.path.basename(python).lower() == "py.exe":
        py_args = [python, "-3"]

    proc = subprocess.Popen(
        py_args + ["-m", "streamlit", "run", MAIN_PY,
                   "--server.port", str(PORT),
                   "--server.headless", "true",
                   "--browser.gatherUsageStats", "false"],
        cwd=APP_DIR,
    )
    proc.wait()
