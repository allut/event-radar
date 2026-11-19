# Event Radar

> AI-powered event discovery for Tallinn: a personalized **Daily 5** feed for every user, in Estonian, English or Russian.

Event Radar ingests events from Tallinn's ticketing platforms, venue sites and organizer submissions. It deduplicates and classifies them with an LLM, publishes the ones that pass a quality gate, and ranks five picks per user each morning. It runs on near-free managed infrastructure: the Render backend is the only paid line.

It's for people in Tallinn deciding what to do this week, and for the venues and promoters who want to reach them.

The backend is one FastAPI process with an embedded APScheduler, so there is no Celery or Redis. It runs on Render and talks to Neon Postgres. The React SPA runs on Cloudflare Pages, which proxies `/api/*` to the backend.

## Features

- **Daily 5:** five events picked for you each morning, in the app and as an email digest.
- **Personas:** rank up to three of nine personas at onboarding. Likes, dislikes and bookmarks keep retuning your ranking.
- **Explore:** search, filter and sort every upcoming event, signed in or not.
- **Saved events:** revisit everything you bookmarked, liked or disliked.
- **Three languages:** every screen, email and event summary in Estonian, English or Russian.
- **Passwordless sign-in:** a magic link by email, or Google.
- **Organizer portal:** venues and promoters submit and edit their own events, with images, saved venues and rich text.
- **Event claiming:** an organizer proves they are an event's Publisher, then edits the ingested event directly.
- **Promotions:** an organizer buys labelled Sponsored slots for an event they own, paid by card through Stripe. Organic ranking never changes.
- **Reports:** report an event's inappropriate content. An admin resolves it and emails you the outcome.
- **One-click unsubscribe:** stop the digest from the email itself, without signing in.
- **Admin console:** operators run the pipeline and work the dedup, submission, claim, report and promotion queues.
- **Light and dark themes:** follows your device theme, with a per-browser override.

## Tech stack

| Layer | Technologies |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy (async), Alembic, APScheduler, Pydantic Settings |
| Frontend | Vite, React, TypeScript, TanStack Query, React Router, CSS Modules, Tiptap |
| Database | Neon Postgres (asyncpg) |
| LLM | Groq, Cloudflare Workers AI, Mistral |
| Email | Resend |
| Payments | Stripe |
| Images | Cloudinary |
| Geocoding | Nominatim |
| Company lookup | Äriregister |
| SEO | Playwright prerender, Cloudflare Pages Functions, Cloudflare R2 |
| Logs | Axiom |
| Tests | pytest, Vitest, Testing Library |
| Hosting | Render (backend, Frankfurt) · Cloudflare Pages (frontend) · cron-job.org (SEO pings) |

## Getting started

Use the devcontainer unless you have a reason not to. It matches CI and needs no local Python, Node or Postgres.

> [!NOTE]
> LLM and email keys are optional locally. Without LLM keys, dedup keeps only its rule-based merges and classification fails, so nothing publishes and the feeds stay empty. Without `RESEND_API_KEY`, emails are logged instead of sent.

### Devcontainer

You need Docker Desktop (WSL2 backend on Windows) and the VS Code [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension.

1. **Free port 5432** if a host `db` container is running: `docker compose down`.
2. **Run *F1 → Dev Containers: Reopen in Container*.** `.devcontainer/post-create.sh` writes `backend/.env` with a generated `SECRET_KEY`, installs dependencies, enables `.githooks/` and runs `alembic upgrade head`.
3. **Wait for the dev servers.** `.devcontainer/post-start.sh` starts the backend on :8000 and the frontend on :5173 on every container start.
4. **Sign in** as described in [First sign-in](#first-sign-in).

Things to know inside the container:

- **The interpreter is `/opt/venv/bin/python`, already on `PATH`.** There is no venv to create or activate. If VS Code shows a stale host interpreter from Settings Sync, pick `/opt/venv/bin/python` once via *Python: Select Interpreter*.
- **Manage the servers with `bash .devcontainer/dev-server.sh`** and `status`, `restart`, `stop` or `logs backend|frontend`. Avoid an ad-hoc `npm run dev`: its watcher goes stale on the mounted workspace. Use `dev-server.sh run <backend|frontend>` for a foreground server.
- **Logs are in `/tmp/event-radar-dev/`.** The `logs: backend` and `logs: frontend` tasks tail them in a split panel. They auto-open once you run *Tasks: Allow Automatic Tasks* and reload the window.
- **`DATABASE_URL` comes from the container environment** and overrides `backend/.env`. The container's Postgres is a separate volume from the host's Compose `db`, so data doesn't carry over.
- **The scheduler is off (`ENABLE_SCHEDULER=false`).** A `--reload` server left running overnight can't arm scrapes, LLM spend or digest email. To run it for one session, `bash .devcontainer/dev-server.sh stop backend`, then run `ENABLE_SCHEDULER=true uvicorn app.main:app --reload` from `backend/`.
- **`gh` authenticates on start and attach** from the host's forwarded git credentials (`.devcontainer/gh-auth.sh`). If `gh auth status` is red, rerun that script or `gh auth login`.
- **The `claude` CLI signs in once, into a persistent named volume** separate from the host's `~/.claude`. `post-start.sh` refreshes it on each start, and `.devcontainer/sync-claude-config.sh` mirrors the host's Claude Code config in. The image installs RTK, so the host's RTK hook works too.
- **`.devcontainer/claude-plugins.json` lists container-only Claude Code plugins.** `sync-claude-config.sh` merges it into the container's `~/.claude/settings.json` on each start and never touches the host's config.
- **`.devcontainer/mem-watchdog.sh` is a manual diagnostic** for the intermittent "reload the VS Code window" hang.

### Native setup

You need Python 3.12, Node.js 24 (`NODE_VERSION` in `frontend/wrangler.toml`) and Postgres 16, ideally through Docker Compose.

1. **Clone, enable the git hooks and create `backend/.env`.** Paste the generated value in as `SECRET_KEY`. `DATABASE_URL` already points at the Compose Postgres, and `.env.example` lists optional service keys.

   ```bash
   git clone <repository-url> && cd event-radar
   git config core.hooksPath .githooks
   cp backend/.env.example backend/.env
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. **Start Postgres** with `docker compose up -d db`, and wait for `docker compose ps` to report it healthy.
3. **Migrate, then start the backend.**

   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt   # includes requirements.txt
   alembic upgrade head
   uvicorn app.main:app --reload   # http://localhost:8000
   ```

4. **Start the frontend** in a second terminal: `cd frontend && npm install && npm run dev`, then open http://localhost:5173.

- **Migrate before the first `uvicorn` start.** Startup seeds sources, personas and publishers but never migrates, so it crashes on missing tables.
- **A native Postgres needs contrib, and migrations need a superuser.** `alembic upgrade head` runs `CREATE EXTENSION` for `citext` and `pg_trgm`. Drop `?ssl=require` from a local `DATABASE_URL`. The Compose `postgres:16` image already covers all of this.
- **The backend serves `/health`, and `/docs` in development only.**

### First sign-in

Open http://localhost:5173 and request a magic link. Without `RESEND_API_KEY` no email is sent. Set `LOG_LEVEL=DEBUG` in `backend/.env`, restart the backend, and copy the `Dev-only magic link URL:` line from its log.

## Project structure

```
event-radar/
├── backend/            FastAPI app, Alembic migrations, pytest suite, ops scripts
├── frontend/           Vite + React SPA, Pages Functions, prerender scripts
├── shared/             cross-stack i18n, personas and config
├── scripts/            repo-wide dev scripts, including the shared/ codegen
├── .devcontainer/      devcontainer image and lifecycle scripts
├── .github/workflows/  CI and the dependency CVE audit
├── .githooks/          pre-commit checks and commit-message trimming
├── .claude/            Claude Code settings and hooks
├── .vscode/            dev-server and log tasks
├── docker-compose.yml  local Postgres 16
├── LICENSE             MIT
└── render.yaml         Render backend service
```

## Development

```bash
# Backend, from backend/
bash scripts/scratch-test.sh                 # all tests, against a throwaway database
bash scripts/scratch-test.sh tests/test_x.py # one file or node id
python -m ruff check . ../scripts            # lint
python -m mypy app ../scripts                # type-check
```

The frontend's commands are the `frontend/package.json` scripts: `dev`, `build`, `type-check`, `lint`, `test` and `test:coverage`.

- **CI runs ruff, mypy, eslint and type-check.** `.githooks/pre-commit` runs them on staged areas.
- **Shared values and translations live in `shared/`.** After an edit, run `python scripts/generate_shared.py` and commit the JSON and the regenerated `_generated/` files together.
- **Bump the version with `python scripts/bump_version.py [patch|minor|major]`** on `master`. The version lives in `frontend/package.json`. The script commits, tags `vX.Y.Z` and pushes `master` with the tag, so local commits not yet on `origin` go out too. `--help` lists the dry-run and no-push flags.
- **Running the pipeline locally:** with the scheduler off, the feed stays empty until you trigger the stages yourself. Sign in at `/admin/login` and run them from `/admin/pipeline`. Locally, either set `ADMIN_PASSWORD` and `ADMIN_TOTP_SECRET`, or set `ALLOW_INSECURE_DEV=true` and leave both unset.
- **Resetting event data:** `backend/scripts/reset_events.py` wipes events and pipeline state, dry run by default.

## Deployment

Production builds from the `release` branch, not `master`. `render.yaml` defines the backend service and `frontend/wrangler.toml` the Cloudflare Pages build.

## Agent docs

The engineering docs live on `local-docs`, a branch that exists only in the maintainer's clone and is never pushed. They cover the rules, architecture, domain glossary, ADRs, runbooks and roadmap. A clone from GitHub does not have this branch.

- **Start with `git show local-docs:CLAUDE.md`.** Its Documentation Map routes to every other doc by its path on that branch, such as `git show local-docs:docs/pipeline.md`.
- **List them with `git ls-tree -r --name-only local-docs`.**
- **Edit them in a worktree:** `git worktree add ../event-radar-docs local-docs`, then commit there.
- **`.githooks/pre-push` refuses to push the branch.**

## Roadmap

Planned work is tracked in [GitHub Issues](https://github.com/allut/event-radar/issues).

## License

Copyright (C) 2026 the Event Radar contributors.

- **Event Radar is licensed under the [MIT License](LICENSE).**
- **The license covers the code, not the Event Radar name or logo.** A fork runs under its own name.
