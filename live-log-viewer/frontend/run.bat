@echo off
rem Frontend startup (Windows): installs deps on first run, starts the dev server.
setlocal
cd /d "%~dp0"

if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install || exit /b 1
)

echo Starting frontend on http://localhost:5173 ...
call npm run dev
