@echo off
chcp 65001 > nul
title IP Watch KZ — Установка

echo ============================================
echo    IP Watch KZ — Установка / Переустановка
echo ============================================
echo.

cd /d "%~dp0"

:: Проверяем Python
python --version > nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не найден.
    echo Скачайте Python 3.11 с https://python.org/downloads
    echo При установке поставьте галочку "Add Python to PATH"
    pause
    exit /b 1
)

echo Обновляем pip...
python -m pip install --upgrade pip --quiet

echo.
echo Устанавливаем все зависимости...
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ОШИБКА при установке.
    echo Попробуйте запустить от имени администратора (правая кнопка — Запуск от имени администратора).
    pause
    exit /b 1
)

echo.
echo ============================================
echo    Установка завершена успешно!
echo    Теперь запустите run.bat
echo ============================================
echo.
pause
