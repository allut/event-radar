#!/usr/bin/env bash
# Runs as `vscode` after container creation and after every Rebuild. Idempotent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> [1/5] git line-ending config"
# Host has core.autocrlf=true, so the worktree is CRLF while the index is LF;
# without this, `git status` in Linux reports every text file as modified.
# `input` converts on commit only -- it rewrites nothing on disk. NOTE: --local
# writes to .git/config, which is bind-mounted from the host -- this setting
# is NOT container-scoped and takes effect in your host repo too.
git config --local core.autocrlf input

echo "==> [2/5] node_modules volume ownership"
if [ ! -w frontend/node_modules ]; then
  sudo chown "$(id -u):$(id -g)" frontend/node_modules
fi

echo "==> [3/5] backend/.env"
# DATABASE_URL is injected as a container env var and outranks this file, so
# .env is only needed for SECRET_KEY. Never clobber an existing one -- it may
# hold real API keys.
if [ -f backend/.env ]; then
  echo "    backend/.env exists -- leaving it untouched"
else
  cp backend/.env.example backend/.env
  python - <<'PY'
import pathlib, secrets
p = pathlib.Path("backend/.env")
p.write_text(
    p.read_text(encoding="utf-8").replace(
        "SECRET_KEY=change-me-use-python-secrets-token-hex-32",
        f"SECRET_KEY={secrets.token_hex(32)}",
    ),
    encoding="utf-8",
)
PY
fi

echo "==> [4/5] dependencies"
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-dev.txt   # includes requirements.txt
npm --prefix frontend install

echo "==> [5/5] database migrations"
for _ in $(seq 1 30); do
  pg_isready -h db -U eventradar -q && break
  sleep 1
done
(cd backend && alembic upgrade head)

cat <<'EOF'

Dev container ready.
  Backend :  cd backend && uvicorn app.main:app --reload
  Frontend:  cd frontend && npm run dev
  Tests   :  (cd backend && pytest)   |   (cd frontend && npm test)
  Claude  :  config, plugins, skills, status line mirrored from host each start
  Anvil   :  put ANVIL_GEMINI_API_KEY / ANVIL_OPENAI_API_KEY in
             .devcontainer/anvil.env (gitignored) -- host keys are DPAPI-bound
EOF
