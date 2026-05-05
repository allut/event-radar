# Event Radar — Implementation Progress

Living log of execution against [`plan.md`](./plan.md). `plan.md` is the original spec and stays unchanged; this file is the audit trail.

---

## Status snapshot

| Field | Value |
|---|---|
| Phase | Week 1 |
| Plan day | Day 5 complete |
| Week progress | 71% (Days 1–5 / 7) |
| Current focus | Day 6: Rule-based dedup + eyeball cross-source matches |
| Last updated | 2026-05-05 |

---

## Implemented

Grouped by plan-day. Format: `[YYYY-MM-DD] (Plan: Day N — <plan title>) — what shipped`.

- `[2026-05-03]` (Pre-Day-1) — Repo bootstrapped: `plan.md` committed; added root `.gitignore` covering FastAPI + Vite/React stack, and seeded this `progress.md`.
- `[2026-05-03]` (Plan: Day 1 — FastAPI scaffold) — `backend/` created: `app/config.py` (pydantic-settings, SECRET_KEY required), `app/db.py` (async SQLAlchemy 2 engine + session dep), `app/main.py` (FastAPI with `/health` + `/internal/tick`), `requirements.txt`, `.env.example`, `render.yaml` (web service + keepalive cron).
- `[2026-05-03]` (Plan: Day 2 — DB migrations) — `alembic/` initialised with async `env.py`; migration `0001_init.py` creates all 13 v0 tables (users through daily_feeds) with citext extension, JSONB/ARRAY types, and all indexes from `plan.md`.
- `[2026-05-03]` (Plan: Day 3 — Fienta adapter) — `app/ingestion/base.py`: `SourceAdapter` ABC + `NormalizedEvent` dataclass + pipeline orchestrator (fetch → raw_events → normalize → events(draft)); `app/ingestion/sources/fienta.py`: Fienta API adapter with per-organizer error isolation, free-event price=0 handling, savepoint-guarded slug collision recovery; `app/seeds.py`: idempotent source seed (8 placeholder Fienta organizer IDs for Sveta Baar, HALL, TMW, etc.); `app/main.py`: lifespan calls `seed_sources` on startup.
- `[2026-05-04]` (Plan: Day 3 follow-up — Organizer sync automation) — `app/ingestion/organizer_sync.py`: weekly sync job that checks each organizer for live events (flags stale, never auto-removes — seasonal venues preserved), discovers new Tallinn organizers via city=Tallinn scan (auto-adds if ≥3 events), persists via full `source.config` dict reassignment for SQLAlchemy JSONB detection; `app/main.py`: wired `AsyncIOScheduler` (APScheduler) into lifespan — runs `sync_fienta_organizers` every Sunday 03:00 Europe/Tallinn.
- `[2026-05-04]` (Plan: Day 3 extension — Fienta pagination + tests) — `app/ingestion/sources/fienta.py`: unified pagination loop in `_fetch_organizer` handles all three Fienta response shapes (plain list, meta-based `{data, meta: {current_page, last_page}}`, link-based `{data, links: {next}}`); shared `_MAX_PAGES=50` budget prevents infinite loops across all styles; SSRF guard rejects `links.next` URLs pointing to a different hostname; `price_raw isinstance(dict)` guard so `"price": 0` (integer) falls through to top-level fields instead of being treated as empty dict. `backend/tests/ingestion/test_fienta.py`: 20 tests covering normalize() (11 cases: free events, integer price field, naive datetime, string venue, all required-field miss cases) and fetch_raw() / pagination (9 cases: plain list, meta 2-page, link-based 2-page, SSRF host mismatch guard, per-organizer error isolation, multi-org aggregation, meta ceiling, link ceiling). `backend/pytest.ini`: asyncio_mode=auto. `backend/tests/conftest.py`: sets `SECRET_KEY` env var before import-time settings validation.
- `[2026-05-04]` (Plan: Day 4 — JSON-LD adapter base class + venue sources) — `app/ingestion/sources/jsonld.py`: `JsonLdAdapter` base class (BeautifulSoup `html.parser` extraction of `<script type="application/ld+json">` tags, full `_collect_events` recursion including `@graph` traversal); `normalize()` maps schema.org Event → `NormalizedEvent` with location/geo/offers/image handling for all common shapes (list, dict, nested); `get_raw_external_id` override stores event URL as `RawEvent.external_id` instead of empty string. Three concrete adapters (trivial subclasses using `source.config["url"]`): `TelliskiviAdapter`, `KultuurikateldAdapter`, `FotografiskaAdapter`. `app/seeds.py`: refactored into `_upsert_fienta` + `_upsert_simple`; seeds `telliskivi`, `kultuurikatel`, `fotografiska` source records with `kind=html_jsonld`. `app/ingestion/base.py`: added `get_raw_external_id(raw)` hook (default `raw.get("id")`). `requirements.txt`: added `beautifulsoup4>=4.12.0`. `tests/ingestion/test_jsonld.py`: 30 tests covering HTML extraction (9 cases), normalize() (17 cases), fetch_raw() (4 async cases).
- `[2026-05-04]` (Refactor — ingestion layer cleanup) — Eliminated three duplicated constants/helpers that had spread across the ingestion layer: `TALLINN_TZ = ZoneInfo("Europe/Tallinn")` (was in `fienta.py`, `jsonld.py`, `organizer_sync.py`) and `_parse_dt()` (was in both `fienta.py` and `jsonld.py`) now live exclusively in `app/ingestion/base.py`. All three source files import from base. `app/config.py`: added `TELLISKIVI_URL`, `KULTUURIKATEL_URL`, `FOTOGRAFISKA_URL` as env-overridable settings (same pattern as `FIENTA_BASE_URL`). `app/seeds.py`: `_JSONLD_SOURCES` static list replaced with `_jsonld_sources()` factory reading from settings; `_upsert_simple` extended to update `config['url']` on existing rows when the setting differs (previously insert-only, meaning env overrides were silently ignored).
- `[2026-05-05]` (Plan: Day 5 — APScheduler + `/admin/ingest`) — `app/ingestion/registry.py` **new**: `ADAPTER_REGISTRY` dict mapping source slugs to adapter classes (fienta, telliskivi, kultuurikatel, fotografiska). `app/ingestion/jobs.py` **new**: `ingest_source(slug)` runs a single source following the `SourceAdapter.run()` contract (commit-on-error to persist `IngestionRun` failure records); `ingest_all_enabled(kind=None)` loops all enabled sources with per-source error isolation. `app/routers/admin.py` **new**: `GET /admin/ingest` (trigger all sources) + `POST /admin/ingest/{slug}` (trigger single source), both guarded by HTTP Basic auth (`ADMIN_USERNAME`/`ADMIN_PASSWORD` settings); refuses with 503 in non-development environments when `ADMIN_PASSWORD` is unset; generic 500 responses never leak internal exception strings. `app/main.py`: hourly `ingest_all_enabled` scheduler job added; `GET /internal/tick` now validates `X-Internal-Token` header when `INTERNAL_TOKEN` env var is set, and logs a warning in non-development environments when it is unset. `app/config.py`: added `ADMIN_USERNAME` (default `"admin"`), `ADMIN_PASSWORD`, `INTERNAL_TOKEN` settings. `backend/.env.example`: documented all three new vars. 50/50 tests passing.
- `[2026-05-05]` (Code quality pass — pre-Day-5 review fixes) — `app/constants.py` **new**: single source of truth for `TALLINN_TZ`, `HTTP_TIMEOUT_SECONDS`, `HTTP_USER_AGENT`, slug constants, status strings, user defaults; all 8 import sites updated. `app/llm/__init__.py` + `app/llm/taxonomy.py` **new**: `VALID_CATEGORIES` (12) and `VALID_VIBES` (10) frozensets + `validate_categories()` / `validate_vibes()` helpers — blocks ontology drift before LLM layer is added. `app/ingestion/base.py`: added `_is_retryable()` and `_http_get()` (tenacity retry: 3 attempts, 2–30s exponential backoff, reraises on final failure) as the single shared HTTP helper for all source adapters. `fienta.py`, `jsonld.py`, `organizer_sync.py`: replaced local `timeout=30.0` and per-file retry duplication with `_http_get` from base. `jsonld.py`: HTTP errors now propagate (log at ERROR + re-raise) so `IngestionRun.error` is always set. `models.py`: imported constants for status/locale/city defaults. `backend/.env.example`: added `CEREBRAS_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`, `RESEND_API_KEY` placeholders. `requirements.txt`: added `tenacity>=9.0`. `requirements-dev.txt`: added `ruff>=0.6`, `mypy>=1.11`. `alembic/versions/0002_add_missing_indexes.py` **new**: `ix_events_status` and `ix_raw_events_source_id` indexes. 50/50 tests passing throughout.

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

- **Symptom:** `price_raw = raw.get("price") or {}` silently drops `"price": 0` (integer zero from API).
  - **Root cause:** `0 or {}` evaluates to `{}` in Python, so the integer price field is treated as "no price dict" and top-level fallbacks are used (which may also be absent).
  - **Fix:** Changed to `price_raw = raw.get("price")` followed by `isinstance(price_raw, dict)` guard. Integer/None values fall through to top-level `min_price`/`max_price` fields.
  - **Time lost:** Caught in adversarial review, zero production impact.

- **Symptom:** Pagination `links.next` SSRF guard compared `netloc` (includes port) instead of `hostname`.
  - **Root cause:** `urlparse(url).netloc` returns `"fienta.com:8443"` on non-standard ports; comparing to `"fienta.com"` causes false-positive guard trips and silently truncates pagination at page 1.
  - **Fix:** Changed to `urlparse(url).hostname` for both base and next-URL comparison. Also escalated log level from `warning` to `error`.
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
