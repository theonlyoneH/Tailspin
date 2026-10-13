#!/usr/bin/env bash
# Frontend startup: installs deps on first run, starts the dev server.
set -e
cd "$(dirname "$0")"

if [ ! -d "node_modules" ]; then
  echo "Installing frontend dependencies..."
  npm install
fi

echo "Starting frontend on http://localhost:5173 ..."
npm run dev
