# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**What's on Radar** (repo/working dir `event-radar`; the product name in every user-facing string, the FastAPI app title, and the README is "What's on Radar") is an AI-powered event discovery platform for Tallinn, Estonia. It ingests events from multiple sources, deduplicates and classifies them via LLM, then delivers a personalized "Daily 5" curated feed per user. MVP complete plus a post-MVP self-service organizer portal (see `docs/organizer-portal.md`); soft launch is live — there is no Playwright/Cypress suite; QA is done via the Playwright MCP server, whose scratch output lands in `.playwright-mcp/` (disposable).

## Documentation Map

Deep-dive docs live in `docs/` and are **not** auto-loaded — read the relevant one before touching its area. Each file opens with a one-line "what's in here" banner.

| Doc | Read before touching |
|---|---|
| `docs/pipeline.md` | `app/ingestion/`, `app/dedup/`, `app/llm/`, `app/publish.py`, `app/ranking/`, `app/routers/browse.py`, `app/routers/public.py`, `app/routers/feedback.py` |
| `docs/security.md` | `app/main.py`, `app/rate_limit.py`, `app/routers/auth.py`, `app/routers/organizer_auth.py`, `app/routers/utils.py`, `app/ingestion/http_client.py`, or any new endpoint |
| `docs/backend-ops.md` | `render.yaml`, `frontend/vercel.json`, `app/routers/admin.py`, `app/cleanup.py`, `app/logging_config.py`, `backend/scripts/` |
| `docs/frontend.md` | `frontend/src/routes/`, `frontend/src/components/`, `frontend/src/hooks/`, `frontend/src/lib/`, `frontend/scripts/`, `shared/i18n/`, `backend/app/email/` |
| `docs/conventions.md` | the *why* behind a Code Quality Rule below (full rationale + examples) |
| `docs/data-model.md` | writing a migration, a query touching a new column, or a serializer |
| `docs/organizer-portal.md` | `app/routers/organizer_auth.py`, `app/routers/organizer_events.py`, `frontend/src/routes/EventSubmit/` |
| `docs/observability.md` | the Axiom monitoring spec (linked from `docs/backend-ops.md`'s Logging section) |
| `CONTEXT.md` | before naming a new domain concept — repo-root domain glossary |
| `docs/adr/` | architectural decisions (currently one: `0001-session-tokens-in-httponly-cookies.md`) |
| `docs/agents/` | agent-facing workflow docs (issue tracker, triage labels, domain docs) — see Agent skills below |

## Commands

A `.devcontainer/` (VS Code Dev Containers) is available for Windows dev — Python 3.12 + Node 20 match CI; Postgres 16 matches the root `docker-compose.yml`/Render, not CI (CI runs no Postgres service at all). Inside it: the venv creation/activation lines below are skipped (interpreter is always `/opt/venv/bin/python`, already on `PATH`), `python -m ruff` / `python -m mypy` are unchanged, and `docker compose up -d db` is unnecessary since `db` comes up with the container. `DATABASE_URL` is injected via `.devcontainer/docker-compose.yml` and overrides `backend/.env`. The embedded APScheduler is off by default in the container (`ENABLE_SCHEDULER=false`, dev-only — see `app/config.py`) so `uvicorn --reload` left running overnight can't arm live scrapes/LLM spend/digest email on a timer; to exercise the real cadence for one session, `bash .devcontainer/dev-server.sh stop backend` then run `ENABLE_SCHEDULER=true uvicorn app.main:app --reload` by hand. The `claude` CLI is available in the container terminal (installed via the `claude-code` devcontainer feature) and signs in once against a persistent named volume, separate from the host's `~/.claude` — `.devcontainer/sync-claude-config.sh` mirrors host settings, hooks, commands and skills in on every start (plus the Dockerfile's RTK install), so those *do* apply inside the container. `.devcontainer/claude-plugins.json` declares container-only Claude plugins (currently `mattpocock-skills`) that `sync-claude-config.sh` merges into the container's `~/.claude/settings.json` on every start, without ever writing to the host. `gh` is installed via the `github-cli` devcontainer feature and auto-authenticated on start/attach by deriving a token from the host's forwarded git credential helper (`.devcontainer/gh-auth.sh`); if `gh auth status` comes back red, re-run that script or `gh auth login`. Backend and frontend dev servers auto-start from the container lifecycle (`postStartCommand` → `.devcontainer/dev-server.sh start`, on every container start — not a VS Code task); status/restart/stop via `bash .devcontainer/dev-server.sh status|restart|stop`, logs in `/tmp/event-radar-dev/`; tail via `bash .devcontainer/dev-server.sh logs backend|frontend`, auto-opened split in VS Code by the `logs: backend`/`logs: frontend` tasks (`.vscode/tasks.json`).

```bash
# Backend (Python 3.12, FastAPI)
cd backend
python -m venv venv          # create virtualenv (venv is gitignored)
# Activate it — pick the line for your shell:
venv\Scripts\Activate.ps1    # Windows PowerShell
venv\Scripts\activate.bat    # Windows cmd
source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
alembic upgrade head          # apply migrations
uvicorn app.main:app --reload # dev server (port 8000)
pytest                        # run all tests
pytest tests/path/test_foo.py::TestClass::test_name  # single test
pytest --cov --cov-report=term-missing   # tests + coverage report (config: backend/.coveragerc)

# Dev tooling (pip install -r requirements-dev.txt)
python -m mypy app             # type-check (mypy not on PATH — always invoke via `python -m mypy`)
python -m ruff check .         # lint (ruff not on PATH either — always `python -m ruff`)
```

```bash
# Local database (repo root) — docker-compose.yml runs Postgres 16 on :5432 with
# user/password/db all "eventradar", matching the DATABASE_URL in backend/.env.example.
docker compose up -d db      # start local Postgres
docker compose ps            # wait for the db healthcheck to report "healthy"
```

```bash
# Frontend (Vite + React SPA)
cd frontend
npm install
npm run dev        # dev server (port 5173)
npm run build      # type-check + production build
npm run type-check # TypeScript check only
npm run lint       # ESLint (flat config in eslint.config.js)
npm test           # run all tests (vitest)
npm run test:watch # vitest watch mode
npm run test:coverage # coverage report (v8, html + text)
```

**CI** (`.github/workflows/tests.yml`, push/PR to `master`): `pytest --cov` (Python 3.12) + `npm run test:coverage` (Node 20) only. `dependency-audit.yml` runs `pip-audit` + `npm audit --audit-level=high`, plus weekly cron Mon 04:00 UTC. **Ruff/mypy/eslint/type-check are house rules with no CI enforcement** — a green PR does not mean they were run; run them locally before committing.

## Architecture

```
Vite + React SPA (frontend, port 5173 in dev)
  ├── Routes: /login  /auth/verify  /onboarding  /  /explore  /saved  /events/:id  /settings  /unsubscribe  /privacy  /terms  /contact
  │           (`/` renders the public Landing when signed out, the Feed when signed in)
  │           Organizer portal: /organizer/login  /organizer/verify  /organizer/dashboard
  │                             /organizer/submit  /organizer/events/:id/edit
  ├── State: React Query (@tanstack/react-query) for server state
  └── API client: frontend/src/api/client.ts (httpOnly session-cookie auth, `credentials: "include"`)
        ↓
FastAPI Backend (single process on Render free tier, port 8000 in dev)
  ├── Routers: /auth  /admin  /onboarding  /events  /explore  /feed  /feedback  /public  /users/me  /contact  /email  /webhooks  /organizer/auth  /organizer/events
  └── APScheduler (embedded, kept alive by a cron-job.org ping of /internal/tick every 10 min)
      ├── Weekly Sun 03:00: sync_fienta_organizers   ├── Weekly Sun 03:30: cleanup_stale_data
      ├── Hourly: ingest_all_sources (job id; callable is ingest_all_enabled) ├── 6-hourly: dedup_pass + classify_pending + publish_pending + geocode_pending
      ├── Daily 04:30: refetch_event_details          ├── Daily 06:00: build_daily_feeds
      └── Daily 07:00: send_daily_digests
        ↓
Neon Postgres (eu-central-1, free tier, pgvector available for v1.1)
        ↓
LLM Router: Groq (primary) → Cerebras → Mistral (fallback chain)
```

**No Celery/Redis** — embedded APScheduler suffices for a single-process MVP. Deployment topology (Render/Vercel/cron-job.org) is in `docs/backend-ops.md`.

## Pipeline at a Glance

Full detail (field-level authority tables, sub-pass ordering, tiering) in `docs/pipeline.md`.

1. **Ingestion** — Fienta API, HTML listing scrapers (Piletilevi/KUMU/Estonia Concert Hall), organizer self-submission. Newsletter inbound (`POST /webhooks/inbound-mail`, Svix-signature-verified, `extract_events_from_email()`) is fully wired up but dormant — `NEWSLETTER_SENDER_ALLOWED_DOMAINS` is an empty frozenset, so no sender is allowlisted yet.
2. **Deduplication** — rule-based pre-filter + LLM tiebreaker on surviving pairs; same-day title unions collapse timed-entry slots with no LLM call.
3. **Classification** — LLM assigns categories/vibes/quality/price/flags against a fixed 14-category/10-vibe taxonomy; ingest-set prices are authoritative over LLM-derived ones.
4. **Ranking** — `score = 0.45·persona_affinity + 0.20·recency_boost + 0.20·feedback_signal + 0.10·quality_score + 0.05·locality_bonus` (feedback_signal is `fb_normalized`, the raw [-1,1] feedback score mapped to [0,1] before weighting)
5. **Daily 5 builder** — 06:00 Europe/Tallinn; MMR-lite diversity capped at `DAILY_5_MAX_PER_CATEGORY` (2); series cooldown + backfill tiers guarantee `n=5`.
6. **Publish gate** — `app/publish.py::publish_pending()` promotes `classified` → `published` on quality/explicit/non-event/area/ended/title/bbox/organizer-trust checks; runs every 6h.
7. **Geocoding backfill** — Nominatim + venue-name extraction + sibling-copy sub-passes; runs every 6h.
8. **Detail-refetch sync** — daily 04:30, reconciles venue/price/coords/localized text from source detail pages before the 06:00 feed build.

Four read paths (Daily 5 feed, Explore, Saved Events, public Landing showcase) and the Fienta organizer lifecycle (detect/skip/revive/retire/discover) are documented in `docs/pipeline.md`. LLM usage constraints (`LLM_MAX_TOKENS = 400` per call, `LLM_REASONING_MAX_TOKENS = 600` hard-cap ceiling used by the Cerebras entry, dedup content-hash cache, Groq→Cerebras→Mistral fallback, backlog drain) and the three-layer NSFW/non-event content filters are also there.

## Auth, Security & the Organizer Portal

- **Auth** — magic-link email (`itsdangerous` tokens, no third-party auth), httpOnly/Secure/`SameSite=Strict` session cookies (2-day TTL), `session_token_version` revocation, `email_verified` gate on the digest/feed builder. Full flow, residual-risk trade-offs, and the digest unsubscribe token in `docs/security.md`.
- **Security hardening** — rate limiting (every endpoint gets a `RATE_LIMIT_*`), security headers, CSP, body-size ceiling, `require_configured_secret` dev-fail-open double gate, admin auth lockout, external-URL sanitization (`safe_external_url()` vs `safe_fetchable_url()`, keyed on fetched-vs-rendered), stored-HTML sanitization (`sanitize_html()`/`html_to_text()`), redirect SSRF guard, webhook signature verification, CSRF (`CsrfOriginCheckMiddleware`, `app/main.py`, rejects mutating requests whose `Origin` isn't in `CORS_ORIGINS ∪ {FRONTEND_URL}` — second layer behind `SameSite=Strict`). Full detail in `docs/security.md` — read it before adding any new endpoint or external-facing URL field.
- **Organizer portal** — self-service submission with its own auth track (separate salts/tables from user auth), auto-publish gated on organizer trust (`verified` flag), admin post-hoc review queue. Full detail in `docs/organizer-portal.md`.
- **Admin endpoints** — `/admin/*`, HTTP Basic auth, shared rate-limit bucket, `run_admin_job()` helper. Full detail in `docs/backend-ops.md`.

## i18n

**Single source of truth:** `shared/i18n/{en,et,ru}.json`, `shared/personas.json`, `shared/app-config.json`, `shared/calendar.json`.

**Workflow (hard rule):** Edit the JSON files in `shared/` → run `python scripts/generate_shared.py` → commit both the JSON and the updated `_generated` files. **Never edit `_generated/` directly.** `backend/tests/test_generated_sync.py` is a drift guard — if it fails, regenerate and commit.

Frontend imports generated strings via `frontend/src/i18n.ts`; backend via `backend/app/i18n.py`. Email presentation (styles/templates/assembly three-file split) and per-email specifics are in `docs/frontend.md`.

## Frontend Structure

Each component/route lives in its own folder: `Name.tsx` + `Name.module.css` + a one-line `index.ts` barrel. Routes in `frontend/src/routes/`, shared components in `frontend/src/components/`, CSS design tokens are **mandatory** (never hardcode colors/spacing/radii — see Code Quality Rules below), shared CSS chrome composes from `frontend/src/components/shared/`. Hooks/utils/constants each have one canonical home (`frontend/src/hooks/`, `frontend/src/utils.ts`, `frontend/src/constants.ts`) — check there before writing a new one. Full folder-by-folder breakdown in `docs/frontend.md`.

## Code Quality Rules

Full rationale for each rule (why it works this way, trade-offs accepted) is in `docs/conventions.md`. These are the imperatives:

- **Backend constants** — all literals in `app/constants.py` (LLM prompts in `app/llm/prompts.py`, scrape selectors in `app/ingestion/selectors.py`; cross-stack via `shared/`). Never define a constant near business logic.
- **Backend utilities** — all shared helpers in `backend/app/routers/utils.py`. Check there before writing a new one.
- **Frontend constants** — all magic values in `frontend/src/constants.ts` (cross-stack via `shared/`). Never inline a literal near component logic.
- **Frontend utilities** — all shared helpers in `frontend/src/utils.ts`. Check there before writing a new one.
- **CSS design tokens** — colors, radii, shadows, z-indices, transitions, spacing, typography, component-geometry vars are all tokenized in `:root` (`frontend/src/index.css`). Never hardcode — define the token first, then `var(--token-name)`.
- **CSS shared base classes** — card/button/menu chrome lives in `frontend/src/components/shared/`. Use CSS Modules `composes` — never copy-paste.
- **Retry logic** — all HTTP calls use `http_get()`/`http_post()` from `app/ingestion/http_client.py` (tenacity backoff, 429 `Retry-After` honored).
- **DB connection pooling** — `app/db.py` uses `pool_pre_ping=True` + `pool_recycle` below Neon's idle-suspend window.
- **HTML listing adapters** — subclass `HtmlListingAdapter` (`app/ingestion/sources/html_base.py`); don't duplicate the fetch/parse loop or hreflang logic.
- **Presentation layer separation** — CSS in `styles.py`, markup in `templates.py`, assembly in the delivery module (see the email package). No templating engine. Exception: `app/email/contact.py` (internal-only mail).
- **Encapsulation** — a leading underscore is module-private; never import a `_name` cross-module (drop the underscore instead). Tests may import private names.
- **Error visibility** — never swallow exceptions in `fetch_raw()`; adapter HTTP failures must propagate to `SourceAdapter.run()`.
- **Taxonomy** — filter LLM output against `VALID_CATEGORIES`/`VALID_VIBES` before persisting; unknown values are silently dropped.
- **Migrations** — chain `down_revision` correctly; keep small and reversible; defensive `DELETE` before a new unique index that could collide with historical dupes.
- **Batch jobs** — bulk-load, no N+1. Fixed query count independent of row count; never `SELECT` inside a per-row loop.
- **External-API fan-out** — bounded concurrency via `asyncio.gather(..., return_exceptions=True)` + a `Semaphore` (limit in `app/constants.py`). Never unbounded-gather.
- **Dedup self-join pre-filter** — time-window check stays in SQL (`candidate_pair_ids_in_window()`); fuzzy check stays in Python, only on pre-filtered pairs.
- **Quote style** — backend Python: double quotes (Ruff `Q` rules). Frontend TS: single quotes for strings, double for JSX attributes (ESLint). Run `ruff check --fix`/`eslint --fix` before committing.
- **Python lint** — `python -m ruff check backend` must pass clean, config in `backend/ruff.toml` (no `backend/pyproject.toml` — don't create one) (`select = ["E","F","W","Q"]`, `line-length = 88`, `E501` ignored, `extend-exclude = ["app/_generated"]`).
- **Type checking** — `python -m mypy app` from `backend/` must pass clean. Give structurally-incompatible reused loop variables their own names.
- **Type annotations** — modern PEP 604/585 syntax (`X | None`, `list[T]`), annotate all public return types.
- **Shared test fixtures** — backend: `backend/tests/conftest.py` (`mock_db`, `make_user`, `make_event`). Frontend: `frontend/src/test/utils.tsx` (`renderWithProviders`, `makeEvent`); mock the `api` module, not `fetch`.
- **Numeric truthiness** — never gate a numeric field on truthiness (`0` is falsy — breaks free events). Use explicit `is not None` / `isinstance` checks.

## Conventions

- All datetimes are timezone-aware — no naive datetimes anywhere. User-visible timestamps and scheduling logic use `zoneinfo` (`Europe/Tallinn`) via `TALLINN_TZ`. Auth/token expiry arithmetic (`generate_magic_token`, session TTL, `_mark_processed`) may use `datetime.now(timezone.utc)` since DST-ambiguity is undesirable for TTL math.
- Email columns use `citext` (case-insensitive) to prevent duplicate accounts.
- Persona affinity vectors and source config stored as JSONB for easy extension without migrations.
- Feedback decay formula: `0.9^days_since_feedback` — recent signals weighted higher, dislike is a hard exclude.
- Public event endpoints (`/events/{id}`) return only `status == published` events and never expose internal metadata (`dedup_group_id`, draft/cancelled rows). Filter at the query level (`routers/events.py`), not in the serializer.

## MVP Scope (do not cut)

All MVP scope implemented: dedup, LLM classification, persona-based personalization, magic-link auth, Daily 5 builder, email digest, bookmarks, i18n (et/en/ru), Settings page.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (github.com/allut/event-radar), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — `CONTEXT.md` at the repo root, `docs/adr/` under `docs/`. See `docs/agents/domain.md`.
