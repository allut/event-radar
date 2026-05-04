# Event Radar — Implementation Progress

Living log of execution against [`plan.md`](./plan.md). `plan.md` is the original spec and stays unchanged; this file is the audit trail.

---

## Status snapshot

| Field | Value |
|---|---|
| Phase | Week 1 |
| Plan day | Day 3 complete + organizer sync automation |
| Week progress | 43% (Days 1–3 / 7) |
| Current focus | Day 4: JSON-LD adapter base class + Telliskivi/Kultuurikatel/Fotografiska |
| Last updated | 2026-05-04 |

---

## Implemented

Grouped by plan-day. Format: `[YYYY-MM-DD] (Plan: Day N — <plan title>) — what shipped`.

- `[2026-05-03]` (Pre-Day-1) — Repo bootstrapped: `plan.md` committed; added root `.gitignore` covering FastAPI + Vite/React stack, and seeded this `progress.md`.
- `[2026-05-03]` (Plan: Day 1 — FastAPI scaffold) — `backend/` created: `app/config.py` (pydantic-settings, SECRET_KEY required), `app/db.py` (async SQLAlchemy 2 engine + session dep), `app/main.py` (FastAPI with `/health` + `/internal/tick`), `requirements.txt`, `.env.example`, `render.yaml` (web service + keepalive cron).
- `[2026-05-03]` (Plan: Day 2 — DB migrations) — `alembic/` initialised with async `env.py`; migration `0001_init.py` creates all 13 v0 tables (users through daily_feeds) with citext extension, JSONB/ARRAY types, and all indexes from `plan.md`.
- `[2026-05-03]` (Plan: Day 3 — Fienta adapter) — `app/ingestion/base.py`: `SourceAdapter` ABC + `NormalizedEvent` dataclass + pipeline orchestrator (fetch → raw_events → normalize → events(draft)); `app/ingestion/sources/fienta.py`: Fienta API adapter with per-organizer error isolation, free-event price=0 handling, savepoint-guarded slug collision recovery; `app/seeds.py`: idempotent source seed (8 placeholder Fienta organizer IDs for Sveta Baar, HALL, TMW, etc.); `app/main.py`: lifespan calls `seed_sources` on startup.
- `[2026-05-04]` (Plan: Day 3 follow-up — Organizer sync automation) — `app/ingestion/organizer_sync.py`: weekly sync job that checks each organizer for live events (flags stale, never auto-removes — seasonal venues preserved), discovers new Tallinn organizers via city=Tallinn scan (auto-adds if ≥3 events), persists via full `source.config` dict reassignment for SQLAlchemy JSONB detection; `app/main.py`: wired `AsyncIOScheduler` (APScheduler) into lifespan — runs `sync_fienta_organizers` every Sunday 03:00 Europe/Tallinn.

---

## Issues & fixes

Format per entry:
- **Symptom:** what was observed
- **Root cause:** why it happened
- **Fix:** what was changed
- **Time lost:** rough wall-clock

- **Symptom:** `daily_feeds.event_ids` typed as `ARRAY(Integer)` while `events.id` is `BigInteger`.
  - **Root cause:** Copy-paste assumption that 32-bit integers suffice for IDs.
  - **Fix:** Changed to `ARRAY(BigInteger)` in both ORM model and migration `0001_init.py`.
  - **Time lost:** Caught in review, zero production impact.

- **Symptom:** `SECRET_KEY` had a hardcoded default `"change-me-in-production"`.
  - **Root cause:** Convenience default; magic-link forgery risk not considered.
  - **Fix:** Made `SECRET_KEY` a required pydantic-settings field (no default). App fails at startup if unset.
  - **Time lost:** Caught in review.

- **Symptom:** `price_raw.get('min') or fallback` silently drops free events (price=0).
  - **Root cause:** Python `or` treats 0 as falsy; would store `price_min=None` instead of 0 for free events.
  - **Fix:** `_first_not_none()` helper using `next(v for v in vals if v is not None)`.
  - **Time lost:** Caught in adversarial review, zero production impact.

- **Symptom:** Single organizer 4xx/5xx aborts entire Fienta fetch batch.
  - **Root cause:** `response.raise_for_status()` propagates unhandled inside the organizer loop.
  - **Fix:** Per-organizer try/except on `httpx.HTTPStatusError` and `httpx.RequestError`; log warning and continue.
  - **Time lost:** Caught in adversarial review.

---

## Decisions / deviations from plan

Anything that contradicts or extends `plan.md`. Format: *What changed → Why → Plan section affected.*

- **2026-05-03 — Single root `.gitignore` instead of per-subdir (`backend/.gitignore` + `frontend/.gitignore`).**
  - *Why:* simpler for a solo dev; the backend/ and frontend/ trees are small and the rules don't conflict.
  - *Plan section affected:* none directly; revisit if backend/frontend ever split into separate repos.

- **2026-05-03 — `SECRET_KEY` made required (no default) instead of having a dev-placeholder default.**
  - *Why:* a known default allows magic-link token forgery if someone deploys without setting the env var. Failing fast at startup is safer.
  - *Plan section affected:* `plan.md` § Auth — no conflict, actually enforces the "~50 LOC" magic-link design.

- **2026-05-03 — `/internal/tick` endpoint has no shared-secret auth (deferred).**
  - *Why:* MVP scope; the endpoint only returns `{status: ok}` today. Will add `X-Internal-Token` header check before the endpoint triggers any scheduler jobs (Day 5).
  - *Plan section affected:* `plan.md` § Architecture, keepalive design.

- **2026-05-03 — `IngestionRun` record lost if caller rolls back on error.**
  - *Why:* `SourceAdapter.run()` sets `run.error` on exception then re-raises; if the caller's session is rolled back, the error record disappears. Documented in `run()` docstring. Proper fix (separate transaction for the run record) comes in Day 5 when the scheduler and admin endpoint are wired.
  - *Plan section affected:* `plan.md` § Architecture, scheduler design.

- **2026-05-03 — Fienta API pagination unhandled.**
  - *Why:* Fienta API pagination field names unconfirmed without a live organizer ID. TODO comment added in `FientaAdapter.fetch_raw`. Will add pagination loop once API format is confirmed against a real organizer.
  - *Plan section affected:* `plan.md` § Data sources, Fienta adapter.

---

## Future considerations

Items deliberately deferred. Each is tied back to where `plan.md` already names it, so we don't lose context.

- **pgvector cosine for feedback signal** — replace category-overlap heuristic in `user_event_feedback` scoring once Neon's pgvector is enabled. (`plan.md` § Personalization, "v1.1 enhancement")
- **Ticketmaster Discovery API** (`countryCode=EE`) — headline concerts, scheduled for Week 3 Day 17. (`plan.md` § Phased delivery)
- **Additional JSON-LD venues** — KUMU, Estonia theatre. (`plan.md` § Data sources, Stretch)
- **Email digest of Daily 5** — Resend HTML template, Week 3 Day 16. First on the "Honest cuts if behind" list. (`plan.md` § Phased delivery)
- **Secondary persona blending at 0.4 weight** — also on the cut list; ship only if onboarding feels too monodimensional in QA. (`plan.md` § Personalization)
- **Bookmarks** — UI affordance + endpoint exist in v0 model, but explicitly cuttable. (`plan.md` § Honest cuts)
- **Submit-an-event escape hatch** — manual form, mitigation for source-coverage thinness (Risk #1). (`plan.md` § Top 3 risks)
- **$7/mo Render Starter upgrade path** — only if free-tier sleep starts mattering after launch traffic. (`plan.md` § Risk #3)

---

## Quota / cost watch

Update weekly during ingestion-heavy phases. "Free LLM quota exhaustion" is `plan.md` Risk #2 — treat sustained >50% utilization as a yellow flag.

| Week of | Cerebras tok/day (cap 1M) | Groq req/day (cap ~1k) | Mistral tok/mo (cap 1B) | Resend sends/mo (cap 3k) | Neon CU-h/mo (cap 100) | Notes |
|---|---|---|---|---|---|---|
| _(none yet)_ | — | — | — | — | — | — |

---

## How to update this file

- **Implemented:** append a bullet whenever a plan-day's work lands. Don't rewrite history; append.
- **Issues & fixes:** add an entry only if it cost real time or might recur. Trivial typo fixes don't belong here.
- **Decisions:** add an entry whenever you do something `plan.md` doesn't say to do, or skip something it does. Future-you needs the *why*.
- **Status snapshot:** edit in place each working session.
- **Quota watch:** add a row at end-of-week once ingestion is live.
