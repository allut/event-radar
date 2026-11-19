#!/usr/bin/env bash
# Run pytest against a throwaway Postgres database, never the dev one.
# Usage (from anywhere): bash backend/scripts/scratch-test.sh [--no-db] [pytest args]
# Test paths may be relative to backend/ (tests/...) or to the repo root (backend/tests/...).
# --no-db skips creating and migrating the database, for tests that never touch one
# (tests/test_move_to_shared.py). DATABASE_URL still names a scratch database, so conftest
# keeps refusing the dev one, but that database does not exist.
set -euo pipefail

cd "$(dirname "$0")/.."

NO_DB=false
if [[ "${1:-}" == "--no-db" ]]; then
  NO_DB=true
  shift
fi

FULL_URL="${DATABASE_URL:-postgresql+asyncpg://eventradar:eventradar@localhost:5432/eventradar}"
BASE_URL="${FULL_URL%%\?*}"
QUERY=""
[[ "$FULL_URL" == *\?* ]] && QUERY="?${FULL_URL#*\?}"
SCRATCH_DB="eventradar_scratch_$$"
PG_URL="${BASE_URL/+asyncpg/}"
ADMIN_URL="${PG_URL%/*}/postgres${QUERY/ssl=/sslmode=}"

cleanup() { [[ "$NO_DB" == true ]] || psql "$ADMIN_URL" -qc "DROP DATABASE IF EXISTS ${SCRATCH_DB} WITH (FORCE)" || true; }
trap cleanup EXIT

[[ "$NO_DB" == true ]] || psql "$ADMIN_URL" -qc "CREATE DATABASE ${SCRATCH_DB}"

# The shell value beats backend/.env, so export both for alembic and pytest.
export DATABASE_URL="${BASE_URL%/*}/${SCRATCH_DB}${QUERY}"
export SECRET_KEY="${SECRET_KEY:-scratch-test-secret-not-for-production-32chars}"

# Migration chatter buries the pytest summary; show it only when the upgrade fails.
MIGRATE_LOG="$(mktemp)"
trap 'rm -f "$MIGRATE_LOG"; cleanup' EXIT
if [[ "$NO_DB" != true ]]; then
  alembic upgrade head >"$MIGRATE_LOG" 2>&1 || { cat "$MIGRATE_LOG"; exit 1; }
fi
# Paths are relative to backend/; accept repo-root ones (backend/tests/...) too.
python -m pytest "${@#backend/}"
