# Event Radar

> AI-powered event discovery for Tallinn — a personalized **Daily 5** curated feed for every user.

Event Radar ingests events from Tallinn's ticketing platforms, venue sites, and organizer submissions, then deduplicates and classifies them with an LLM and ranks them against each user's personas and feedback. The result is a tight, five-event daily digest instead of an endless listings page — delivered in **Estonian, English, or Russian**.

The whole platform is designed to run on **near-free managed infrastructure**: the backend is the only paid line item (Render's Starter plan, Frankfurt); the frontend, database, LLM providers, email, images, and cron pings all sit on free tiers.

## Features

- **Multi-source ingestion** — Fienta API, HTML listing scrapers (Piletilevi, KUMU, Estonia Concert Hall) sharing a common adapter, organizer self-submission, and inbound newsletter parsing via email webhook (landed but dormant — no sender domain is allowlisted yet, and the newsletter source has no ingestion adapter, so its stored raw rows never become events). A multi-pass geocoding backfill (out-of-bbox self-heal, organizer venue directory sync, venue-name address extraction, sibling copy, Nominatim lookup) fills in venue coordinates that sources don't provide, a daily detail-refetch sync reconciles venue/price/coordinates against each event's source page, and per-locale page fetches capture localized `et`/`en`/`ru` titles and descriptions at ingest.
- **Two-stage deduplication** — a cheap SQL + fuzzy pre-filter narrows candidate pairs, then an LLM tiebreaker resolves only the survivors. Decisions are cached by content hash to avoid repeat LLM calls.
- **LLM classification** — assigns a fixed 14-category / 10-vibe taxonomy, a quality score, an explicit-content flag, a non-event flag, a parsed price range, an in-target-city signal, a free-tier flag, a detected language, and a localized 3-bullet "why go?" rationale, with a Groq → Cloudflare Workers AI → Mistral provider fallback chain.
- **3-layer NSFW filter** — a keyword prefilter at ingest time, an LLM-assigned explicit-content flag, and a publish gate that excludes flagged events from the published feed.
- **3-layer non-event filter** — the same pattern applied to gift cards/merch/webinars, so the published feed only surfaces real attendable events.
- **Publish gate** — classified events are promoted to `published` only once they clear a minimum quality score, pass the NSFW and non-event checks, pass a location check, carry a non-empty title, haven't already ended, (if geocoded) fall within the Tallinn region, and — for organizer submissions — come from a `verified` organizer. Rejects stay `classified` with a per-reason breakdown.
- **Persona-based personalization** — users rank 1–3 of 9 personas at onboarding (each pick weighted by position); like/dislike/bookmark signals continuously retune their ranking.
- **Daily 5 builder** — a scheduled job scores upcoming events and writes a diverse five-event feed per user each morning, then emails a digest.
- **Explore discovery grid** — a searchable, filterable (keyword, category/vibe, date, free-only, for-you), and sortable (relevance/date/price/quality) view over all upcoming published events. Public: signed-out visitors get the same result set scored by a persona-free anonymous formula (plus signed-out chrome and a sign-in upsell); signed-in users get the personalized ranking path.
- **Saved Events** — a dedicated page listing the events a user has bookmarked, liked, or disliked, tabbed by signal and paginated.
- **Public landing showcase** — a fixed-size grid of six top-quality published events happening this week (widening to a 30-day window on a thin week), shown on `/` when signed out. No personalization, no PII. Together with signed-out `/explore` and single-event detail (`GET /events/{id}`, optional auth), it forms the unauthenticated read surface.
- **Organizer portal** — self-service event submission for venues/promoters: its own magic-link auth track (separate table, tokens, and signing salts from user auth, also with Google sign-in available — see below), a submit/edit form with per-locale `et`/`en`/`ru` text, up to three organizer-chosen categories, and rich-text `description`/`important_info` authoring (Tiptap, sanitized server-side against a narrower organizer allowlist), signed Cloudinary image upload, a reusable per-organizer saved-venue directory picked from the form, an organizer settings page (display name, log out everywhere, linked-identity/unlink-Google), an authenticated organizer contact form, per-account daily submission/image-upload/venue-creation caps, and an admin review queue. A submission from a `verified` organizer auto-publishes through the normal publish gate; a brand-new organizer's first submission waits in the queue until an admin approves it (which flips the organizer to `verified`).
- **Event claiming** — an organizer can claim an event already ingested from Fienta, KUMU, Estonia Concert Hall, or Piletilevi by proving ownership of its Publisher (or, failing that, its Series) through a per-source proof channel — a Fienta token round-trip, DNS-TXT on the institution's or promoter's domain, or a Piletilevi contact-mailbox match — with anything unprovable falling to admin review. Verified proof preempts rival pending claims; abandoned claims expire (7 days for self-fixable mechanisms, 30 for admin review). Once granted, the organizer edits the event directly, and claimed fields are pinned against ingestion/refetch overwrite. A public "is this your event?" panel on the event page starts the flow; organizers get grant/decline/expiry emails. See `docs/organizer-portal.md` and `docs/adr/0004-claim-eligibility-tightening.md`.
- **Content reporting** — a signed-in user can flag an event's hosted content from the event card or detail page (`POST /reports`); the report lands in an admin queue with an email notification, an admin can resolve it or take the event down, and the reporter is emailed the outcome.
- **Admin console** — an operator-facing SPA at `/admin/*` (its own lazy-loaded chunk, un-i18n'd, reachable only by typed URL): dashboard, pipeline runner with a live per-stage breakdown, dedup-group review, organizer-submission queue, claim queue, report queue, and a single-event inspector. Its own auth track — username/password + required TOTP, a 12h `Path=/api/admin` cookie — with a per-client consecutive-failure lockout on the login endpoint. HTTP Basic is gone entirely; every `/admin/*` route is session-only.
- **Magic-link auth** — passwordless sign-in with short-lived (15-minute), single-use links and 2-day sessions carried in an httpOnly / Secure / `SameSite=Strict` cookie, revocable per user via a token version.
- **Google sign-in** — coexists permanently with magic link on **both** the consumer and organizer tracks: server-side OAuth 2.0 authorization-code + PKCE (S256), no third-party JS, no OAuth library (hand-rolled on `httpx` + `PyJWT`, ID token verified via JWKS), scope `openid email` only. `sub` is the sole identity key, stored in per-track `user_identities` / `organizer_identities` tables that never merge across tracks. Auto-links only for `GOOGLE_AUTHORITATIVE_EMAIL_DOMAINS` (gmail.com/googlemail.com); otherwise a confirm-by-email linking gate. Both tracks are flag-gated off by default (`GOOGLE_SIGNIN_CONSUMER_ENABLED` / `GOOGLE_SIGNIN_ORGANIZER_ENABLED` — endpoints 404 when off), and unlinkable from Settings / Organizer settings. See `docs/adr/0002-google-sign-in-oauth-pkce.md`.
- **Email digest opt-out** — one-click unsubscribe (RFC 8058 `List-Unsubscribe` header + a token-signed no-login page with an Undo/resubscribe button) toggles the daily digest without a sign-in.
- **Static pages** — a globally mounted site footer links to localized Privacy, Terms, and FAQ pages plus a Contact form (email-only delivery, honeypot + rate limit, no login). The FAQ (`/faq`) is public, prerendered in all three locales, and supports deep links that open and scroll to an answer.
- **Full trilingual i18n** — every UI string, email, and LLM output supports `et` / `en` / `ru` from a single shared source of truth.
- **C1 design system + theming** — one editorial-cinematic visual language (Cormorant Garamond display over the navy/gold brand, hairline rules, sharp interactive corners) across four registers: Landing, consumer app, organizer portal, and the admin console's data-oriented sub-language. Dark is the origin palette; light is a token-level inversion. The theme follows the device (OS) theme; a viewer can override it to light or dark per browser, and that override expires the next time the device theme changes (`docs/adr/0003-device-theme-with-expiring-override.md`). There is no account-level theme. Emails render from one light-base bundle with a `prefers-color-scheme` dark override, so the mail client decides.
- **SEO prerendering + live audit** — a build-time pipeline (`frontend/scripts/prerender.ts`, Playwright) snapshots Landing, Explore, the FAQ, and every published `/events/:id` (all three locale variants) into static HTML with per-page meta tags/JSON-LD, writes `sitemap.xml`/`robots.txt`, and validates its own output before the build can pass. A cron-job.org-driven "cadence" rebuild keeps snapshots fresh every 6h, chaining continuation rounds when one build can't finish in its time budget — with a per-burst chain-state manifest in Cloudflare R2 so later rounds read a resolved page back out of storage instead of re-fetching production. An independent live-audit function checks production directly every 6h and self-files/closes a GitHub issue on failure/recovery, so a silently-dead cadence still gets caught.
- **Security-hardened** — OWASP Top 10 mitigations: per-IP rate limiting, strict security headers, CORS lockdown, an Origin-checking CSRF layer behind `SameSite=Strict` cookies, external-URL and stored-HTML sanitization, a body-size ceiling, admin auth lockout, webhook signature verification, and a CVE audit in CI.
- **Data retention** — a weekly cleanup prunes aged satellite/audit rows (auth tokens, raw ingestion payloads, raw inbound emails, ingestion runs, LLM-call logs, old feed snapshots) plus stale never-verified user and organizer accounts, while preserving all event history and feedback from real accounts indefinitely.

## Architecture

```
Vite + React SPA  ──HTTPS / JSON──▶  FastAPI (single process)
                                       ├── Routers: /auth /admin /admin/auth /onboarding /events
                                       │            /explore /feed /feedback /public /reports
                                       │            /users/me /contact /email /webhooks
                                       │            /organizer/auth /organizer/events
                                       │            /organizer/profile /organizer/venues
                                       │            /organizer/contact /organizer/claims
                                       └── APScheduler (embedded, always-on compute — no keepalive ping)
                                           ├── Weekly Sun 03:00: sync_fienta_organizers
                                           ├── Weekly Sun 03:30: cleanup_stale_data
                                           ├── Hourly:    ingest_all_enabled (job id: ingest_all_sources)
                                           ├── 6-hourly:  dedup_pass + classify_pending +
                                           │              publish_pending + geocode_pending +
                                           │              backfill_publisher_ids
                                           ├── 04:30 EET: refetch_event_details
                                           ├── 05:00 EET: expire_stale_claims
                                           ├── 06:00 EET: build_daily_feeds
                                           └── 07:00 EET: send_daily_digests
                                             ↓
                                   Neon Postgres (eu-central-1, pgvector-ready)
                                             ↓
                            LLM Router: Groq → Cloudflare Workers AI → Mistral
```

There is intentionally **no Celery/Redis** — an embedded APScheduler is sufficient for a single-process MVP.

The processing pipeline:

```
fetch → raw_events → normalize → events(draft) → dedup → classify → events(classified) → publish gate → events(published) → rank → daily_feeds → digest
```

Geocoding runs as a separate backfill alongside this pipeline, filling in `lat`/`lng` for events that lack coordinates. It is a chain of sub-passes in a fixed order: self-heal coordinates that fall outside the Tallinn bbox, geocode organizer-owned `Venue` rows and sync their coordinates onto venue-linked events, extract an address out of a venue *name*, copy from an already-geocoded sibling event at the same venue, and finally a rate-limited Nominatim lookup.

## Tech stack

| Layer       | Technologies |
|-------------|--------------|
| Backend     | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, APScheduler, Pydantic Settings, nh3 (HTML sanitization), slowapi (rate limiting), itsdangerous (signed tokens), pyotp (admin TOTP), PyJWT[crypto] (Google ID-token verification) |
| Frontend    | Vite 8, React 18, TypeScript, TanStack Query 5, React Router 7, CSS Modules, Tiptap (organizer rich text), DOMPurify, Vitest + Testing Library |
| Database    | Neon Postgres (async via `asyncpg`) |
| LLM         | Groq (primary), Cloudflare Workers AI, Mistral (fallback chain) |
| Email       | Resend (magic links, daily digests, contact-form relay, report notifications and reporter outcomes, claim outcome emails, inbound newsletter webhook) |
| Images      | Cloudinary (signed server-side upload for organizer-submitted event images) |
| SEO         | Playwright (build-time prerender snapshots), Cloudflare Pages Functions (`frontend/functions/api/`) for the prerender-cadence gate and live SEO audit, Cloudflare R2 (`@aws-sdk/client-s3`) for the prerender chain-state manifest |
| Hosting     | Render (backend web service, Frankfurt, Starter plan) · Cloudflare Pages (frontend, `eventradar.ee`) · cron-job.org (prerender-cadence + live SEO audit pings) |

## Getting started

### Prerequisites

- **Python 3.12**
- **Node.js 24** and npm — matches CI and Cloudflare Pages (`NODE_VERSION` in `frontend/wrangler.toml`); Vite 8's own floor is 20.19+ / 22.12+
- A **PostgreSQL** database — [Docker Compose](#2-set-up-the-database) is the recommended local path (see below); a free [Neon](https://neon.tech) project also works out of the box for production-like testing.

> [!NOTE]
> External API keys (Groq/Cloudflare Workers AI/Mistral for LLM, Resend for email) are **optional for local development**. Without LLM keys, dedup falls back to its rule-based matches (LLM-tiebreaker pairs stay unmerged) and classification fails per event, so nothing clears the publish gate and the feeds stay empty. Without Resend, emails are logged to the console instead of being sent. Provide them when you want the full pipeline.

### Option 0 — VS Code Dev Container (recommended on Windows)

One-click Python 3.12 + Node 24 + Postgres 16, matching CI exactly — no local venv, no Windows/Linux `node_modules` conflicts.

Prerequisites: Docker Desktop (WSL2 backend) and the VS Code [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension.

```bash
docker compose down   # free port 5432 if a host `db` container is already running
```

Then **F1 → Dev Containers: Reopen in Container**. `postCreateCommand` (`.devcontainer/post-create.sh`) creates `backend/.env` with a generated `SECRET_KEY`, installs the Python and npm dependencies, and runs `alembic upgrade head` automatically — skip step 1 and step 3's venv/install lines below. There is no venv step: the image ships a ready interpreter at `/opt/venv/bin/python`, already on `PATH`. The backend and frontend dev servers then start automatically from the container lifecycle (`postStartCommand` → `.devcontainer/post-start.sh` → `dev-server.sh start`, on every container start) — no manual commands, no VS Code task/trust preconditions. Logs land in `/tmp/event-radar-dev/{backend,frontend}.log` inside the container; check `bash .devcontainer/dev-server.sh status`, or `restart`/`stop` a service the same way. The `logs: backend` / `logs: frontend` VS Code tasks tail those files (`bash .devcontainer/dev-server.sh logs backend|frontend`) and auto-open as a split terminal panel on container open — first time per workspace, run Command Palette → *Tasks: Allow Automatic Tasks* and reload the window, otherwise start them by hand via *Tasks: Run Task*. If you need to run a server in the foreground instead, use Command Palette → *Tasks: Run Task* → `dev: backend (uvicorn)` / `dev: frontend (vite)`, or run manually:

```bash
cd backend && uvicorn app.main:app --reload   # terminal 1
cd frontend && npm run dev                     # terminal 2
```

Notes:
- `DATABASE_URL` comes from the container environment and overrides `backend/.env` — no `.env` edit needed for the database.
- The container's Postgres is a **separate volume** from the host's `docker-compose.yml` `db` service; data doesn't carry over automatically.
- The interpreter is always `/opt/venv/bin/python` — no activation step, ever. VS Code's Python extension may still surface a stale interpreter path carried over from the host via Settings Sync; if so, one-time fix with *Python: Select Interpreter* → `/opt/venv/bin/python`.
- The embedded scheduler is **off** in the container (`ENABLE_SCHEDULER=false`) so `uvicorn --reload` left running overnight can't arm hourly scrapes, real LLM spend, or a real digest send. To exercise the real cadence for one session: `bash .devcontainer/dev-server.sh stop backend`, then run `ENABLE_SCHEDULER=true uvicorn app.main:app --reload` by hand. With it off, `GET /feed` stays empty until you run `POST /admin/build-feeds` — that's expected, not a bug.
- `.devcontainer/mem-watchdog.sh` is a manual, unwired diagnostic for the intermittent "reload the VS Code window" hang — run it by hand when chasing that; it's not part of the normal dev loop.
- `.devcontainer/claude-plugins.json` declares Claude Code plugins that are enabled only inside the container (currently `mattpocock-skills`); `sync-claude-config.sh` merges it into the container's `~/.claude/settings.json` on every start, never touching the host's config.
- `gh` is installed and auto-authenticated on start/attach (`.devcontainer/gh-auth.sh`) from the host's forwarded git credential helper. If `gh auth status` is red, re-run that script or `gh auth login`.

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

- `SECRET_KEY` — a random secret, minimum 32 characters; generate one with `python -c "import secrets; print(secrets.token_hex(32))"` (already satisfies the minimum)

Optionally add `GROQ_API_KEY` / `CLOUDFLARE_WORKERS_AI_API_KEY` + `CLOUDFLARE_WORKERS_AI_BASE_URL` / `MISTRAL_API_KEY` and `RESEND_API_KEY` to enable LLM classification and real email delivery. See `.env.example` for the full list of overridable settings (data sources, persona vectors, admin auth, CORS).

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

The Vite dev server proxies `/api` requests to the backend at `http://127.0.0.1:8000` (deliberate — `localhost` can resolve to IPv6 `::1`, see `frontend/vite.config.ts`). No frontend env vars are required by default; `VITE_GOOGLE_SIGNIN_CONSUMER_ENABLED` / `VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED` (see `frontend/.env.example`) gate the Google sign-in button locally when set.

Open http://localhost:5173 and sign in with a magic link. Without `RESEND_API_KEY` configured, no email is sent and the link URL is logged at **DEBUG** level — set `LOG_LEVEL=DEBUG` in `backend/.env` and copy the `Dev-only magic link URL:` line from the backend console to complete sign-in.

## Project structure

```
event-radar/
├── .devcontainer/             # VS Code Dev Container (Python 3.12 + Node 24 + Postgres 16)
├── .vscode/tasks.json         # dev-server run/logs tasks (see Option 0 above)
├── CLAUDE.md                  # engineering conventions and codebase guidance
├── CONTEXT.md                 # domain glossary
├── VERSION                    # current release version
├── backend/                  # FastAPI application
│   ├── app/
│   │   ├── routers/          # /auth /admin /admin/auth /onboarding /events /explore /feed /feedback /public /reports /users/me /contact /email /webhooks /organizer/auth /organizer/events /organizer/profile /organizer/venues /organizer/contact /organizer/claims
│   │   ├── ingestion/        # source adapters (Fienta, HTML listings), geocoding backfill, detail-refetch sync, Fienta organizer sync, publisher-id backfill, HTML/URL sanitization
│   │   ├── claims/           # event claiming: target resolution, per-source verification, claim lifecycle, field pinning
│   │   ├── dedup/            # rule-based pre-filter + LLM tiebreaker
│   │   ├── llm/              # provider router, classifier, prompts, newsletter extractor (taxonomy lives in app/_generated/)
│   │   ├── ranking/          # scoring + Daily 5 builder
│   │   ├── email/            # digest / magic-link / contact / report-notification / reporter-outcome / claim-outcome — styles / templates / delivery, shared Resend send
│   │   ├── auth/             # magic-link tokens + email, Google OAuth (PKCE), admin TOTP (RFC 6238) + lockout, cross-router auth Depends
│   │   ├── models/           # SQLAlchemy models
│   │   ├── _generated/       # generated constants & i18n (do not edit by hand)
│   │   ├── constants.py      # single source of truth for backend literals
│   │   ├── config.py         # environment settings
│   │   ├── db.py             # async SQLAlchemy engine/session (pool_pre_ping, pool_recycle)
│   │   ├── i18n.py           # backend-side i18n lookup
│   │   ├── publish.py        # publish gate (classified → published)
│   │   ├── cleanup.py        # weekly data-retention pruning
│   │   ├── rate_limit.py     # slowapi per-IP limiter
│   │   ├── logging_config.py # JSON logging + optional external log drain
│   │   ├── seeds.py          # persona + source seeding on startup
│   │   └── main.py           # app wiring, middleware, scheduler
│   ├── alembic/             # migrations
│   ├── scripts/             # one-off operational scripts (reset_events.py, _reclassify_events.py, admin_totp_enroll.py, backfill_publisher_ids.py)
│   └── tests/               # pytest suite
├── frontend/                 # Vite + React SPA
│   ├── functions/            # live Cloudflare Pages Functions: api/[[path]].ts (backend proxy), [[path]].ts (SPA fallback), api/prerender-cadence.ts, api/seo-audit.ts, plus _shared/ (Pages Function types + JSON helper) — tests live in frontend/tests/functions/ (a .test.ts here would be claimed as a route)
│   ├── public/               # static assets + _headers (security headers/CSP) + _routes.json (keeps assets off the Functions path)
│   ├── scripts/              # build-time prerender snapshot pipeline (prerender.ts, Playwright) + generate-icons.ts
│   ├── tests/functions/      # tests for frontend/functions/, mirroring its tree
│   ├── wrangler.toml         # Cloudflare Pages build config (output dir, [vars]) — source of truth, like render.yaml
│   └── src/
│       ├── routes/          # Landing, Login, AuthVerify, Onboarding, Feed, Explore, SavedEvents, EventDetail, Settings, Unsubscribe, Privacy, Terms, Faq, Contact, NotFound
│       │                    #   + organizer portal (OrganizerLogin, OrganizerVerify, OrganizerDashboard, OrganizerSettings, OrganizerContact, EventSubmit — also serves /organizer/events/:id/edit)
│       │                    #   + event claiming (OrganizerClaimVerify, ClaimPending, ClaimEventEdit, ClaimEvents)
│       │                    #   + admin console, own lazy chunk (AdminApp, AdminLogin, AdminDashboard, AdminPipeline, AdminDedup, AdminSubmissions, AdminClaims, AdminReports, AdminEventDetail)
│       ├── components/      # EventCard, PersonaCard, TopBar, OrganizerTopBar, OrganizerProfileNudge, VenuePicker, RichTextEditor, ClaimStrip, ClaimEventPicker, ReportModal, CategoryPicker, PrefsMenu (language + theme), AccountMenu, Footer, AdminShell, AdminThemeToggle, form controls, shared/ (CSS base classes + GoogleSignInButton) ...
│       ├── hooks/           # useAuth, useFeedback, useDropdown, useOrganizerAuth, useAdminAuth, useSeoMeta, useResolvedTheme, useClaimEventEdit ...
│       ├── lib/             # auth/organizer/admin subscriber stores + signed-in hint & locale storage (the session itself is an httpOnly cookie), theme resolution (theme.ts), analytics (gtag.ts), Google sign-in landing helper (googleSignInLanding.ts), build-time CSP inline-script hashing (csp.ts), SEO/prerender modules (githubRequest, jsonLd, prerenderChain, prerenderQueue, r2ChainState, seoAudit, seoAuditAuth, seoAuditIssue, seoValidation, structuredData, urlLocale)
│       ├── api/             # API client (user, organizer, and admin wrappers + NDJSON admin stream)
│       ├── content/legal/   # localized Privacy/Terms documents
│       ├── content/faq/     # localized FAQ documents (per-locale data behind the Faq route)
│       ├── _generated/      # generated constants & i18n (do not edit by hand)
│       └── i18n.ts          # i18n helpers
├── shared/                   # cross-stack source of truth (i18n, personas, config, calendar)
├── docs/                     # deep-dive docs: pipeline, security, backend-ops, frontend,
│                             # design-system, conventions, data-model, organizer-portal,
│                             # observability, adr/ (architecture decisions),
│                             # agents/ (agent workflows)
├── scripts/generate_shared.py# regenerates the _generated/ files in both stacks
├── docker-compose.yml        # local Postgres 16
├── .github/workflows/        # CI: pytest + Vitest + alembic round-trip, weekly dependency CVE audit
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

Both suites also run in CI (`.github/workflows/tests.yml`) on every push/PR to `master`, alongside a third `migrations` job in the same workflow that round-trips the full alembic chain against a `postgres:16` service (`upgrade head` → `downgrade base` → `upgrade head`, then `alembic check` to catch a model changed without a matching migration), and a `pip-audit` + `npm audit` CVE sweep (`.github/workflows/dependency-audit.yml`) that runs on every push/PR to `master` **and** a weekly Mon 04:00 UTC cron.

> [!NOTE]
> Ruff, mypy, ESLint, and `npm run type-check` are house rules with **no CI enforcement** — a green PR doesn't mean they were run. Run them locally before committing.

### Editing shared values & translations

Strings, taxonomies, persona definitions, and cross-stack scalars live in `shared/`. After editing any file there, regenerate the per-stack `_generated/` files and commit both:

```bash
python scripts/generate_shared.py
```

> [!IMPORTANT]
> Never edit files under `_generated/` directly. A test (`backend/tests/test_generated_sync.py`) fails if the generated output drifts from `shared/`.

### Manually triggering pipeline jobs (E2E testing)

The scheduled jobs described in [Architecture](#architecture) (`sync_fienta_organizers`, `cleanup_stale_data`, `ingest_all_enabled`, `dedup_pass`, `classify_pending`, `publish_pending`, `build_daily_feeds`, `send_daily_digests`, `geocode_pending`, `refetch_event_details`) can each be run on demand from the admin console — useful for exercising the full pipeline end to end without waiting for the schedule. The two claim-related jobs, `backfill_publisher_ids` and `expire_stale_claims`, are scheduler-only (no admin trigger); the publisher backfill also has a one-off CLI, `backend/scripts/backfill_publisher_ids.py` (dry run by default, `--yes` to apply).

Sign in at `/admin/login` (username/password + TOTP, see `docs/backend-ops.md`), then use `/admin/pipeline` to trigger any stage individually or run the full `POST /admin/pipeline/run` sequence in one click — it streams a live per-stage result breakdown and gates destructive/expensive triggers (digest send, cleanup delete) behind an explicit confirmation. `/admin/dedup` reviews dedup groups, `/admin/submissions` is the organizer-submission review queue, `/admin/claims` is the event-claim queue (grant/decline/revoke), `/admin/reports` is the report queue, `/admin/events/:id` is the single-event inspector, and `/admin` is the dashboard landing page. See `docs/backend-ops.md` for the full endpoint/screen breakdown.

### Resetting event data

`backend/scripts/reset_events.py` wipes **all** event and pipeline data and resets auto-increment IDs to 1 — useful for clearing out test/bad ingested data and starting the pipeline from a clean slate. It truncates the event, raw-event, source-link, classification, feedback, daily-feed, ingestion-run, LLM-call, and inbound-email tables (`RESTART IDENTITY CASCADE` — so event reports, which reference events, go too), then resets each source's last-run state so ingestion re-fetches everything. **Users, organizers, personas, the source registry, publishers, and claims are preserved** — though claim edits pinned onto the wiped events are lost with them.

```bash
cd backend                              # with the venv active
python scripts/reset_events.py          # dry run: prints target DB + per-table row counts
python scripts/reset_events.py --yes    # actually truncate
```

> [!WARNING]
> The `--yes` truncate is permanent and cannot be undone. The dry run (no flag) prints the masked `DATABASE_URL` it would hit and the current row counts — check that the target is the DB you expect before passing `--yes`.

## Deployment

Production is split across three services: **Render** (backend, Frankfurt, Starter plan), **Cloudflare Pages** (frontend, serving `eventradar.ee`), and **cron-job.org** (the two SEO freshness pings below).

> [!IMPORTANT]
> Cloudflare Pages builds production from the **`release`** branch, not `master`. `master` is the CI/PR branch; a non-`release` Pages build skips the prerender pass entirely (`PRERENDER_CADENCE_GIT_BRANCH`, `frontend/src/constants.ts`).

- **Backend — Render web service** (`render.yaml`): `plan: starter`, `region: frankfurt`, `rootDir: backend`, health check on `/health`, `PYTHON_VERSION` pinned to 3.12 to match CI and the dev container. Migrations run via `preDeployCommand: alembic upgrade head`, ahead of `startCommand` (`uvicorn app.main:app ...`) on every deploy — the Starter plan makes `preDeployCommand` available, unlike the old free tier, where it was paid-only and migrations had to be chained onto `startCommand` instead. Starter's always-on compute also removed the need for a keepalive cron ping (issue #349 deleted the `/internal/tick` endpoint), so nothing pings the backend on a timer any more. Set `DATABASE_URL` (asyncpg form: `postgresql+asyncpg://user:pass@host/db?ssl=require`), `ADMIN_PASSWORD` and `ADMIN_TOTP_SECRET` (the admin console's second factor — enroll the secret locally with `backend/scripts/admin_totp_enroll.py`; `ADMIN_USERNAME` defaults to `admin`), the LLM keys (`GROQ_API_KEY`, optionally `CLOUDFLARE_WORKERS_AI_API_KEY` + `CLOUDFLARE_WORKERS_AI_BASE_URL` / `MISTRAL_API_KEY`), `RESEND_API_KEY`, `RESEND_FROM_ADDRESS`, `CONTACT_TO_ADDRESS`, `RESEND_WEBHOOK_SECRET`, `CORS_ORIGINS`, `FRONTEND_URL`, the Cloudinary trio `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` (organizer image upload; the endpoint returns 501 when unset), and — for Google sign-in — `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` (not `GOOGLE_CLIENT_*`) plus `GOOGLE_SIGNIN_CONSUMER_ENABLED` / `GOOGLE_SIGNIN_ORGANIZER_ENABLED` (both default `false`). `BACKEND_URL` — the API's own absolute URL, needed by the digest's server-side-fetched `List-Unsubscribe` header and by the host allowlist — is **not** a dashboard secret: it's a `value:` literal in `render.yaml` (`https://event-radar-api-r7l6.onrender.com`), so a blueprint sync sets it without a manual step. `SECRET_KEY` is auto-generated; `APP_ENV=production` and `LOG_LEVEL=INFO` are also `value:` literals. Set `EDGE_SHARED_SECRET` to the same value as the Cloudflare Pages Secret of that name — the API proxy sends it as `X-Edge-Auth` so the backend can trust the real client IP for rate limiting and admin lockout (unset, it falls back to a rightmost-`X-Forwarded-For` heuristic that buckets every visitor behind the proxy together). Optionally set `LOG_SHIP_URL` (+ `LOG_SHIP_TOKEN`) to ship JSON logs to an external drain such as Axiom, and `ADMIN_SESSION_EPOCH` — bumping it (or rotating `ADMIN_PASSWORD` / `ADMIN_TOTP_SECRET`) invalidates every outstanding admin session.
- **Frontend — Cloudflare Pages** (`frontend/wrangler.toml`, checked in as the build-config source of truth the same way `render.yaml` is for the backend): static Vite build, `pages_build_output_dir = "dist"`, `compatibility_flags = ["nodejs_compat"]` (the Functions import `node:crypto`). The build command and root directory live in the Pages dashboard — a Pages project rejects a `[build]` table in `wrangler.toml` outright. Non-secret build-time vars (`NODE_VERSION`, `PRERENDER_RENDER_BUDGET_MINUTES`, `VITE_GOOGLE_SIGNIN_CONSUMER_ENABLED` / `VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED`, the R2 account/bucket ids) live in `[vars]`; anything credential-shaped (including `EDGE_SHARED_SECRET`) is a Pages **Secret** (dashboard or `wrangler pages secret put`), never checked in. The API client issues all requests against a relative `/api` prefix (`frontend/src/api/client.ts`), and two Pages Functions do the same-origin proxying:
  - `frontend/functions/api/[[path]].ts` — forwards every `/api/*` request to the Render backend **with the `/api` prefix stripped** (backend routes carry no `/api` prefix — this mirrors the dev Vite proxy), avoiding CORS entirely and keeping the session cookie first-party. It also strips inbound client-IP headers and, when the `EDGE_SHARED_SECRET` Pages Secret is set, forwards Cloudflare's `CF-Connecting-IP` as `X-Client-IP` plus `X-Edge-Auth`.
  - `frontend/functions/[[path]].ts` — the SPA fallback. It tries `env.ASSETS.fetch()` first so a prerendered route or a real `dist/` file always wins; only a genuine 404 falls through to `app-shell.html` (a copy of the pre-prerender `dist/index.html`, kept distinct so a prerendered snapshot never overwrites the generic CSR shell).

  Cloudflare's file-based routing matches the exact-path Functions (`functions/api/seo-audit.ts`, `functions/api/prerender-cadence.ts`) ahead of the `/api/*` catch-all automatically, so there's no negative-lookahead exclusion list to keep in sync. Security headers and the SPA's tailored CSP live in `frontend/public/_headers` (copied into `dist/` by the build) rather than a `headers` block, and `frontend/public/_routes.json` keeps static assets off the Functions path.
- **SEO freshness — Cloudflare Pages Functions + R2 + cron-job.org**: two cron-job.org jobs, offset from each other, keep the prerendered snapshots and `sitemap.xml` fresh and independently verified. One POSTs `/api/prerender-cadence` every 6h (`frontend/functions/api/prerender-cadence.ts`), which gates a Pages Deploy Hook rebuild — skipping it when a multi-round prerender chain is already in flight; the other POSTs `/api/seo-audit` every 6h (`frontend/functions/api/seo-audit.ts`) to check production directly and self-file/close a GitHub issue if the cadence has gone silently stale. Both authenticate via their own distinct shared-secret headers (`PRERENDER_CADENCE_TOKEN_HEADER` / `SEO_AUDIT_TOKEN_HEADER`), and their credentials are Pages Secrets: `PRERENDER_CADENCE_TOKEN`, `PRERENDER_CADENCE_DEPLOY_HOOK_URL`, `SEO_AUDIT_TOKEN`, `GH_ISSUE_TOKEN`, `GH_PRERENDER_CHAIN_TOKEN`. A multi-round prerender burst keeps its per-target state in a Cloudflare **R2** bucket (`event-radar-prerender-chain-state`, credentials `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` as Secrets, plus a bucket lifecycle rule set in the dashboard as a crash backstop) — strictly an optimization: every R2 failure mode degrades to re-fetching production and never fails a build. Full detail in `docs/backend-ops.md` and `docs/frontend.md`.

## Documentation

- **[CLAUDE.md](CLAUDE.md)** — engineering conventions and codebase guidance (the map to everything below).
- **[CONTEXT.md](CONTEXT.md)** — domain glossary.
- **[docs/pipeline.md](docs/pipeline.md)** — ingestion → dedup → classification → ranking → Daily 5, field-level authority tables, read paths.
- **[docs/security.md](docs/security.md)** — auth flow, rate limits, CSP/CSRF, URL and HTML sanitization, residual risks.
- **[docs/backend-ops.md](docs/backend-ops.md)** — deployment topology, admin endpoints, logging, cleanup.
- **[docs/frontend.md](docs/frontend.md)** — SPA folder layout, hooks/utils homes, email presentation split.
- **[docs/design-system.md](docs/design-system.md)** — the C1 visual language: token groups, per-surface registers, theming machinery, motion vocabulary.
- **[docs/data-model.md](docs/data-model.md)** — tables, columns, migration guidance.
- **[docs/conventions.md](docs/conventions.md)** — the rationale behind each code-quality rule.
- **[docs/organizer-portal.md](docs/organizer-portal.md)** — the self-service organizer track end to end.
- **[docs/observability.md](docs/observability.md)** — shipped log-record shape, the `event` taxonomy, and the APL queries behind each Axiom monitor.
- **[docs/adr/](docs/adr/)** — architecture decision records.
- **[docs/agents/](docs/agents/)** — agent-facing workflow docs: issue tracker, triage labels, domain docs.
- **[shared/README.md](shared/README.md)** — the cross-stack shared/generated files and their workflow.
