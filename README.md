# Event Radar

> AI-powered event discovery for Tallinn: a personalized **Daily 5** feed for every user, in Estonian, English or Russian.

Event Radar ingests events from Tallinn's ticketing platforms, venue sites and organizer submissions. It deduplicates and classifies them with an LLM, publishes the ones that pass a quality gate, and ranks five picks per user each morning. It runs on near-free managed infrastructure: the Render backend is the only paid line.

How the pieces fit is in [CLAUDE.md's Architecture](CLAUDE.md#architecture) and [docs/pipeline.md](docs/pipeline.md).

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
- **Reports:** flag an event's content. An admin reviews it and emails you the outcome.
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
2. **Run *F1 → Dev Containers: Reopen in Container*.** `.devcontainer/post-create.sh` writes `backend/.env` with a generated `SECRET_KEY`, installs dependencies and runs `alembic upgrade head`.
3. **Wait for the dev servers.** `.devcontainer/post-start.sh` starts the backend on :8000 and the frontend on :5173 on every container start.
4. **Sign in** as described in [First sign-in](#first-sign-in).

Things to know inside the container:

- **The interpreter is `/opt/venv/bin/python`, already on `PATH`.** There is no venv to create or activate. If VS Code shows a stale host interpreter from Settings Sync, pick `/opt/venv/bin/python` once via *Python: Select Interpreter*.
- **Manage the servers with `bash .devcontainer/dev-server.sh`** and `status`, `restart`, `stop` or `logs backend|frontend`. Avoid an ad-hoc `npm run dev`: its watcher goes stale on the mounted workspace. Use `dev-server.sh run <backend|frontend>` for a foreground server.
- **Logs are in `/tmp/event-radar-dev/`.** The `logs: backend` and `logs: frontend` tasks tail them in a split panel. They auto-open once you run *Tasks: Allow Automatic Tasks* and reload the window.
- **`DATABASE_URL` comes from the container environment** and overrides `backend/.env`. The container's Postgres is a separate volume from the host's Compose `db`, so data doesn't carry over.
- **The scheduler is off (`ENABLE_SCHEDULER=false`).** A `--reload` server left running overnight can't arm scrapes, LLM spend or digest email. To run it for one session, `bash .devcontainer/dev-server.sh stop backend`, then run `ENABLE_SCHEDULER=true uvicorn app.main:app --reload` from `backend/`.
- **`gh` authenticates on start and attach** from the host's forwarded git credentials (`.devcontainer/gh-auth.sh`). If `gh auth status` is red, rerun that script or `gh auth login`.
- **The `claude` CLI signs in once, into a persistent named volume** separate from the host's `~/.claude`. `post-start.sh` refreshes it on each start, and `.devcontainer/sync-claude-config.sh` mirrors in the host's settings, hooks, commands, plugins and status line. Skills come in through a read-only bind mount. The image installs RTK, so the host's RTK hook works too.
- **`.devcontainer/claude-plugins.json` lists container-only Claude Code plugins.** `sync-claude-config.sh` merges it into the container's `~/.claude/settings.json` on each start and never touches the host's config.
- **`.devcontainer/mem-watchdog.sh` is a manual diagnostic** for the intermittent "reload the VS Code window" hang. It isn't part of the normal dev loop.

### Native setup

You need Python 3.12, Node.js 24 (`NODE_VERSION` in `frontend/wrangler.toml`) and Postgres 16, ideally through Docker Compose.

1. **Clone and create `backend/.env`.** Paste the generated value in as `SECRET_KEY`. `DATABASE_URL` already points at the Compose Postgres, and `.env.example` lists the optional LLM and email keys.

   ```bash
   git clone <repository-url> && cd event-radar
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

> [!IMPORTANT]
> An older `backend/.env` may still point `DATABASE_URL` at a shared Neon database. Switch it to the local form in `.env.example`, or you'll keep working against the remote DB.

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
├── scripts/            generate_shared.py (regenerates _generated/ files), linearize-branch.py
├── docs/               deep-dive docs, ADRs, agent workflow docs
├── .devcontainer/      devcontainer image and lifecycle scripts
├── .github/workflows/  CI (lint, tests, migrations) and the dependency CVE audit
├── CLAUDE.md           engineering rules and the Documentation Map
├── CONTEXT.md          domain glossary
├── docker-compose.yml  local Postgres 16
├── render.yaml         Render backend service
└── VERSION             current release version
```

## Development

- **Day-to-day commands are in [CLAUDE.md's Commands](CLAUDE.md#commands):** tests, lint, type-check and build for both stacks. Read its [Traps](CLAUDE.md#traps) before your first commit.
- **Shared values and translations live in `shared/`.** After an edit, run `python scripts/generate_shared.py` and commit both sides. See [shared/README.md](shared/README.md).
- **Running the pipeline locally:** with the scheduler off, the feed stays empty until you trigger the stages yourself. Sign in at `/admin/login` and run them from `/admin/pipeline`. Locally, either set `ADMIN_PASSWORD` and `ADMIN_TOTP_SECRET`, or set `ALLOW_INSECURE_DEV=true` and leave both unset.
- **Resetting event data:** `backend/scripts/reset_events.py` wipes events and pipeline state, dry run by default. See [docs/backend-ops.md](docs/backend-ops.md)'s Maintenance Scripts section.

## Deployment

Production builds from the `release` branch, not `master`. Topology, secrets and scheduled jobs are in [docs/backend-ops.md](docs/backend-ops.md).

## Documentation

[CLAUDE.md's Documentation Map](CLAUDE.md#documentation-map) routes to every deep-dive doc in `docs/`. The domain glossary is [CONTEXT.md](CONTEXT.md), architecture decisions are in [docs/adr/](docs/adr/), and the shared-file workflow is in [shared/README.md](shared/README.md).
