# What's on Radar

> AI-powered event discovery for Tallinn — a personalized **Daily 5** curated feed for every user.

What's on Radar ingests events from Tallinn's ticketing platforms, venue sites, and newsletters, then deduplicates and classifies them with an LLM and ranks them against each user's personas and feedback. The result is a tight, five-event daily digest instead of an endless listings page — delivered in **Estonian, English, or Russian**.

The whole platform is designed to run on **free-tier infrastructure** at a steady-state cost of $0/month.

## Features

- **Multi-source ingestion** — Fienta API, HTML listing scrapers (Piletilevi, KUMU, Estonia Concert Hall) sharing a common adapter, and inbound newsletter parsing via email webhook. A Nominatim geocoding backfill fills in venue coordinates that sources don't provide, a daily detail-refetch sync reconciles venue/price/coordinates against each event's source page, and per-locale page fetches capture localized `et`/`en`/`ru` titles and descriptions at ingest.
- **Two-stage deduplication** — a cheap SQL + fuzzy pre-filter narrows candidate pairs, then an LLM tiebreaker resolves only the survivors. Decisions are cached by content hash to avoid repeat LLM calls.
- **LLM classification** — assigns a fixed 12-category / 10-vibe taxonomy, a quality score, an explicit-content flag, a non-event flag, a parsed price range, and a localized 3-bullet "why go?" rationale, with a Groq → Cerebras → Mistral provider fallback chain.
- **3-layer NSFW filter** — a keyword prefilter at ingest time, an LLM-assigned explicit-content flag, and a publish gate that excludes flagged events from the published feed.
- **3-layer non-event filter** — the same pattern applied to gift cards/merch/webinars, so the published feed only surfaces real attendable events.
- **Publish gate** — classified events are promoted to `published` only once they clear a minimum quality score, pass the NSFW and non-event checks, pass a location check, haven't already ended, and (if geocoded) fall within the Tallinn region.
- **Persona-based personalization** — users pick a primary and optional secondary persona at onboarding; like/dislike/bookmark signals continuously retune their ranking.
- **Daily 5 builder** — a scheduled job scores upcoming events and writes a diverse five-event feed per user each morning, then emails a digest.
- **Explore discovery grid** — a searchable, filterable (keyword, category/vibe, date, free-only, for-you), and sortable (relevance/date/price/quality) view over all upcoming published events, with an optional personalized ranking path.
- **Saved Events** — a dedicated page listing the events a user has liked, disliked, or bookmarked, grouped by signal.
- **Magic-link auth** — passwordless sign-in with short-lived, single-use links and revocable 7-day session tokens. No third-party auth provider.
- **Full trilingual i18n** — every UI string, email, and LLM output supports `et` / `en` / `ru` from a single shared source of truth.
- **Security-hardened** — OWASP Top 10 mitigations: per-IP rate limiting, strict security headers, CORS lockdown, external-URL sanitization, and a CVE audit in CI.
- **Data retention** — a weekly cleanup prunes aged satellite/audit rows (auth tokens, raw ingestion payloads, old feed snapshots, cached scores) while preserving all event history and user feedback indefinitely.

## Architecture

```
Vite + React SPA  ──HTTPS / JSON──▶  FastAPI (single process)
                                       ├── Routers: /auth /admin /onboarding /events /explore
                                       │            /feed /feedback /users/me /webhooks
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
| Email       | Resend (magic links + daily digests, inbound newsletter webhook) |
| Hosting     | Render (backend web service) · Vercel (frontend) · cron-job.org (keepalive ping) |

## Getting started

### Prerequisites

- **Python 3.12**
- **Node.js 18+** and npm
- A **PostgreSQL** database — a free [Neon](https://neon.tech) project works out of the box, or run Postgres locally.

> [!NOTE]
> External API keys (Groq/Cerebras/Mistral for LLM, Resend for email) are **optional for local development**. Without them, classification degrades gracefully to a rule-only dedup pass and emails are logged to the console instead of being sent. Provide them when you want the full pipeline.

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

Edit `backend/.env` and set at minimum:

- `DATABASE_URL` — your Postgres connection string (async driver, e.g. `postgresql+asyncpg://user:pass@host/db`)
- `SECRET_KEY` — a random secret; generate one with `python -c "import secrets; print(secrets.token_hex(32))"`

Optionally add `GROQ_API_KEY` / `CEREBRAS_API_KEY` / `MISTRAL_API_KEY` and `RESEND_API_KEY` to enable LLM classification and real email delivery. See `.env.example` for the full list of overridable settings (data sources, persona vectors, admin auth, CORS).

### 2. Run the backend

```bash
cd backend

# Create and activate a virtual environment (venv is gitignored).
python -m venv venv
venv\Scripts\Activate.ps1      # Windows PowerShell
# venv\Scripts\activate.bat    # Windows cmd
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
alembic upgrade head            # apply database migrations
uvicorn app.main:app --reload   # dev server on http://localhost:8000
```

The app seeds personas and ingestion sources automatically on startup. Once running:

- Health check: http://localhost:8000/health
- Interactive API docs (development only): http://localhost:8000/docs

### 3. Run the frontend

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
├── backend/                  # FastAPI application
│   ├── app/
│   │   ├── routers/          # /auth /admin /onboarding /events /explore /feed /feedback /webhooks ...
│   │   ├── ingestion/        # source adapters (Fienta, HTML listings, newsletter), geocoding backfill, detail-refetch sync
│   │   ├── dedup/            # rule-based pre-filter + LLM tiebreaker
│   │   ├── llm/              # provider router, classifier, taxonomy, extractor
│   │   ├── ranking/          # scoring + Daily 5 builder
│   │   ├── email/            # digest styles / templates / delivery
│   │   ├── auth/             # magic-link tokens + email
│   │   ├── models/           # SQLAlchemy models
│   │   ├── _generated/       # generated constants & i18n (do not edit by hand)
│   │   ├── constants.py      # single source of truth for backend literals
│   │   ├── config.py         # environment settings
│   │   ├── publish.py        # publish gate (classified → published)
│   │   └── main.py           # app wiring, middleware, scheduler
│   ├── alembic/             # migrations
│   └── tests/               # pytest suite
├── frontend/                 # Vite + React SPA
│   ├── vercel.json           # Vercel rewrites (/api proxy + SPA fallback)
│   └── src/
│       ├── routes/          # Login, AuthVerify, Onboarding, Feed, Explore, SavedEvents, EventDetail, Settings ...
│       ├── components/      # EventCard, PersonaCard, shared CSS base classes ...
│       ├── api/             # API client
│       ├── _generated/      # generated constants & i18n (do not edit by hand)
│       └── i18n.ts          # i18n helpers
├── shared/                   # cross-stack source of truth (i18n, personas, config, calendar)
├── scripts/generate_shared.py# regenerates the _generated/ files in both stacks
├── plan.md                   # authoritative product/architecture spec
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
> `POST /admin/pipeline/run` runs all seven stages above in dependency order in a single call, stopping at the first failure — the fastest way to drive a full E2E cycle. It also accepts `?dry_run=false` for the final digest stage. `GET /admin/stats` and `GET /admin/dedup/groups` are useful for inspecting the results afterwards. The geocoding backfill (`geocode_pending`), the detail-refetch sync (`refetch_event_details`), and the data-retention cleanup (`cleanup_stale_data`) each run on their own schedule and are not part of `pipeline/run`; trigger them on demand via `POST /admin/geocode`, `POST /admin/refetch`, and `POST /admin/cleanup` respectively. Run `refetch` before `geocode` if you want coordinates cleared by an address change re-resolved in the same operation.

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

- **Backend — Render web service** (`render.yaml`): `rootDir: backend`, health check on `/health`. Migrations run on every boot — `startCommand` chains `alembic upgrade head && uvicorn ...`, since Render's `preDeployCommand` is paid-only. Set `DATABASE_URL` (asyncpg form: `postgresql+asyncpg://user:pass@host/db?ssl=require`), `ADMIN_PASSWORD`, `INTERNAL_TOKEN`, the LLM keys (`GROQ_API_KEY`, optionally `CEREBRAS_API_KEY` / `MISTRAL_API_KEY`), `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `CORS_ORIGINS`, and `FRONTEND_URL`. `SECRET_KEY` is auto-generated. Optionally set `LOG_SHIP_URL` (+ `LOG_SHIP_TOKEN`) to ship JSON logs to an external drain such as Axiom.
- **Frontend — Vercel** (`frontend/vercel.json`): static Vite build (`npm run build`, output `dist`). The API client issues all requests against a relative `/api` prefix (`frontend/src/api/client.ts`), so a Vercel rewrite proxies `/api/:path*` to the Render URL **and strips the `/api` prefix** (backend routes have no `/api` prefix — this mirrors the dev Vite proxy); a second rewrite provides the SPA fallback to `index.html` for React Router routes. Same-origin proxying also avoids CORS entirely. No build-time API env var is used.
- **Keepalive — cron-job.org**: Render's free tier sleeps after 15 minutes idle, which would stop the embedded APScheduler. A [cron-job.org](https://cron-job.org) job pings `https://event-radar-api.onrender.com/internal/tick` every 10 minutes with the `X-Internal-Token` header set to the same value as Render's `INTERNAL_TOKEN`. (Render's own cron jobs are paid; GitHub Actions cron proved too imprecise for a keepalive cadence.)

## Documentation

- **[plan.md](plan.md)** — the authoritative product and architecture specification (data model, pipeline, scoring formula, roadmap).
- **[CLAUDE.md](CLAUDE.md)** — engineering conventions and codebase guidance.
