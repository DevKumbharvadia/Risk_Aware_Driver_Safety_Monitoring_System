
@echo off
setlocal
cd /d "%~dp0"

title Fleet Guardian Launcher

echo ==========================================
echo       FLEET GUARDIAN - STARTUP
echo ==========================================
echo.

REM Check Python 3.13
py -3.13 --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.13 is not installed.
    echo Install Python 3.13 and try again.
    pause
    exit /b 1
)

REM Create virtual environment if missing
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    py -3.13 -m venv .venv
    if errorlevel 1 goto venv_failed
) else (
    echo [1/3] Virtual environment already exists.
)

REM Upgrade pip
echo.
echo [2/3] Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto install_failed

REM Install project dependencies
echo.
echo Installing project dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto install_failed

REM Start application
echo.
echo [3/3] Starting Fleet Guardian...
echo ==========================================
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto app_failed

echo.
echo Fleet Guardian closed successfully.
pause
exit /b 0

:venv_failed
echo.
echo ERROR: Could not create the virtual environment.
pause
exit /b 1

:install_failed
echo.
echo ERROR: Dependency installation failed.
echo Check requirements.txt and your internet connection.
pause
exit /b 1

:app_failed
echo.
echo ERROR: Fleet Guardian stopped with an error.
pause
exit /b 1
