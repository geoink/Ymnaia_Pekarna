@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 run_app.py %*
) else (
    python run_app.py %*
)
if errorlevel 1 (
    echo Нужен Python 3.11 или новее: https://www.python.org/downloads/
    pause
)
