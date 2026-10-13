@echo off
rem Backend startup (Windows): creates a venv on first run, installs deps, starts the API.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv || exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install -q -r requirements.txt || exit /b 1

if not exist ".env" (
  echo.
  echo !! No backend\.env found. Copy .env.example to .env and set LOGVIEWER_ROOT first:
  echo      copy .env.example .env
  echo.
  exit /b 1
)

echo Starting backend on http://127.0.0.1:8000 ...
uvicorn app.main:app --reload --port 8000
