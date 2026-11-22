@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -3.13 -m venv .venv
  if errorlevel 1 (echo Could not create the .venv. Install Python 3.13 first. & pause & exit /b 1)
  echo Installing dependencies (first run only)...
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 (echo Dependency installation failed. Read the error above. & pause & exit /b 1)
)
.venv\Scripts\python.exe main.py %*
if errorlevel 1 pause
