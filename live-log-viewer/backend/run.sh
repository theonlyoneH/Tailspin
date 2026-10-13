#!/usr/bin/env bash
# Backend startup: creates a venv on first run, installs deps, starts the API.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  echo ""
  echo "!! No backend/.env found. Copy .env.example to .env and set LOGVIEWER_ROOT first:"
  echo "     cp .env.example .env"
  echo ""
  exit 1
fi

echo "Starting backend on http://127.0.0.1:8000 ..."
uvicorn app.main:app --reload --port 8000
