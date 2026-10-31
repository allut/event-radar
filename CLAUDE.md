# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Event Radar** is an AI-powered event discovery platform for Tallinn, Estonia. Use that name in every user-facing string; `event-radar` is only the repo and working directory.

The pipeline ingests events from several sources, then dedups, classifies, publishes and ranks them into a personalized Daily 5 feed per user.

## Documentation Map

Deep-dive docs are not auto-loaded. Open the row's doc before editing what it covers.

| Subject | Read before touching |
|---|---|
| **Pipeline** — `docs/pipeline.md` | `app/ingestion/`, `app/dedup/`, `app/llm/`, `app/ranking/`, `app/events/`, `app/publish.py`, `app/routers/{browse,public,feedback,feed,events,webhooks}.py` |
| **Security** — `docs/security.md` | `app/main.py`, `app/rate_limit.py`, `app/auth/`, `app/routers/{auth,organizer_auth,admin_auth,unsubscribe,utils}.py`, `app/ingestion/http_client.py`, any new endpoint |
| **Security audit state** — `docs/security-audit.md` | fixing or adding an audit finding |
| **Backend ops** — `docs/backend-ops.md` | `render.yaml`, `frontend/wrangler.toml`, `frontend/public/_headers`, `frontend/functions/`, `app/routers/{admin_*,reports}.py`, `app/cleanup.py`, `backend/scripts/`, scheduled jobs, CI |
| **Frontend** — `docs/frontend.md` | `frontend/src/{routes,components,hooks,lib,content}/`, `frontend/scripts/generate-icons.ts`, `shared/i18n/`, `app/email/` |
| **SEO and prerender** — `docs/seo.md` | `frontend/scripts/prerender.ts`, `frontend/functions/api/{seo-audit,prerender-cadence}.ts`, `useSeoMeta`, `SeoTags/`, `frontend/src/lib/{structuredData,jsonLd,seoValidation,seoAudit*,prerender*,r2ChainState}.ts` |
| **Design system** — `docs/design-system.md` | any `.module.css`, `frontend/src/index.css`, `frontend/src/components/shared/`, `frontend/src/lib/theme.ts`, `app/email/styles.py`, any visual change |
| **Promotions and payments** — no single doc | `app/promotions/`, `app/integrations/`, `app/routers/admin_promotion*.py`, `app/routers/stripe_webhook.py`: `docs/backend-ops.md` (Stripe Setup, sweep, kill switches), `docs/security.md` (Stripe Webhook), `docs/organizer-portal.md` (promotion form), `docs/data-model.md` |
| **Organizer portal and claiming** — `docs/organizer-portal.md` | `app/routers/organizer_*.py`, `app/routers/admin_claims.py`, `app/claims/`, `frontend/src/routes/{EventSubmit,OrganizerSettings,OrganizerContact}/`, `frontend/src/routes/*Claim*/`, `frontend/src/components/{VenuePicker,RichTextEditor,ClaimStrip,ClaimEventPicker}/` |
| **Data model** — `docs/data-model.md` | `app/models/`, a migration, a query on a new column, a serializer |
| **Rule rationale** — `docs/conventions.md` | the reason behind a Code Quality Rule below |
| **Writing docs** — `docs/writing-docs.md` | `CLAUDE.md`, `README.md`, any `docs/*.md` |
| **Observability** — `docs/observability.md` | `app/logging_config.py`, `LOG_*` constants in `app/constants/ops.py`, Axiom monitors, the log-record shape, log triage |
| **Domain glossary** — `CONTEXT.md` | naming a new domain concept |
| **Decisions** — `docs/adr/` | an architectural decision |
| **Agent workflow** — `docs/agents/` | the issue tracker, triage labels and domain docs |

## Commands

Setup (venv, installs, `backend/.env`) is in `README.md`.

```bash
# Backend (Python 3.12, FastAPI)
cd backend
alembic upgrade head          # apply migrations
uvicorn app.main:app --reload # dev server (port 8000)
bash scripts/scratch-test.sh  # all tests, throwaway DB
bash scripts/scratch-test.sh tests/path/test_foo.py::TestClass::test_name  # single test
bash scripts/scratch-test.sh --cov --cov-report=term-missing  # coverage (backend/.coveragerc)
python -m mypy app ../scripts # type-check (requirements-dev.txt)
python -m ruff check . ../scripts  # lint
```

```bash
# Local database (repo root) — Postgres 16 on :5432, user/password/db all "eventradar"
docker compose up -d db      # start local Postgres
docker compose ps            # wait for the db healthcheck to report "healthy"
```

The frontend's commands are the `frontend/package.json` scripts: `dev` (port 5173), `build`, `type-check`, `lint`, `test` and `test:coverage`.

### Devcontainer

The setup walkthrough is in `README.md`. Inside the container:

- **The interpreter is `/opt/venv/bin/python`, already on `PATH`.** There is no venv to activate. `DATABASE_URL` and Postgres come with the container.
- **Dev servers auto-start; restart them with `bash .devcontainer/dev-server.sh restart`.** An ad-hoc `npm run dev` on the mounted workspace gets a Vite watcher that silently goes stale. Use `dev-server.sh run <backend|frontend>` for a foreground instance.
- **The scheduler is off (`ENABLE_SCHEDULER=false`).** No timed scrapes, LLM spend or digest email. The README shows how to turn it on for one session.
- **Logs are in `/tmp/event-radar-dev/`.** Tail them with `bash .devcontainer/dev-server.sh logs backend|frontend`.

### Testing

- **Run the backend suite from the repo root with `bash backend/scripts/scratch-test.sh [pytest args]`.** It migrates, then drops, a throwaway database. The full suite takes ~4 min: run it with `run_in_background`. `backend/tests/conftest.py` refuses to run when `DATABASE_URL` names the dev `eventradar` database.
- **UI work starts with an approved prototype built on the real `index.css`.** Recipe: `docs/design-system.md` "Prototype Shell". A change with no visual difference (data, wiring, when an existing control shows) needs none.
- **After editing `CLAUDE.md`, `README.md` or `docs/*.md`, run `bash backend/scripts/scratch-test.sh --no-db tests/test_docs_style.py`.**
- **There is no e2e suite.** QA runs through the Playwright MCP server, and `.playwright-mcp/` is disposable scratch. Playwright stays a build dependency for the SEO prerender.

## Architecture

```
Vite + React SPA          Cloudflare Pages; /api/* proxied by a Pages Function
        ↓
FastAPI + APScheduler     one process, Render Frankfurt
        ↓
Neon Postgres             eu-central-1
LLM router                Groq → Cloudflare Workers AI → Mistral
```

- **There is no Celery or Redis.** The embedded APScheduler runs every job inside the single FastAPI process. Module-level caches and locks rely on that single-process topology.

## Code Quality Rules

`docs/conventions.md` holds the reasons and examples. Area-specific rules live in their area doc.

### Where things live

- **Backend constants live in `app/constants/<domain>.py`**, one file per domain, imported from the file that defines them. LLM prompts go in `app/llm/prompts.py`, scrape selectors in `app/ingestion/selectors.py`, and cross-stack values in `shared/`, imported from `app._generated.shared_constants` directly. Add the constant there first, then import it.
- **Frontend constants live in `frontend/src/constants/<domain>.ts`**, imported from the file that defines them, and cross-stack ones in `shared/`, imported from `src/_generated/sharedConstants.ts` directly (an int, string or string list under `scalars` in `app-config.json`; `docs/frontend.md` i18n has the generator flow). Add the literal there before using it in a component.
- **Each backend helper has one home.** Router-shared helpers go in `app/routers/utils.py`. Domain packages (`app/auth/`, `app/email/`, `app/claims/`, `app/ingestion/`, `app/events/`, `app/promotions/`) own theirs and never import from `routers/utils.py`. Check both before writing one.
- **Cross-router auth dependencies live in `app/auth/dependencies.py`**, so routers never import from each other's modules.
- **Frontend helpers live in `frontend/src/utils.ts` and hooks in `frontend/src/hooks/`.** Every request goes through `frontend/src/api/client.ts`. Check there before writing a new one.
- **A leading underscore means module-private.** Drop the underscore before importing a name across modules. Tests, and a third-party library's own documented exports, are exempt.

### CSS

- **Styles use design tokens only.** Colors, radii, shadows, z-indices, transitions, spacing, typography and component geometry are `:root` tokens in `frontend/src/index.css`. Define a missing token there first, then use `var(--token)`.
- **Shared chrome composes from `frontend/src/components/shared/`** through CSS Modules `composes`. For one consumer's variation, add a modifier class next to the base class and leave the base unchanged.

### Backend behaviour

- **Batch jobs bulk-load.** Keep the query count fixed whatever the row count: fetch with one `WHERE col IN (...)`, group in Python, and keep every `SELECT` outside per-row loops.
- **Bound external-API fan-out.** Use `asyncio.gather(..., return_exceptions=True)` behind an `asyncio.Semaphore` whose limit lives in `app/constants/`.
- **HTTP calls go through `app/ingestion/http_client.py::http_get()`/`http_post()`** for tenacity backoff and 429 `Retry-After`. Request-path Resend sends use `app/email/resend.py::send_resend_email()`, a single attempt. `docs/conventions.md` lists the other bypasses and their reasons; add one only with a reason.
- **Gate numeric fields with `is not None`, never truthiness.** `0` is falsy, so a truthiness check silently drops free events.

### Tests

- **Reuse the shared test fixtures** in `backend/tests/conftest.py`, the package conftests and `frontend/src/test/utils.tsx`. Frontend tests mock the `api` module, not `fetch`.

## Conventions

- **Datetimes are timezone-aware everywhere.** User-visible times and scheduling use `zoneinfo` `Europe/Tallinn` through `TALLINN_TZ`.
- **Token and session TTL arithmetic may use `datetime.now(timezone.utc)`.** DST ambiguity is wrong for an expiry, so `generate_magic_token`, the session TTL and similar stay in UTC.

## Traps

- **Production builds from `release`, not `master`.** `master` is the CI/PR branch. A Cloudflare Pages build of any other branch skips the prerender pass (`PRERENDER_CADENCE_GIT_BRANCH`, `frontend/src/constants/prerender.ts`).
- **CI's `lint` job and `.githooks/pre-commit` run ruff, mypy, eslint and type-check.** Ruff's config is `backend/ruff.toml`; there is no `backend/pyproject.toml`. The devcontainer enables the hook (`git config core.hooksPath .githooks`). Elsewhere, enable it yourself, or run the four checks by hand before committing.
- **Edit translations and shared values in `shared/`, then run `python scripts/generate_shared.py`.** Commit the JSON and the regenerated `_generated/` files together, and leave `_generated/` to the script. `backend/tests/test_generated_sync.py` fails on drift. To move an existing backend constant there, run `python scripts/move_to_shared.py <domain> NAME` (`--dry-run` first).
- **The three auth tracks never mix.** Consumer, organizer and admin sessions use separate signing salts and cookies, and consumer and organizer accounts live in separate tables. `CONTEXT.md` names them and `docs/security.md` has the flows.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (github.com/allut/event-radar), via the `gh` CLI. Open `docs/agents/issue-tracker.md` before any `gh issue` command; `gh issue view <n> --comments` alone prints nothing for an issue without comments.

### Triage labels

Default label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — `CONTEXT.md` at the repo root, `docs/adr/` under `docs/`. See `docs/agents/domain.md`.
