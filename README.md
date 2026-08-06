# What's on Radar

> AI-powered event discovery for Tallinn — a personalized **Daily 5** curated feed for every user.

What's on Radar ingests events from Tallinn's ticketing platforms, venue sites, and newsletters, then deduplicates and classifies them with an LLM and ranks them against each user's personas and feedback. The result is a tight, five-event daily digest instead of an endless listings page — delivered in **Estonian, English, or Russian**.

The whole platform is designed to run on **free-tier infrastructure** at a steady-state cost of $0/month.

## Features

- **Multi-source ingestion** — Fienta API, HTML listing scrapers (Piletilevi, KUMU, Estonia Concert Hall) sharing a common adapter, and inbound newsletter parsing via email webhook. A Nominatim geocoding backfill fills in venue coordinates that sources don't provide, a daily detail-refetch sync reconciles venue/price/coordinates against each event's source page, and per-locale page fetches capture localized `et`/`en`/`ru` titles and descriptions at ingest.
- **Two-stage deduplication** — a cheap SQL + fuzzy pre-filter narrows candidate pairs, then an LLM tiebreaker resolves only the survivors. Decisions are cached by content hash to avoid repeat LLM calls.
- **LLM classification** — assigns a fixed 14-category / 10-vibe taxonomy, a quality score, an explicit-content flag, a non-event flag, a parsed price range, and a localized 3-bullet "why go?" rationale, with a Groq → Cerebras → Mistral provider fallback chain.
- **3-layer NSFW filter** — a keyword prefilter at ingest time, an LLM-assigned explicit-content flag, and a publish gate that excludes flagged events from the published feed.
- **3-layer non-event filter** — the same pattern applied to gift cards/merch/webinars, so the published feed only surfaces real attendable events.
- **Publish gate** — classified events are promoted to `published` only once they clear a minimum quality score, pass the NSFW and non-event checks, pass a location check, haven't already ended, and (if geocoded) fall within the Tallinn region.
- **Persona-based personalization** — users rank 1–3 of 9 personas at onboarding (each pick weighted by position); like/dislike/bookmark signals continuously retune their ranking.
- **Daily 5 builder** — a scheduled job scores upcoming events and writes a diverse five-event feed per user each morning, then emails a digest.
- **Explore discovery grid** — a searchable, filterable (keyword, category/vibe, date, free-only, for-you), and sortable (relevance/date/price/quality) view over all upcoming published events, with an optional personalized ranking path.
- **Saved Events** — a dedicated page listing the events a user has liked, disliked, or bookmarked, grouped by signal.
- **Public landing showcase** — the only unauthenticated *list* read path: a fixed-size grid of top-quality published events happening this week, shown on `/` when signed out. No personalization, no PII. (Single-event detail, `GET /events/{id}`, is also public via optional auth.)
- **Organizer portal** — self-service event submission for venues/promoters: its own magic-link auth track (separate table, tokens, and signing salts from user auth), a submit/edit form with per-locale `et`/`en`/`ru` text and an organizer-chosen category, signed Cloudinary image upload, a per-account daily submission cap, and auto-publish through the normal publish gate with a post-hoc admin review queue.
- **Magic-link auth** — passwordless sign-in with short-lived, single-use links and revocable 2-day session tokens. No third-party auth provider.
- **Email digest opt-out** — one-click unsubscribe (RFC 8058 `List-Unsubscribe` header + a token-signed no-login page with an Undo/resubscribe button) toggles the daily digest without a sign-in.
- **Static pages** — a globally mounted site footer links to localized Privacy and Terms pages plus a Contact form (email-only delivery, honeypot + rate limit, no login).
- **Full trilingual i18n** — every UI string, email, and LLM output supports `et` / `en` / `ru` from a single shared source of truth.
- **Security-hardened** — OWASP Top 10 mitigations: per-IP rate limiting, strict security headers, CORS lockdown, external-URL sanitization, and a CVE audit in CI.
- **Data retention** — a weekly cleanup prunes aged satellite/audit rows (auth tokens, raw ingestion payloads, old feed snapshots, cached scores) while preserving all event history and user feedback indefinitely.

## Architecture

```
Vite + React SPA  ──HTTPS / JSON──▶  FastAPI (single process)
                                       ├── Routers: /auth /admin /onboarding /events /explore
                                       │            /feed /feedback /public /users/me /contact
                                       │            /email /webhooks
                                       │            /organizer/auth /organizer/events
                                       └── APScheduler (embedded, kept warm by a cron-job.org ping)
                                           ├── Weekly Sun 03:00: sync_fienta_organizers
                                           ├── Weekly Sun 03:30: cleanup_stale_data
                                           ├── Hourly:    ingest_all_enabled
                                           ├── 6-hourly:  dedup_pass + classify_pending +
                                           │              publish_pending + geocode_pending
                                           ├── 04:30 EET: refetch_event_details
                                           ├── 06:00 EET: build_daily_feeds
                                           └── 07:00 EET: send_daily_digests
                                             ↓
                                   Neon Postgres (eu-central-1, pgvector-ready)
                                             ↓
                                 LLM Router: Groq → Cerebras → Mistral
```

There is intentionally **no Celery/Redis** — an embedded APScheduler is sufficient for a single-process MVP. On free-tier hosting the process sleeps when idle, so an external scheduled ping (cron-job.org) hits `/internal/tick` every 10 minutes to keep the scheduler alive.

The processing pipeline:

```
fetch → raw_events → normalize → dedup → events(draft) → classify → events(classified) → publish gate → events(published) → rank → daily_feeds → digest
```

Geocoding runs as a separate backfill alongside this pipeline, filling in `lat`/`lng` for events that have a venue address but no coordinates.

## Tech stack

| Layer       | Technologies |
|-------------|--------------|
| Backend     | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, APScheduler, Pydantic Settings |
| Frontend    | Vite, React 18, TypeScript, TanStack Query, React Router, CSS Modules, Vitest + Testing Library |
| Database    | Neon Postgres (async via `asyncpg`) |
| LLM         | Groq (primary), Cerebras, Mistral (fallback chain) |
| Email       | Resend (magic links, daily digests, contact-form relay, inbound newsletter webhook) |
| Images      | Cloudinary (signed server-side upload for organizer-submitted event images) |
| Hosting     | Render (backend web service) · Vercel (frontend) · cron-job.org (keepalive ping) |

## Getting started

### Prerequisites

- **Python 3.12**
- **Node.js 20.19+** (or 22.12+) and npm — required by Vite 8 / Vitest 4
- A **PostgreSQL** database — [Docker Compose](#2-set-up-the-database) is the recommended local path (see below); a free [Neon](https://neon.tech) project also works out of the box for production-like testing.

> [!NOTE]
> External API keys (Groq/Cerebras/Mistral for LLM, Resend for email) are **optional for local development**. Without them, classification degrades gracefully to a rule-only dedup pass and emails are logged to the console instead of being sent. Provide them when you want the full pipeline.

### Option 0 — VS Code Dev Container (recommended on Windows)

One-click Python 3.12 + Node 20 + Postgres 16, matching CI exactly — no local venv, no Windows/Linux `node_modules` conflicts.

Prerequisites: Docker Desktop (WSL2 backend) and the VS Code [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension.

```bash
docker compose down   # free port 5432 if a host `db` container is already running
```

Then **F1 → Dev Containers: Reopen in Container**. `postCreateCommand` (`.devcontainer/post-create.sh`) handles venv creation, `pip install`, `npm install`, and `alembic upgrade head` automatically — skip step 1 and step 3's venv/install lines below. Once it finishes:

```bash
cd backend && uvicorn app.main:app --reload   # terminal 1
cd frontend && npm run dev                     # terminal 2
```

Notes:
- `DATABASE_URL` comes from the container environment and overrides `backend/.env` — no `.env` edit needed for the database.
- The container's Postgres is a **separate volume** from the host's `docker-compose.yml` `db` service; data doesn't carry over automatically.
- The interpreter is always `/opt/venv/bin/python` — no activation step, ever.
- The embedded scheduler is **off** in the container (`ENABLE_SCHEDULER=false`) so `uvicorn --reload` left running overnight can't arm hourly scrapes, real LLM spend, or a real digest send. Run `ENABLE_SCHEDULER=true uvicorn app.main:app --reload` for one session to exercise the real cadence. With it off, `GET /feed` stays empty until you run `POST /admin/build-feeds` — that's expected, not a bug.

Skip to [Development](#development) once both servers are up. The steps below are for running natively instead.

### 1. Clone and configure

```bash
git clone <repository-url>
cd event-radar
```

Create the backend environment file from the template:

```bash
cd backend
cp .env.example .env
```

`backend/.env` now defaults to a local Postgres `DATABASE_URL` matching the Docker Compose service below, so no edit is needed there. Set at minimum:

- `SECRET_KEY` — a random secret; generate one with `python -c "import secrets; print(secrets.token_hex(32))"`

Optionally add `GROQ_API_KEY` / `CEREBRAS_API_KEY` / `MISTRAL_API_KEY` and `RESEND_API_KEY` to enable LLM classification and real email delivery. See `.env.example` for the full list of overridable settings (data sources, persona vectors, admin auth, CORS).

> [!IMPORTANT]
> If you already have a `backend/.env` from before, pointing at a shared Neon database, change its `DATABASE_URL` to the local form shown in `.env.example` — otherwise you'll keep hitting the shared remote DB instead of your local one.

### 2. Set up the database

**Option A — Docker Compose (recommended):**

```bash
docker compose up -d db      # starts local Postgres on :5432
docker compose ps            # wait for db to report "healthy"
```

Credentials and DB name already match the local `DATABASE_URL` in `.env.example`, so no further `.env` edit is needed. The official `postgres:16` image bundles the `citext` and `pg_trgm` extensions the migrations need and runs as superuser, so `CREATE EXTENSION` succeeds with no extra setup.

**Option B — native install (fallback):** install Postgres **with contrib** (the Windows EDB installer includes it), then `createdb eventradar`. Point `DATABASE_URL` at your local instance (no `?ssl=require`). Run migrations as a **superuser role** (e.g. `postgres`) — `alembic upgrade head` issues `CREATE EXTENSION citext` / `pg_trgm`, which a non-privileged role can't do.

### 3. Run the backend

```bash
cd backend

# Create and activate a virtual environment (venv is gitignored).
python -m venv venv
venv\Scripts\Activate.ps1      # Windows PowerShell
# venv\Scripts\activate.bat    # Windows cmd
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
alembic upgrade head            # apply database migrations — do this before uvicorn
uvicorn app.main:app --reload   # dev server on http://localhost:8000
```

The app seeds personas and ingestion sources automatically on startup, but does **not** run migrations — `alembic upgrade head` must complete first or startup will crash on missing tables. Once running:

- Health check: http://localhost:8000/health
- Interactive API docs (development only): http://localhost:8000/docs

### 4. Run the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev                     # dev server on http://localhost:5173
```

The Vite dev server proxies `/api` requests to the backend at `http://localhost:8000`, so no frontend env vars are needed for local development.

Open http://localhost:5173 and sign in with a magic link. Without `RESEND_API_KEY` configured, the magic link is printed to the backend console — copy the URL from there to complete sign-in.

## Project structure

```
event-radar/
├── .devcontainer/             # VS Code Dev Container (Python 3.12 + Node 20 + Postgres 16)
├── backend/                  # FastAPI application
│   ├── app/
│   │   ├── routers/          # /auth /admin /onboarding /events /explore /feed /feedback /public /users/me /contact /email /webhooks /organizer/auth /organizer/events
│   │   ├── ingestion/        # source adapters (Fienta, HTML listings, newsletter), geocoding backfill, detail-refetch sync, organizer sync
│   │   ├── dedup/            # rule-based pre-filter + LLM tiebreaker
│   │   ├── llm/              # provider router, classifier, taxonomy, extractor
│   │   ├── ranking/          # scoring + Daily 5 builder
│   │   ├── email/            # digest / magic-link / contact styles / templates / delivery
│   │   ├── auth/             # magic-link tokens + email
│   │   ├── models/           # SQLAlchemy models
│   │   ├── _generated/       # generated constants & i18n (do not edit by hand)
│   │   ├── constants.py      # single source of truth for backend literals
│   │   ├── config.py         # environment settings
│   │   ├── publish.py        # publish gate (classified → published)
│   │   ├── cleanup.py        # weekly data-retention pruning
│   │   ├── rate_limit.py     # slowapi per-IP limiter
│   │   └── main.py           # app wiring, middleware, scheduler
│   ├── alembic/             # migrations
│   ├── scripts/             # one-off operational scripts (reset_events.py)
│   └── tests/               # pytest suite
├── frontend/                 # Vite + React SPA
│   ├── vercel.json           # Vercel rewrites (/api proxy + SPA fallback) + security headers
│   └── src/
│       ├── routes/          # Landing, Login, AuthVerify, Onboarding, Feed, Explore, SavedEvents, EventDetail, Settings, Unsubscribe, Privacy, Terms, Contact, NotFound + organizer portal (OrganizerLogin, OrganizerVerify, OrganizerDashboard, EventSubmit)
│       ├── components/      # EventCard, PersonaCard, TopBar, OrganizerTopBar, form controls, shared CSS base classes ...
│       ├── hooks/           # useAuth, useFeedback, useDropdown, useOrganizerAuth ...
│       ├── lib/             # auth token/locale storage + auth-state store (auth.ts, organizerAuth.ts)
│       ├── api/             # API client (user + organizer wrappers)
│       ├── content/legal/   # localized Privacy/Terms documents
│       ├── _generated/      # generated constants & i18n (do not edit by hand)
│       └── i18n.ts          # i18n helpers
├── shared/                   # cross-stack source of truth (i18n, personas, config, calendar)
├── docs/observability.md     # shipped log shape + Axiom monitor queries
├── scripts/generate_shared.py# regenerates the _generated/ files in both stacks
├── docker-compose.yml        # local Postgres 16
├── .github/workflows/        # CI: pytest + Vitest, weekly dependency CVE audit
└── render.yaml               # Render deployment (backend web service)
```

## Development

### Common commands

```bash
# Backend
cd backend
pytest                                          # run all tests
pytest tests/path/test_foo.py::TestClass::test  # run a single test
python -m ruff check .                           # lint (Ruff)
python -m mypy app                               # type-check (mypy, requirements-dev.txt)

# Frontend
cd frontend
npm run build       # type-check + production build
npm run type-check  # TypeScript check only
npm run lint        # ESLint
npm test            # run all tests (Vitest)
npm run test:watch  # watch mode
npm run test:coverage # coverage report
```

Both suites also run in CI (`.github/workflows/tests.yml`) on every push/PR to `master`, alongside a weekly `pip-audit` + `npm audit` CVE sweep (`.github/workflows/dependency-audit.yml`).

### Editing shared values & translations

Strings, taxonomies, persona definitions, and cross-stack scalars live in `shared/`. After editing any file there, regenerate the per-stack `_generated/` files and commit both:

```bash
python scripts/generate_shared.py
```

> [!IMPORTANT]
> Never edit files under `_generated/` directly. A test (`backend/tests/test_generated_sync.py`) fails if the generated output drifts from `shared/`.

### Manually triggering pipeline jobs (E2E testing)

The scheduled jobs described in [Architecture](#architecture) (`sync_fienta_organizers`, `cleanup_stale_data`, `ingest_all_enabled`, `dedup_pass`, `classify_pending`, `publish_pending`, `build_daily_feeds`, `send_daily_digests`, `geocode_pending`, `refetch_event_details`) can each be run on demand via `/admin/*` endpoints — useful for exercising the full pipeline end to end without waiting for the schedule.

All `/admin/*` endpoints require HTTP Basic auth (`ADMIN_USERNAME` / `ADMIN_PASSWORD`, see `.env.example`). In development with no `ADMIN_PASSWORD` set, any credentials are accepted — the examples below use `admin:admin`. Run them in this order to exercise a full pipeline cycle:

```bash
# 1. sync_fienta_organizers — discover/refresh Fienta organizer IDs
curl -u admin:admin -X POST http://localhost:8000/admin/sync-organizers

# 2. ingest_all_enabled — fetch raw events from every enabled source
curl -u admin:admin http://localhost:8000/admin/ingest

# 3. dedup_pass — rule pre-filter + LLM tiebreaker over non-cancelled events
curl -u admin:admin -X POST http://localhost:8000/admin/dedup

# 4. classify_pending — LLM classification for one batch of draft events
curl -u admin:admin -X POST http://localhost:8000/admin/classify

# 5. publish_pending — promote qualifying classified events to published
curl -u admin:admin -X POST http://localhost:8000/admin/publish

# 6. build_daily_feeds — score events and write daily_feeds for all users
curl -u admin:admin -X POST http://localhost:8000/admin/build-feeds

# 7. send_daily_digests — dry-run by default (counts would-send, sends nothing)
curl -u admin:admin -X POST http://localhost:8000/admin/send-digests
# Pass dry_run=false to actually deliver emails:
curl -u admin:admin -X POST "http://localhost:8000/admin/send-digests?dry_run=false"

# geocode_pending — backfill lat/lng for events missing coordinates (runs standalone,
# not part of pipeline/run; safe to invoke any time)
curl -u admin:admin -X POST http://localhost:8000/admin/geocode

# refetch_event_details — re-fetch each future event's source detail page and
# reconcile venue/price/coordinates (runs standalone, not part of pipeline/run)
curl -u admin:admin -X POST http://localhost:8000/admin/refetch

# cleanup_stale_data — prune aged satellite/audit rows (auth tokens, raw payloads,
# old feed snapshots, cached scores); never deletes events. Dry-run by default
# (counts candidates, deletes nothing); runs standalone, not part of pipeline/run.
curl -u admin:admin -X POST http://localhost:8000/admin/cleanup
# Pass dry_run=false to actually delete:
curl -u admin:admin -X POST "http://localhost:8000/admin/cleanup?dry_run=false"
```

> [!TIP]
> `POST /admin/pipeline/run` runs all seven stages above in dependency order in a single call, stopping at the first failure — the fastest way to drive a full E2E cycle. It also accepts `?dry_run=false` for the final digest stage. `GET /admin/stats` and `GET /admin/dedup/groups` are useful for inspecting the results afterwards; `GET /admin/submissions` (plus `POST /admin/submissions/{event_id}/approve` and `.../retract`) is the post-hoc review queue for organizer-submitted events. The geocoding backfill (`geocode_pending`), the detail-refetch sync (`refetch_event_details`), and the data-retention cleanup (`cleanup_stale_data`) each run on their own schedule and are not part of `pipeline/run`; trigger them on demand via `POST /admin/geocode`, `POST /admin/refetch`, and `POST /admin/cleanup` respectively. Run `refetch` before `geocode` if you want coordinates cleared by an address change re-resolved in the same operation.

### Resetting event data

`backend/scripts/reset_events.py` wipes **all** event and pipeline data and resets auto-increment IDs to 1 — useful for clearing out test/bad ingested data and starting the pipeline from a clean slate. It truncates the event, raw-event, source-link, classification, feedback, score, daily-feed, ingestion-run, LLM-call, and inbound-email tables (`RESTART IDENTITY CASCADE`), then resets each source's last-run state so ingestion re-fetches everything. **Users, personas, and the source registry are preserved.**

```bash
cd backend                              # with the venv active
python scripts/reset_events.py          # dry run: prints target DB + per-table row counts
python scripts/reset_events.py --yes    # actually truncate
```

> [!WARNING]
> The `--yes` truncate is permanent and cannot be undone. The dry run (no flag) prints the masked `DATABASE_URL` it would hit and the current row counts — check that the target is the DB you expect before passing `--yes`.

## Deployment

Production runs entirely on free tiers, split across three services:

- **Backend — Render web service** (`render.yaml`): `rootDir: backend`, health check on `/health`. Migrations run on every boot — `startCommand` chains `alembic upgrade head && uvicorn ...`, since Render's `preDeployCommand` is paid-only. Set `DATABASE_URL` (asyncpg form: `postgresql+asyncpg://user:pass@host/db?ssl=require`), `ADMIN_PASSWORD`, `INTERNAL_TOKEN`, the LLM keys (`GROQ_API_KEY`, optionally `CEREBRAS_API_KEY` / `MISTRAL_API_KEY`), `RESEND_API_KEY`, `RESEND_FROM_ADDRESS`, `CONTACT_TO_ADDRESS`, `RESEND_WEBHOOK_SECRET`, `CORS_ORIGINS`, `FRONTEND_URL`, `BACKEND_URL` (the API's own absolute URL, e.g. `https://event-radar-api.onrender.com` — needed by the digest's server-side-fetched `List-Unsubscribe` header), and the Cloudinary trio `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` (organizer image upload; the endpoint returns 501 when unset). `SECRET_KEY` is auto-generated. Optionally set `LOG_SHIP_URL` (+ `LOG_SHIP_TOKEN`) to ship JSON logs to an external drain such as Axiom.
- **Frontend — Vercel** (`frontend/vercel.json`): static Vite build (`npm run build`, output `dist`). The API client issues all requests against a relative `/api` prefix (`frontend/src/api/client.ts`), so a Vercel rewrite proxies `/api/:path*` to the Render URL **and strips the `/api` prefix** (backend routes have no `/api` prefix — this mirrors the dev Vite proxy); a second rewrite provides the SPA fallback to `index.html` for React Router routes. Same-origin proxying also avoids CORS entirely. No build-time API env var is used.
- **Keepalive — cron-job.org**: Render's free tier sleeps after 15 minutes idle, which would stop the embedded APScheduler. A [cron-job.org](https://cron-job.org) job pings `https://event-radar-api.onrender.com/internal/tick` every 10 minutes with the `X-Internal-Token` header set to the same value as Render's `INTERNAL_TOKEN`. (Render's own cron jobs are paid; GitHub Actions cron proved too imprecise for a keepalive cadence.)

## Documentation

- **[CLAUDE.md](CLAUDE.md)** — engineering conventions and codebase guidance.
- **[docs/observability.md](docs/observability.md)** — shipped log-record shape, the `event` taxonomy, and the APL queries behind each Axiom monitor.
- **[shared/README.md](shared/README.md)** — the cross-stack shared/generated files and their workflow.
