# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Event Radar** (repo/working dir `event-radar`; the product name in every user-facing string, the FastAPI app title, and the README is "Event Radar") is an AI-powered event discovery platform for Tallinn, Estonia. It ingests events from multiple sources, deduplicates and classifies them via LLM, then delivers a personalized "Daily 5" curated feed per user. MVP complete plus post-MVP work: a self-service organizer portal (`docs/organizer-portal.md`), user-facing event reporting + admin resolution, the operator-facing admin console SPA at `/admin/*` (`docs/backend-ops.md`), the C1 design system with account-level light/dark theming (`docs/design-system.md`), and the public SEO surface — signed-out Explore, JSON-LD, build-time prerender (`docs/frontend.md`). Soft launch is live — there is no Playwright/Cypress **e2e suite**; QA is done via the Playwright MCP server, whose scratch output lands in `.playwright-mcp/` (disposable). Playwright is still a build dependency: `frontend/scripts/prerender.ts` drives it for the SEO prerender pass (see `docs/frontend.md`).

## Documentation Map

Deep-dive docs live in `docs/` and are **not** auto-loaded — read the relevant one before touching its area. Each file opens with a one-line "what's in here" banner.

| Doc | Read before touching |
|---|---|
| `docs/pipeline.md` | `app/ingestion/`, `app/dedup/`, `app/llm/`, `app/publish.py`, `app/ranking/`, `app/routers/browse.py`, `app/routers/public.py`, `app/routers/feedback.py` |
| `docs/security.md` | `app/main.py`, `app/rate_limit.py`, `app/routers/auth.py`, `app/routers/organizer_auth.py`, `app/routers/admin_auth.py`, `app/auth/`, `app/routers/utils.py`, `app/ingestion/http_client.py`, or any new endpoint |
| `docs/backend-ops.md` | `render.yaml`, `frontend/wrangler.toml`, `frontend/public/_headers`, `frontend/functions/`, `app/routers/admin.py`, `app/routers/admin_auth.py`, `app/routers/reports.py`, `app/cleanup.py`, `app/logging_config.py`, `backend/scripts/` |
| `docs/frontend.md` | `frontend/src/routes/`, `frontend/src/components/`, `frontend/src/hooks/`, `frontend/src/lib/`, `frontend/src/content/`, `frontend/scripts/`, `frontend/api/`, `frontend/functions/`, `shared/i18n/`, `backend/app/email/` |
| `docs/design-system.md` | any `.module.css`, `frontend/src/index.css`, `frontend/src/components/shared/`, `frontend/src/lib/theme.ts`, `backend/app/email/styles.py`, or any change that is visual rather than behavioral |
| `docs/conventions.md` | the *why* behind a Code Quality Rule below (full rationale + examples) |
| `docs/data-model.md` | writing a migration, a query touching a new column, or a serializer |
| `docs/organizer-portal.md` | `app/routers/organizer_auth.py`, `app/routers/organizer_events.py`, `app/routers/organizer_profile.py`, `app/routers/organizer_venues.py`, `app/routers/organizer_contact.py`, `frontend/src/routes/EventSubmit/`, `frontend/src/routes/OrganizerSettings/`, `frontend/src/routes/OrganizerContact/`, `frontend/src/components/VenuePicker/`, `frontend/src/components/RichTextEditor/` |
| `docs/observability.md` | the Axiom monitoring spec (linked from `docs/backend-ops.md`'s Logging section) |
| `CONTEXT.md` | before naming a new domain concept — repo-root domain glossary |
| `docs/adr/` | architectural decisions — two: `0001-session-tokens-in-httponly-cookies.md`, `0002-google-sign-in-oauth-pkce.md` |
| `docs/agents/` | agent-facing workflow docs (issue tracker, triage labels, domain docs) — see Agent skills below |

## Commands

A `.devcontainer/` (VS Code Dev Containers) is available for Windows dev — Python 3.12 + Node 20 match CI; Postgres 16 matches the root `docker-compose.yml`/Render, not CI (CI runs no Postgres service at all). Inside it: the venv creation/activation lines below are skipped (interpreter is always `/opt/venv/bin/python`, already on `PATH`), `python -m ruff` / `python -m mypy` are unchanged, and `docker compose up -d db` is unnecessary since `db` comes up with the container. `DATABASE_URL` is injected via `.devcontainer/docker-compose.yml` and overrides `backend/.env`. The embedded APScheduler is off by default in the container (`ENABLE_SCHEDULER=false`, dev-only — see `app/config.py`) so `uvicorn --reload` left running overnight can't arm live scrapes/LLM spend/digest email on a timer; to exercise the real cadence for one session, `bash .devcontainer/dev-server.sh stop backend` then run `ENABLE_SCHEDULER=true uvicorn app.main:app --reload` by hand. The `claude` CLI is available in the container terminal (installed via the `claude-code` devcontainer feature) and signs in once against a persistent named volume, separate from the host's `~/.claude` — `.devcontainer/sync-claude-config.sh` mirrors host settings, hooks, commands and skills in on every start (plus the Dockerfile's RTK install), so those *do* apply inside the container. `.devcontainer/claude-plugins.json` declares container-only Claude plugins (currently `mattpocock-skills`) that `sync-claude-config.sh` merges into the container's `~/.claude/settings.json` on every start, without ever writing to the host. `gh` is installed via the `github-cli` devcontainer feature and auto-authenticated on start/attach by deriving a token from the host's forwarded git credential helper (`.devcontainer/gh-auth.sh`); if `gh auth status` comes back red, re-run that script or `gh auth login`. Backend and frontend dev servers auto-start from the container lifecycle (`postStartCommand` → `.devcontainer/post-start.sh`, which runs `dev-server.sh start`, refreshes the `claude` CLI, syncs Claude config, and takes a first shot at `gh-auth.sh` — on every container start, not a VS Code task); status/restart/stop via `bash .devcontainer/dev-server.sh status|restart|stop` (also `run <backend|frontend>` for a foreground, Ctrl-C-able instance), logs in `/tmp/event-radar-dev/`; tail via `bash .devcontainer/dev-server.sh logs backend|frontend`, auto-opened split in VS Code by the `logs: backend`/`logs: frontend` tasks (`.vscode/tasks.json`). `.devcontainer/mem-watchdog.sh` is a manual, unwired diagnostic for the intermittent "reload the VS Code window" hang — run it by hand when chasing that, never part of the normal loop.

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

**CI** (`.github/workflows/tests.yml`, push/PR to `master`): `pytest --cov` (Python 3.12) + `npm run test:coverage` (Node 20), plus a `migrations` job against a `postgres:16` service that round-trips the full alembic chain (`upgrade head` → `downgrade base` → `upgrade head`) and runs `alembic check` to catch a model changed without a matching migration — the class of failure behind the 0030/`admin_actions` prod incident, where code shipped a new model+migration but the deployed DB never ran it. `dependency-audit.yml` runs `pip-audit` + `npm audit --audit-level=moderate`, plus weekly cron Mon 04:00 UTC. **Ruff/mypy/eslint/type-check are house rules with no CI enforcement** — a green PR does not mean they were run; run them locally before committing.

## Architecture

```
Vite + React SPA (frontend, port 5173 in dev)
  ├── Routes: /login  /auth/verify  /onboarding  /  /explore  /saved  /events/:id  /settings  /unsubscribe  /privacy  /terms  /contact
  │           (`/` renders the public Landing when signed out, the Feed when signed in;
  │            /explore is public too, with signed-out chrome + a sign-in upsell)
  │           Each is registered twice — bare path (Estonian) and `/:locale` prefix (/en/…, /ru/…)
  │           Organizer portal: /organizer/login  /organizer/verify  /organizer/dashboard
  │                             /organizer/settings  /organizer/contact  /organizer/submit
  │                             /organizer/events/:id/edit
  │           Admin console (own React.lazy chunk, no i18n, outside the locale loop):
  │                             /admin/login  /admin  /admin/reports  /admin/submissions
  │                             /admin/pipeline  /admin/dedup  /admin/events/:id
  ├── State: React Query (@tanstack/react-query) for server state
  └── API client: frontend/src/api/client.ts (httpOnly session-cookie auth, `credentials: "include"`)
        ↓
FastAPI Backend (single process on Render Frankfurt Starter, port 8000 in dev)
  ├── Routers: /auth  /admin  /admin/auth  /onboarding  /events  /explore  /feed  /feedback  /public
  │            /reports  /users/me  /contact  /email  /webhooks  /organizer/auth  /organizer/events
  │            /organizer/profile  /organizer/venues  /organizer/contact
  └── APScheduler (embedded)
      ├── Weekly Sun 03:00: sync_fienta_organizers   ├── Weekly Sun 03:30: cleanup_stale_data
      ├── Hourly: ingest_all_sources (job id; callable is ingest_all_enabled) ├── 6-hourly: dedup_pass + classify_pending + publish_pending + geocode_pending
      ├── Daily 04:30: refetch_event_details          ├── Daily 06:00: build_daily_feeds
      └── Daily 07:00: send_daily_digests
        ↓
Neon Postgres (eu-central-1, free tier, pgvector available for v1.1)
        ↓
LLM Router: Groq (primary) → Cloudflare Workers AI → Mistral (fallback chain)
```

**No Celery/Redis** — embedded APScheduler suffices for a single-process MVP. Deployment topology (Render Frankfurt/Cloudflare Pages/cron-job.org) is in `docs/backend-ops.md`.

## Pipeline at a Glance

Full detail (field-level authority tables, sub-pass ordering, tiering) in `docs/pipeline.md`.

1. **Ingestion** — Fienta API, HTML listing scrapers (Piletilevi/KUMU/Estonia Concert Hall), organizer self-submission. Newsletter inbound (`POST /webhooks/inbound-mail`, Svix-signature-verified, `extract_events_from_email()`) is fully wired up but dormant — `NEWSLETTER_SENDER_ALLOWED_DOMAINS` is an empty frozenset, so no sender is allowlisted yet.
2. **Deduplication** — rule-based pre-filter + LLM tiebreaker on surviving pairs; same-day title unions collapse timed-entry slots with no LLM call.
3. **Classification** — LLM assigns categories/vibes/quality/price/flags against a fixed 14-category/10-vibe taxonomy; ingest-set prices are authoritative over LLM-derived ones.
4. **Ranking** — `score = 0.45·persona_affinity + 0.20·recency_boost + 0.20·feedback_signal + 0.10·quality_score + 0.05·locality_bonus` (feedback_signal is `fb_normalized`, the raw [-1,1] feedback score mapped to [0,1] before weighting). Signed-out `/explore` uses the anonymous weight set (`SCORE_WEIGHT_ANON_*`): feedback drops out and its 0.20 is redistributed by scaling the three remaining differentiating terms by 1/0.80.
5. **Daily 5 builder** — 06:00 Europe/Tallinn; MMR-lite diversity capped at `DAILY_5_MAX_PER_CATEGORY` (2); series cooldown + backfill tiers guarantee `n=5`.
6. **Publish gate** — `app/publish.py::publish_pending()` promotes `classified` → `published` on quality/explicit/non-event/area/ended/title/bbox/organizer-trust checks; runs every 6h.
7. **Geocoding backfill** — bbox self-heal + organizer-`Venue` pass (with coord sync onto venue-linked events) + venue-name extraction + sibling-copy + Nominatim sub-passes, in that order; runs every 6h.
8. **Detail-refetch sync** — daily 04:30, reconciles venue/price/coords/localized text from source detail pages before the 06:00 feed build.

Four read paths (Daily 5 feed, Explore, Saved Events, public Landing showcase) and the Fienta organizer lifecycle (detect/skip/revive/retire/discover) are documented in `docs/pipeline.md`. LLM usage constraints (`LLM_MAX_TOKENS = 400` per call, `LLM_REASONING_MAX_TOKENS = 600` hard-cap ceiling used by the Groq and Cloudflare Workers AI entries (both `gpt-oss-120b`), dedup content-hash cache, Groq→Cloudflare Workers AI→Mistral fallback, backlog drain) and the three-layer NSFW/non-event content filters are also there.

## Auth, Security & the Organizer Portal

- **Auth** — three independent tracks, never interchangeable (separate salts/tables; see `CONTEXT.md`). Consumer + organizer: magic-link email (`itsdangerous` tokens, no third-party auth), httpOnly/Secure/`SameSite=Strict` session cookies (2-day TTL), `session_token_version` revocation, `email_verified` gate on the digest/feed builder. Google sign-in (`docs/adr/0002-google-sign-in-oauth-pkce.md`) coexists permanently with magic link on both tracks — server-side OAuth 2.0 authorization-code + PKCE, no third-party JS. Both tracks are flag-gated, defaulting to off in code (`GOOGLE_SIGNIN_CONSUMER_ENABLED`/`GOOGLE_SIGNIN_ORGANIZER_ENABLED`, `app/config.py`, both `False`; endpoints 404 when off) — the production values are dashboard-owned (`render.yaml`, `sync: false`), and the frontend build gates (`VITE_GOOGLE_SIGNIN_*`) are `"true"` in `frontend/wrangler.toml`. `sub` is the sole *identity* match key — email is a one-time linking-gate lookup on first sign-in only, never written from a Google token — with own linked-identity tables (`user_identities`/`organizer_identities`) that never merge across tracks. Admin console: password + required TOTP (`app/auth/totp.py`, RFC 6238) against `ADMIN_USERNAME`/`ADMIN_PASSWORD`/`ADMIN_TOTP_SECRET`, its own 12h cookie (`Path=/api/admin`, no revocation beyond TTL expiry); secret enrollment is the one-time local `backend/scripts/admin_totp_enroll.py`, not an endpoint. Full flow, residual-risk trade-offs, and the digest unsubscribe token in `docs/security.md`.
- **Security hardening** — rate limiting (every endpoint gets a `RATE_LIMIT_*`), security headers, CSP, body-size ceiling, `require_configured_secret` dev-fail-open double gate, admin auth lockout, external-URL sanitization (`safe_external_url()` vs `safe_fetchable_url()`, keyed on fetched-vs-rendered), stored-HTML sanitization (`sanitize_html()`/`html_to_text()` — the default ingest allowlist, plus a narrower `ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS`/`_ATTRS` passed at the organizer-submission boundary in `organizer_events.py`), redirect SSRF guard, webhook signature verification, CSRF (`CsrfOriginCheckMiddleware`, `app/main.py`, rejects mutating requests whose `Origin` isn't in `CORS_ORIGINS ∪ {FRONTEND_URL}` — second layer behind `SameSite=Strict`). Full detail in `docs/security.md` — read it before adding any new endpoint or external-facing URL field.
- **Organizer portal** — self-service submission with its own auth track (separate salts/tables from user auth), auto-publish gated on organizer trust (`verified` flag), admin post-hoc review queue, an organizer settings page (display name + theme preference), an authenticated organizer contact form (`/organizer/contact`, `app/routers/organizer_contact.py`), rich-text `description`/`important_info` authoring (`RichTextEditor`, Tiptap — sanitized server-side against the organizer allowlist), and saved venues — a per-organizer reusable `Venue` directory (`app/routers/organizer_venues.py`, `VenuePicker` in the submit/edit form). A venue-linked event leaves `venue_name`/`venue_address` NULL and resolves them at read time via `resolve_venue_name()`/`resolve_venue_address()`/`resolve_venue_coords()` (`app/routers/utils.py`) — never read those columns directly in a serializer. Full detail in `docs/organizer-portal.md` + `docs/data-model.md`.
- **Content reporting** — a signed-in user flags an event's hosted content via `POST /reports` (`app/routers/reports.py`, `ReportModal` on the frontend); admins resolve or take down from `/admin/reports`. "Report" ≠ feedback and ≠ the organizer review queue — see `CONTEXT.md`'s Content Moderation glossary before naming anything here.
- **Admin endpoints** — `/admin/*` requires the admin console's `/admin/auth` session cookie (TOTP-backed). HTTP Basic survives only on the two non-PII read-only routes (`GET /admin/counts`, `/admin/stats`, via `_require_admin`); everything else — every `POST` and every PII- or moderation-content-bearing `GET` (including `/admin/dedup/groups`, OWASP audit G-5) — is session-only (`get_current_admin`, OWASP H-1). Both auth surfaces share one consecutive-failure lockout counter — `POST /admin/auth/login` carries its own `RATE_LIMIT_ADMIN_LOGIN` bucket, and `admin_auth.py`'s other two routes carry their own too (`POST /admin/auth/logout` → `RATE_LIMIT_LOGOUT`, `GET /admin/auth/me` → `RATE_LIMIT_BROWSE`), all three separate from the `limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")` bucket the 22 routes in `app/routers/admin.py` share; all 12 job-trigger endpoints stream NDJSON progress — eleven through the shared `stream_admin_job()` helper, plus `POST /admin/pipeline/run`, which hand-rolls its own per-stage loop for stop-on-first-failure semantics — while `run_admin_job()` (`app/routers/utils.py`) backs the remaining non-streaming mutating `/admin/*` actions. Operate the pipeline via the admin console (`/admin/login`, `/admin` dashboard, `/admin/pipeline`, `/admin/dedup`, `/admin/submissions`, `/admin/reports`, `/admin/events/:id`), not curl. Full detail in `docs/backend-ops.md`.

## i18n

**Single source of truth:** `shared/i18n/{en,et,ru}.json`, `shared/personas.json`, `shared/app-config.json`, `shared/calendar.json`.

**Workflow (hard rule):** Edit the JSON files in `shared/` → run `python scripts/generate_shared.py` → commit both the JSON and the updated `_generated` files. **Never edit `_generated/` directly.** `backend/tests/test_generated_sync.py` is a drift guard — if it fails, regenerate and commit.

Frontend imports generated strings via `frontend/src/i18n.ts`; backend via `backend/app/i18n.py`. Email presentation (styles/templates/assembly three-file split) and per-email specifics are in `docs/frontend.md`.

## Frontend Structure

Each component/route lives in its own folder: `Name.tsx` + (usually) `Name.module.css` + a one-line `index.ts` barrel — a handful of folders (`AdminApp/`, `Privacy/`, `Terms/`, `AdminThemeToggle/`, `LocaleSelector/`, `SeoTags/`, `ThemeSelector/`) have no stylesheet. Routes in `frontend/src/routes/`, shared components in `frontend/src/components/`, CSS design tokens are **mandatory** (never hardcode colors/spacing/radii — see Code Quality Rules below), shared CSS chrome composes from `frontend/src/components/shared/`. Hooks/utils/constants each have one canonical home (`frontend/src/hooks/`, `frontend/src/utils.ts`, `frontend/src/constants.ts`) — check there before writing a new one. Non-component homes: `frontend/src/api/client.ts` (the single fetch wrapper), `frontend/src/lib/` (auth/locale/theme/analytics/SEO-prerender modules), `frontend/src/content/legal/` (per-locale legal-doc data behind `LegalPage`), `frontend/scripts/` (build-time prerender + icon generation), `frontend/functions/` (the live Cloudflare Pages Functions — API proxy, SPA fallback, SEO audit, prerender-cadence — see `docs/backend-ops.md`) and `frontend/api/` (their now-idle Vercel Serverless Functions predecessor, kept as the migration's rollback path per issue #341/#348, not deleted). Tests are co-located as `Name.test.tsx`/`Name.test.ts` — the one exception is the Cloudflare Pages Functions: `frontend/functions/` stays test-free (Cloudflare's file-based routing would claim a `.test.ts` there as a route), so its tests live in `frontend/tests/functions/`, mirroring the tree. `npm run lint` covers `src scripts api functions`. Full folder-by-folder breakdown in `docs/frontend.md`.

Two routing facts that bite: every `ROUTE_DEFS` entry is registered at both its bare path and a `/:locale` prefix (`/`, `/explore` and `/events/:id` are the three `noRedirect` SEO routes — their bare path always renders Estonian and never redirects); the admin console lives entirely outside that loop in its own `React.lazy` chunk (`routes/AdminApp/`), un-i18n'd and reachable only by typed URL.

## Design System

One visual language — **C1**: editorial-cinematic type (Cormorant Garamond display) over the existing navy/gold brand, hairline rules instead of boxes, sharp interactive corners, no decorative iconography, imagery that amplifies but is never load-bearing. Full detail — token groups, per-surface registers, theming machinery, motion vocabulary, settled decisions — in `docs/design-system.md`. **Read it before any visual change.** The imperatives:

- **Four registers, one token system.** Landing (hero display + poster imagery), consumer app and organizer portal (Cormorant on headings/eyebrows/card titles, Manrope everywhere else), and the admin console's **sub-language**: `--font-system` (OS-native sans) + `--font-mono` for data, never `--font-display` or `--font-body`, no imagery/scrims/display scale. Admin inherits colors, spacing, hairlines and geometry only.
- **Sharp corners are universal and already in the base classes.** `border-radius: 0` on every button/input/menu (`Button`/`Field`/`Menu`/`Bar` shared modules); `--radius` is untouched on cards, images, and chips. There is no `buttonSharp`/`fieldSharp`/`menuSharp` variant to compose — don't reintroduce one.
- **Dark is the origin palette; `:root[data-theme="light"]` is a literal inversion** redefining only the tokens that need a light value. Never define a color solely inside the light block. Theme resolution (`account → localStorage → OS`) lives in `frontend/src/lib/theme.ts`, duplicated minimally by an inline pre-paint script in `frontend/index.html` — the two must never disagree. Emails default to **light** (`app/email/styles.py::get_email_styles`).
- **A new webfont must clear two gates**: `@fontsource` self-hosted (CSP is `font-src 'self'` — no CDN link) and a `cyrillic` subset (`ru` is first-class; a missing cut silently falls back to `system-ui`).
- **Size display type against Estonian/Russian strings, never English** — ET/RU run ~1.6× longer. Display sizes are `clamp()` tokens (`--font-size-display-*`), not per-component inline clamps.
- **Breakpoint tokens are documentation only** — `--bp-narrow: 640px` names the value (`frontend/src/index.css`; no `--bp-wide` token exists); `@media` rules still carry the literal (custom properties can't drive media conditions). Keep them in sync.
- **Motion must collapse under `prefers-reduced-motion` and survive the prerender gate.** `.rise` uses fill-mode `backwards`, not `both` — `both` leaves a computed transform that breaks `position: fixed` descendants.
- **`EventCard` has two variants** (`standard`/`featured`), **`EmptyState` has no icon prop**, and no *new* pictographic emoji ships in consumer/organizer UI — functional Unicode marks (`✓ ✕ ⚠ ☰`) are allowed everywhere, and `FeedbackButtonRow`'s three signal glyphs (`👍 👎 🔖`, `SIGNAL_CONFIG` in `constants.ts`) are the one live pre-C1 carryover. All were settled after a build-and-revert; see the doc's "Settled" table before proposing otherwise.

## Code Quality Rules

Full rationale for each rule (why it works this way, trade-offs accepted) is in `docs/conventions.md`. These are the imperatives:

- **Backend constants** — all literals in `app/constants.py` (LLM prompts in `app/llm/prompts.py`, scrape selectors in `app/ingestion/selectors.py`; cross-stack via `shared/`). Never define a constant near business logic.
- **Backend utilities** — all shared helpers in `backend/app/routers/utils.py`. Check there before writing a new one. Exception: `get_current_user` (`app/routers/auth.py`), `get_optional_user` (`app/routers/auth.py`), and `get_current_organizer` (`app/routers/organizer_auth.py`) are FastAPI `Depends` auth entry-points, not reusable helpers — each is defined once and consumed via `Depends()` by other routers, so the anti-duplication rationale doesn't apply. Second exception: the admin-lockout helpers (`check_admin_lockout`, `record_admin_auth_failure`, `clear_admin_auth_failure`, `admin_username_disabled`, `admin_credentials_ok`) stay in `app/routers/admin.py` and are imported by `admin_auth.py` — they're inseparable from that module's `_admin_auth_failures` LRU state. Full rationale in `docs/conventions.md`.
- **Frontend constants** — all magic values in `frontend/src/constants.ts` (cross-stack via `shared/`). Never inline a literal near component logic.
- **Frontend utilities** — all shared helpers in `frontend/src/utils.ts`. Check there before writing a new one.
- **CSS design tokens** — colors, radii, shadows, z-indices, transitions, spacing, typography, component-geometry vars are all tokenized in `:root` (`frontend/src/index.css`). Never hardcode — define the token first, then `var(--token-name)`. Token groups and the light-theme rules are in `docs/design-system.md`.
- **CSS shared base classes** — card/button/menu chrome lives in `frontend/src/components/shared/` (18 `.module.css` files, mapped in `docs/design-system.md`, plus the one `GoogleSignInButton/` component folder). Use CSS Modules `composes` — never copy-paste, and never restyle a base class in place for one consumer; add a modifier variant instead.
- **Retry logic** — all HTTP calls use `http_get()`/`http_post()` from `app/ingestion/http_client.py` (tenacity backoff, 429 `Retry-After` honored). Seven documented bypass sites (inline-request-latency, fallback-chain, or own-caching reasons) — see `docs/conventions.md`; do not add an eighth without one.
- **DB connection pooling** — `app/db.py` uses `pool_pre_ping=True` + `pool_recycle` below Neon's idle-suspend window.
- **HTML listing adapters** — subclass `HtmlListingAdapter` (`app/ingestion/sources/html_base.py`); don't duplicate the fetch/parse loop or hreflang logic.
- **Presentation layer separation** — CSS in `styles.py`, markup in `templates.py`, assembly in the delivery module (see the email package). No templating engine. Exception: `app/email/contact.py` (internal-only mail).
- **Encapsulation** — a leading underscore is module-private; never import a `_name` cross-module (drop the underscore instead). Rule is intra-project — a third-party library's own documented public export (e.g. slowapi's `_rate_limit_exceeded_handler`) isn't ours to rename. Tests may import private names.
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
- **Shared test fixtures** — backend: `backend/tests/conftest.py` fixtures `mock_db`, `make_user`, `make_organizer`, `make_event`, `make_venue`, `make_report`, `make_request`, `patch_client`; `session_factory` and `assert_hardened_cookie` are importable helpers, not fixtures. Package-level conftests add more: `tests/routers/conftest.py` (`admin_app`, `make_db_ctx` fixtures, the `ndjson_lines`/`scalars_returning`/`execute_rows` helpers, plus autouse admin-lockout, public-cache and rate-limiter resets), `tests/auth/conftest.py` and `tests/ingestion/conftest.py` (plain helper functions, not fixtures). Frontend: `frontend/src/test/utils.tsx` (`renderWithProviders`, `makeQueryWrapper`, `makeRouterQueryWrapper`, `makeEvent`, `LocationProbe`); mock the `api` module, not `fetch`.
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
