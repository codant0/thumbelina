#!/usr/bin/env bash
# Start both backend and frontend dev servers concurrently.
# Usage: bash start.sh

set -e
trap 'kill 0' EXIT

echo "Starting backend (uvicorn)..."
cd "$(dirname "$0")"
uvicorn thumbelina.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "Starting frontend (vite)..."
cd "$(dirname "$0")/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop both servers."

wait
