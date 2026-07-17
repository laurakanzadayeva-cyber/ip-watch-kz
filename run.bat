@echo off
chcp 65001 > nul
title IP Watch KZ

echo ============================================
echo    IP Watch KZ — Запуск приложения
echo ============================================
echo.

cd /d "%~dp0"

:: Проверяем Python
python --version > nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не найден.
    echo Скачайте Python с https://python.org/downloads
    pause
    exit /b 1
)

:: Проверяем Streamlit, при необходимости ставим зависимости
python -c "import streamlit, docx, pypdf, openpyxl, google.generativeai" > nul 2>&1
if errorlevel 1 (
    echo Устанавливаем зависимости (один раз)...
    python -m pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo ОШИБКА при установке зависимостей.
        pause
        exit /b 1
    )
    echo Готово.
    echo.
)

echo Приложение запускается на http://localhost:8501
echo Браузер откроется автоматически...
echo.
echo Для остановки закройте это окно или нажмите Ctrl+C
echo.

start "" http://localhost:8501
python -m streamlit run app\main.py --server.headless false --browser.gatherUsageStats false --server.port 8501

pause
