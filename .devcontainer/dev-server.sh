#!/usr/bin/env bash
# Guarded launcher for the backend/frontend dev servers, invoked by
# .vscode/tasks.json on folderOpen. Usage: bash .devcontainer/dev-server.sh <backend|frontend>
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

port_is_bound() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

case "${1:-}" in
  backend)
    PORT=8000
    if port_is_bound "$PORT"; then
      echo "port $PORT already served -- leaving it alone"
      exit 0
    fi
    cd backend
    exec uvicorn app.main:app --reload
    ;;
  frontend)
    PORT=5173
    if port_is_bound "$PORT"; then
      echo "port $PORT already served -- leaving it alone"
      exit 0
    fi
    exec npm --prefix frontend run dev
    ;;
  *)
    echo "usage: dev-server.sh <backend|frontend>"
    exit 1
    ;;
esac
