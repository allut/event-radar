#!/usr/bin/env bash
# Service manager for the backend/frontend dev servers. Invoked from the
# container lifecycle (.devcontainer/post-start.sh, `start`) and from
# .vscode/tasks.json (`run`, foreground/Ctrl-C-able).
#
# Usage:
#   dev-server.sh start   [backend|frontend]   # detached; default = both
#   dev-server.sh stop    [backend|frontend]
#   dev-server.sh restart [backend|frontend]
#   dev-server.sh status
#   dev-server.sh run     <backend|frontend>   # foreground exec
#   dev-server.sh logs    <backend|frontend>   # foreground tail -F
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_ROOT
cd "$REPO_ROOT"

# Container-local, not the 9p Windows bind mount -- logs are append-heavy.
STATE_DIR="/tmp/event-radar-dev"
mkdir -p "$STATE_DIR"

port_is_bound() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

port_for() {
  case "$1" in
    backend) echo 8000 ;;
    frontend) echo 5173 ;;
  esac
}

pid_file_for() {
  echo "$STATE_DIR/$1.pid"
}

log_file_for() {
  echo "$STATE_DIR/$1.log"
}

svc_command() {
  case "$1" in
    backend)
      # Wait for Postgres before exec'ing -- runs inside the detached child,
      # so `start` itself never blocks on the DB.
      for _ in $(seq 1 30); do
        pg_isready -h db -U eventradar -q && break
        sleep 1
      done
      cd "$REPO_ROOT/backend"
      exec uvicorn app.main:app --reload
      ;;
    frontend)
      cd "$REPO_ROOT"
      exec npm --prefix frontend run dev
      ;;
  esac
}

run_service() {
  local svc="$1"
  local port
  port="$(port_for "$svc")"
  if [ -z "$port" ]; then
    echo "usage: dev-server.sh run <backend|frontend>"
    exit 1
  fi
  if port_is_bound "$port"; then
    echo "port $port already served -- leaving it alone"
    exit 0
  fi
  svc_command "$svc"
}

logs_service() {
  local svc="$1"
  local log_file
  log_file="$(log_file_for "$svc")"
  if [ -z "$(port_for "$svc")" ]; then
    echo "usage: dev-server.sh logs <backend|frontend>"
    exit 1
  fi
  # The tail may start before the server has ever written the file.
  touch "$log_file"
  # -F (not -f) survives start_service's truncating redirect on restart.
  exec tail -n 200 -F "$log_file"
}

start_service() {
  local svc="$1"
  local port pid_file log_file
  port="$(port_for "$svc")"
  pid_file="$(pid_file_for "$svc")"
  log_file="$(log_file_for "$svc")"

  if port_is_bound "$port"; then
    echo "$svc: port $port already served -- leaving it alone"
    return 0
  fi

  # setsid detaches from the postStartCommand's docker exec, which exits
  # immediately once the lifecycle script returns.
  setsid nohup bash -c "$(declare -f svc_command); svc_command '$svc'" \
    >"$log_file" 2>&1 &
  echo $! >"$pid_file"
  echo "$svc: starting (pid $!, log $log_file)"
}

stop_service() {
  local svc="$1"
  local pid_file
  pid_file="$(pid_file_for "$svc")"

  if [ ! -f "$pid_file" ]; then
    echo "$svc: no pid file -- nothing to stop"
    return 0
  fi

  local pid port
  pid="$(cat "$pid_file")"
  port="$(port_for "$svc")"
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    # Wait for the port to actually free up -- a subsequent `start` checks
    # port_is_bound immediately, and the listening socket can outlive the
    # TERM signal by a beat (uvicorn --reload shutdown, vite teardown).
    for _ in $(seq 1 20); do
      port_is_bound "$port" || break
      sleep 0.5
    done
    echo "$svc: stopped (pid $pid)"
  else
    echo "$svc: pid $pid not running"
  fi
  rm -f "$pid_file"
}

status_service() {
  local svc="$1"
  local port pid_file log_file
  port="$(port_for "$svc")"
  pid_file="$(pid_file_for "$svc")"
  log_file="$(log_file_for "$svc")"

  local bound="not bound"
  port_is_bound "$port" && bound="bound"

  local pid="none"
  [ -f "$pid_file" ] && pid="$(cat "$pid_file")"

  echo "$svc: port $port $bound, pid $pid, log $log_file"
}

services_for() {
  # Prints the service list on stdout; returns non-zero on an invalid arg
  # instead of exiting, since this always runs inside a $(...) subshell.
  case "${1:-}" in
    backend|frontend) echo "$1" ;;
    "") echo "backend frontend" ;;
    *) return 1 ;;
  esac
}

case "${1:-}" in
  start)
    svcs="$(services_for "${2:-}")" || { echo "usage: dev-server.sh start [backend|frontend]"; exit 1; }
    for svc in $svcs; do
      start_service "$svc"
    done
    ;;
  stop)
    svcs="$(services_for "${2:-}")" || { echo "usage: dev-server.sh stop [backend|frontend]"; exit 1; }
    for svc in $svcs; do
      stop_service "$svc"
    done
    ;;
  restart)
    svcs="$(services_for "${2:-}")" || { echo "usage: dev-server.sh restart [backend|frontend]"; exit 1; }
    for svc in $svcs; do
      stop_service "$svc"
      start_service "$svc"
    done
    ;;
  status)
    for svc in backend frontend; do
      status_service "$svc"
    done
    ;;
  run)
    case "${2:-}" in
      backend|frontend) run_service "$2" ;;
      *)
        echo "usage: dev-server.sh run <backend|frontend>"
        exit 1
        ;;
    esac
    ;;
  logs)
    case "${2:-}" in
      backend|frontend) logs_service "$2" ;;
      *)
        echo "usage: dev-server.sh logs <backend|frontend>"
        exit 1
        ;;
    esac
    ;;
  *)
    echo "usage: dev-server.sh start|stop|restart|status|run|logs [backend|frontend]"
    exit 1
    ;;
esac
