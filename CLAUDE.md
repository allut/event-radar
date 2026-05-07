# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Event Radar** is an AI-powered event discovery platform for Tallinn, Estonia. It ingests events from multiple sources, deduplicates and classifies them via LLM, then delivers a personalized "Daily 5" curated feed per user. Project is in active development (MVP target: 3 weeks, solo).

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

Frontend does not exist yet (planned: Vite + React SPA).

## Architecture

```
FastAPI Backend (single process on Render free tier)
  ├── Routers: /auth  /admin  /onboarding  (feed/events/feedback — not yet wired)
  └── APScheduler (embedded, kept alive by Render Cron Job ping every 15 min)
      ├── Weekly Sun 03:00: sync_fienta_organizers (auto-discover new organizers)
      ├── Hourly:   ingest_all_enabled
      ├── 6-hourly: dedup_pass
      └── classify_pending + build_daily_feeds — not yet scheduled (Day 9–13)
        ↓
Neon Postgres (eu-central-1, free tier, pgvector available for v1.1)
        ↓
LLM Router: Cerebras (primary) → Groq → Mistral (fallback chain)
```

**No Celery/Redis** — embedded APScheduler suffices for a single-process MVP.

## Data Flow

1. **Ingestion** — 5 sources: Fienta API (~15 Tallinn organizer IDs), Telliskivi/Kultuurikatel/Fotografiska JSON-LD, Resend Inbound email webhook.
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
- `event_classifications` — categories[], vibes[], quality_score, why_go_bullets[3], language_detected, model_used
- `user_event_feedback` — like/dislike/bookmark/view/click_external signals
- `user_event_scores` — cached ranking score per (user, event); unique constraint
- `daily_feeds` — user_id, feed_date, event_ids BigInteger[]

## LLM Usage Constraints

- **Hard cap:** ≤600 tokens per LLM call to avoid quota exhaustion.
- **Dedup cache:** Cache decisions by content hash — never re-call LLM for identical pairs.
- **Fallback order:** Cerebras (1M tok/day, Llama 3.3 70B) → Groq → Mistral (overnight batch, 1B tok/mo).
- Cerebras handles Estonian well; test Estonian text paths explicitly.

## Auth

Magic-link email via `itsdangerous` tokens (~50 LOC, no third-party auth). Resend handles email delivery (3k/mo free tier). No sessions stored server-side — token is the credential.

Session tokens are issued after magic-link verification and passed as `X-Session-Token` header. TTL is 7 days (`SESSION_TTL_DAYS`).

## Admin Endpoints

`/admin/*` uses HTTP Basic auth (`ADMIN_PASSWORD` env var). In development with no password set, any credentials are accepted (logs a warning). In production, the env var is required — unset = 503.

## Code Quality & Best Practices

This project follows production best practices throughout:

- **Constants** — all shared literals live in `app/constants.py` (timezone, HTTP settings, slug params, status strings, user defaults). Never duplicate constants across files.
- **Retry logic** — all HTTP calls use `_http_get()` from `app/ingestion/base.py`, which wraps `httpx` with tenacity exponential-backoff retry (3 attempts, 2–30s backoff). Retryable: 429/502/503/504 and `RequestError`. Non-retryable: 4xx except 429.
- **Error visibility** — HTTP failures in source adapters propagate to `SourceAdapter.run()` so `IngestionRun.error` and `source.last_status` are always set correctly. Never swallow exceptions in `fetch_raw()`.
- **Taxonomy** — LLM classification uses the fixed 12-category / 10-vibe frozensets in `app/llm/taxonomy.py`. Use `validate_categories()` / `validate_vibes()` before persisting any LLM output.
- **Migrations** — always chain migrations correctly (`down_revision = "PREV"`). Keep migrations small and reversible.

## Conventions

- All datetimes are timezone-aware using `zoneinfo` (`Europe/Tallinn`). No UTC-naive datetimes anywhere.
- Email columns use `citext` (case-insensitive) to prevent duplicate accounts.
- Persona affinity vectors and source config stored as JSONB for easy extension without migrations.
- Feedback decay formula: `0.9^days_since_feedback` — recent signals weighted higher, dislike is a hard exclude.

## MVP Scope (do not cut)

Deduplication, LLM classification, persona-based personalization (primary + secondary blend already implemented), magic-link auth, Daily 5 builder. Everything else (extra venues, email digest, bookmarks) is cuttable if behind schedule.
