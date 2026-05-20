# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Event Radar** is an AI-powered event discovery platform for Tallinn, Estonia. It ingests events from multiple sources, deduplicates and classifies them via LLM, then delivers a personalized "Daily 5" curated feed per user. Days 1–20 complete. Day 21 = soft launch (pending E2E QA). See `pending_items.md` for QA checklist.

The authoritative spec is `plan.md`.

## Commands

```bash
# Backend (Python 3.12, FastAPI)
cd backend
pip install -r requirements.txt
alembic upgrade head          # apply migrations
uvicorn app.main:app --reload # dev server (port 8000)
pytest                        # run all tests
pytest tests/path/test_foo.py::TestClass::test_name  # single test
```

```bash
# Frontend (Vite + React SPA)
cd frontend
npm install
npm run dev        # dev server (port 5173)
npm run build      # type-check + production build
npm run type-check # TypeScript check only
```

## Architecture

```
FastAPI Backend (single process on Render free tier)
  ├── Routers: /auth  /admin  /onboarding  /events  /feed  /feedback  /users/me  /settings  /webhooks
  └── APScheduler (embedded, kept alive by Render Cron Job ping every 15 min)
      ├── Weekly Sun 03:00: sync_fienta_organizers (auto-discover new organizers)
      ├── Hourly:   ingest_all_enabled
      ├── 6-hourly: dedup_pass + classify_pending
      └── Daily 06:00: build_daily_feeds
        ↓
Neon Postgres (eu-central-1, free tier, pgvector available for v1.1)
        ↓
LLM Router: Groq (primary) → Cerebras → Mistral (fallback chain)
```

**No Celery/Redis** — embedded APScheduler suffices for a single-process MVP.

## Data Flow

1. **Ingestion** — 5 sources: Fienta API (~15 Tallinn organizer IDs), Piletilevi HTML scraper, Telliskivi/Kultuurikatel/Fotografiska/KUMU/Estonia Concert Hall JSON-LD, Resend Inbound email webhook. Eventbrite removed (API deprecated for non-partners).
2. **Deduplication** — Two-stage: rule-based pre-filter (fuzzy title + time proximity), then LLM tiebreaker only on candidate pairs (keeps token usage low).
3. **Classification** — LLM assigns fixed 12-category / 10-vibe taxonomy, quality score 0–1, 3-bullet "why go?" text. Fixed taxonomy prevents ontology drift.
4. **Ranking** — `score = 0.45·persona_affinity + 0.20·recency_boost + 0.20·feedback_signal + 0.10·quality_score + 0.05·locality_bonus`
5. **Daily 5 builder** — runs 06:00 Europe/Tallinn; scores events in next 14 days; MMR-lite diversity (max 2 per category); writes to `daily_feeds`.

## Key Database Tables

- `users` — email (citext unique), locale (et|en|ru), home_city
- `auth_magic_links` — token_hash (sha256), expires_at, used_at; one-use only
- `personas` — 5 static personas with JSONB affinity vectors; display names in et/en/ru
- `user_personas` — M2M join with weight (1.0 primary, 0.4 secondary)
- `sources` — ingestion source registry
- `raw_events` — source payload as JSONB
- `event_sources` — M2M: links events to source + external_id
- `events` — normalized: slug, title_orig, description_orig, starts_at/ends_at, venue, lat/lng, price, status (draft→classified→published|cancelled), dedup_group_id
- `event_classifications` — categories[], vibes[], quality_score, why_go_bullets[3], why_go_localized JSONB ({locale: [bullets]}), language_detected, model_used
- `user_event_feedback` — like/dislike/bookmark/view/click_external signals
- `user_event_scores` — cached ranking score per (user, event); unique constraint
- `daily_feeds` — user_id, feed_date, event_ids BigInteger[]

## LLM Usage Constraints

- **Hard cap:** ≤600 tokens per LLM call to avoid quota exhaustion.
- **Dedup cache:** Cache decisions by content hash — never re-call LLM for identical pairs.
- **Fallback order:** Groq (primary, `llama-3.3-70b-versatile`, Production) → Cerebras (`qwen-3-235b-a22b-instruct-2507`, Preview — 1 req/min, monitor for deprecation) → Mistral (overnight batch, 1B tok/mo).
- Groq's 30 req/min burst means no sleep loop needed in the classification batch job.

## i18n

- **Frontend** — custom `frontend/src/i18n.ts` (no library). `t(key, locale)` function; locale stored in `localStorage` and read from `GET /users/me`. Translations are plain TS objects.
- **Backend** — custom `backend/app/i18n.py` mirroring the frontend: single `TRANSLATIONS[locale][key]` dict + `DAY_NAMES`/`MONTH_NAMES` lookup tables; helpers `t(key, locale)`, `ti(key, locale, **vars)`, `day_name(weekday, locale)`, `month_name(month, locale)` with `locale → en → key` fallback. `Accept-Language` header parsed at signup → stored as `users.locale` (et|en|ru). `why_go_localized` JSONB column holds per-locale bullet translations; `resolve_why_go(cl, locale)` in `routers/utils.py` falls back: locale → en → raw.
- **Email digest** — `backend/app/email/digest.py`; HTML built inline, sent via Resend. All subjects, labels, and day/month names resolved via `app/i18n.py`.

## Frontend Structure

- Routes (pages) in `frontend/src/routes/`: Login, AuthVerify, Onboarding, Feed, EventDetail, Settings, NotFound.
- Shared components in `frontend/src/components/`: EventCard, PersonaCard, ErrorBoundary, PageState, LocaleSelector, FeedbackButtonRow, EmptyState.
- Shared CSS base classes in `frontend/src/components/shared/`: `Card.module.css` (`.card`, `.cardAccentTop`, `.cardDangerTop`, `.cardElevated`, `.cardPage`) and `Button.module.css` (`.btnPrimary`, `.btnOutline`). Compose from these via CSS Modules `composes` — never copy-paste the same card/button rules into route or component stylesheets.
- API calls in `frontend/src/routes/client.ts`. React Query used for server state (`@tanstack/react-query`).

## Auth

Magic-link email via `itsdangerous` tokens (~50 LOC, no third-party auth). Resend handles email delivery (3k/mo free tier). No sessions stored server-side — token is the credential.

Session tokens are issued after magic-link verification and passed as `X-Session-Token` header. TTL is 7 days (`SESSION_TTL_DAYS`).

## Admin Endpoints

`/admin/*` uses HTTP Basic auth (`ADMIN_PASSWORD` env var). In development with no password set, any credentials are accepted (logs a warning). In production, the env var is required — unset = 503.

## Code Quality & Best Practices

This project follows production best practices throughout:

- **Backend constants** — all literals (numbers, strings, thresholds, weights, sentinel values) live in `app/constants.py`. This is the single source of truth for every named constant in the project: ranking weights, scoring thresholds, decay parameters, bounding-box coordinates, signal names, etc. Never define a constant near business logic — always add it to `app/constants.py` first, then import it. Never duplicate constants across files.
- **Backend utilities** — all shared helper functions live in `backend/app/routers/utils.py`. Before writing a new utility function anywhere in the backend, check this file first. If the function is reusable, add it here and import it — never duplicate helpers across routers or modules.
- **Frontend constants** — all magic values (numbers, strings, breakpoints, timeouts, limits) live in `frontend/src/constants.ts`. Apply the same discipline as the backend: never inline a literal near component logic — add it to `constants.ts` first, then import it. Never duplicate constants across components.
- **Frontend utilities** — all shared helper functions live in `frontend/src/utils.ts`. Before writing a new utility function anywhere in the frontend, check this file first. If the function is reusable, add it here and import it — never duplicate helpers across components or pages.
- **CSS design tokens** — all design values (colors, spacing, typography, border-radius, shadows, z-indices, transitions) are defined as CSS custom properties on `:root` in `frontend/src/index.css`. Component stylesheets (`.module.css` files) consume only those variables — **never hardcode raw values**. This is the SSOT for theming; changing a token in `index.css` propagates everywhere automatically. When adding a new value, add the token to `:root` first, then reference it via `var(--token-name)`.
- **CSS shared base classes** — structural CSS patterns (card chrome, button styles) live in `frontend/src/components/shared/`. Use CSS Modules `composes: baseClass from '...'` to inherit shared rules — **never duplicate card or button CSS** across route or component stylesheets. Add new shared patterns to the shared files and compose from them.
- **Retry logic** — all HTTP calls use `_http_get()` from `app/ingestion/base.py`, which wraps `httpx` with tenacity exponential-backoff retry (3 attempts, 2–30s backoff). Retryable: 429/502/503/504 and `RequestError`. Non-retryable: 4xx except 429.
- **Error visibility** — HTTP failures in source adapters propagate to `SourceAdapter.run()` so `IngestionRun.error` and `source.last_status` are always set correctly. Never swallow exceptions in `fetch_raw()`.
- **Taxonomy** — LLM classification uses the fixed 12-category / 10-vibe frozensets in `app/llm/taxonomy.py`. Use `validate_categories()` / `validate_vibes()` before persisting any LLM output.
- **Migrations** — always chain migrations correctly (`down_revision = "PREV"`). Keep migrations small and reversible.
- **Quote style** — Backend Python uses **double quotes** (enforced by Ruff `Q` rules in `backend/ruff.toml`: `inline-quotes`, `multiline-quotes`, `docstring-quotes` all set to `double`). Frontend TypeScript uses **single quotes** for JS/TS string literals and **double quotes** for JSX attributes (enforced by ESLint `quotes: ['error', 'single', { avoidEscape: true, allowTemplateLiterals: true }]` + `'jsx-quotes': ['error', 'prefer-double']` in `frontend/eslint.config.js`). Template literals and strings containing the preferred quote character may use the alternate form (`avoidEscape`). Run `ruff check --fix` and `eslint --fix` before committing.

## Conventions

- All datetimes are timezone-aware using `zoneinfo` (`Europe/Tallinn`). No UTC-naive datetimes anywhere.
- Email columns use `citext` (case-insensitive) to prevent duplicate accounts.
- Persona affinity vectors and source config stored as JSONB for easy extension without migrations.
- Feedback decay formula: `0.9^days_since_feedback` — recent signals weighted higher, dislike is a hard exclude.

## MVP Scope (do not cut)

All MVP scope implemented: dedup, LLM classification, persona-based personalization, magic-link auth, Daily 5 builder, email digest, bookmarks, i18n (et/en/ru), Settings page.
