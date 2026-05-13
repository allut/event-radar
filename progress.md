# Event Radar — Implementation Progress

Audit trail against [`plan.md`](./plan.md). `plan.md` is the original spec and stays unchanged.

---

## Status snapshot

| Field | Value |
|---|---|
| Phase | Week 3 |
| Plan day | Day 15 complete |
| Week progress | Days 1–15 complete |
| Current focus | Day 16: Email digest of Daily 5 (Resend HTML template) |
| Last updated | 2026-05-13 |

---

## Implemented

### Pre-Day 1 `2026-05-03`
- Repo bootstrapped: `plan.md` committed, root `.gitignore`, seeded `progress.md`.

### Day 1 — FastAPI scaffold `2026-05-03`
- `app/config.py` — pydantic-settings, `SECRET_KEY` required
- `app/db.py` — async SQLAlchemy 2 engine + session dep
- `app/main.py` — FastAPI with `/health` + `/internal/tick`
- `requirements.txt`, `.env.example`, `render.yaml` (web service + keepalive cron)

### Day 2 — DB migrations `2026-05-03`
- `alembic/` initialised with async `env.py`
- `0001_init.py` — all 13 v0 tables (citext, JSONB/ARRAY types, all indexes from `plan.md`)

### Day 3 — Fienta adapter `2026-05-03–04`
- `app/ingestion/base.py` — `SourceAdapter` ABC, `NormalizedEvent` dataclass, pipeline orchestrator (fetch → raw_events → normalize → events draft)
- `app/ingestion/sources/fienta.py` — per-organizer error isolation, free-event price=0 handling, savepoint-guarded slug collision recovery
- Pagination loop handles all three Fienta response shapes (plain list, `meta`-based, `links.next`-based); `_MAX_PAGES=50` budget; SSRF guard on `links.next`
- `app/seeds.py` — idempotent source seed (8 Fienta organizer IDs)
- `app/ingestion/organizer_sync.py` — weekly job: flags stale organizers, discovers new Tallinn orgs (≥3 events → auto-add); runs Sunday 03:00 EET
- **Tests:** `tests/ingestion/test_fienta.py` — 20 tests (normalize: 11, fetch/pagination: 9)

### Day 4 — JSON-LD adapter + venue sources `2026-05-04`
- `app/ingestion/sources/jsonld.py` — `JsonLdAdapter` base: BeautifulSoup `html.parser`, `@graph` traversal, schema.org → `NormalizedEvent` mapping
- Concrete adapters: `TelliskiviAdapter`, `KultuurikateldAdapter`, `FotografiskaAdapter`
- `app/seeds.py` — seeds the three JSON-LD sources with `kind=html_jsonld`
- URL settings: `TELLISKIVI_URL`, `KULTUURIKATEL_URL`, `FOTOGRAFISKA_URL` (env-overridable); `_upsert_simple` updates `config['url']` on existing rows
- **Tests:** `tests/ingestion/test_jsonld.py` — 30 tests (HTML extraction: 9, normalize: 17, fetch: 4)

### Code quality pass — pre-Day 5 `2026-05-05`
- `app/constants.py` — single source of truth for `TALLINN_TZ`, HTTP settings, slug constants, status strings, user defaults; all 8 import sites updated
- `app/llm/taxonomy.py` — `VALID_CATEGORIES` (12) + `VALID_VIBES` (10) frozensets; `validate_categories()` / `validate_vibes()` helpers
- `app/ingestion/base.py` — `_http_get()` shared helper: tenacity retry (3 attempts, 2–30s exponential backoff); all adapters migrated to it
- `0002_add_missing_indexes.py` — `ix_events_status`, `ix_raw_events_source_id`
- `.env.example` — added `CEREBRAS_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`, `RESEND_API_KEY`
- `requirements.txt` — added `tenacity>=9.0`; `requirements-dev.txt` — `ruff>=0.6`, `mypy>=1.11`

### Day 5 — APScheduler + `/admin/ingest` `2026-05-05`
- `app/ingestion/registry.py` — `ADAPTER_REGISTRY` mapping source slugs to adapter classes
- `app/ingestion/jobs.py` — `ingest_source(slug)` + `ingest_all_enabled(kind=None)` with per-source error isolation
- `app/routers/admin.py` — `GET /admin/ingest` (all sources) + `POST /admin/ingest/{slug}` (single source); HTTP Basic auth; 503 in non-dev if `ADMIN_PASSWORD` unset
- `app/main.py` — hourly `ingest_all_enabled` scheduler job; `/internal/tick` validates `X-Internal-Token` when `INTERNAL_TOKEN` is set
- **Tests:** 50/50 passing

### Day 6 — Rule-based dedup + admin eyeballing `2026-05-05`
- `app/dedup/rules.py` — `is_candidate_pair()` (token_set_ratio > 70, |Δstart| ≤ 12h, venue-compatible); union-find `cluster_events()` (group root = min event ID); `run_dedup_pass(db)`
- `app/routers/admin.py` — `POST /admin/dedup` (trigger pass); `GET /admin/dedup/groups` (eyeballing JSON)
- `app/main.py` — 6-hourly dedup scheduler job
- `requirements.txt` — added `rapidfuzz>=3.0`
- **Tests:** `tests/dedup/test_rules.py` — 25 tests (venue-compat: 6, candidate pair: 9, cluster: 10); 75/75 passing

### Day 7 — Magic-link auth + onboarding `2026-05-06`
- `app/auth/tokens.py` — `generate_magic_token` / `verify_magic_token` (itsdangerous, SHA-256 hash, `magic-link-v1` salt) + `generate_session_token` / `verify_session_token` (7-day TTL, `session-v1` salt); TTLs computed per-call so test monkeypatching works
- `app/auth/email.py` — `send_magic_link()` via Resend API; falls back to WARNING log when `RESEND_API_KEY` unset (signed token never logged)
- `app/routers/auth.py` — `POST /auth/request-link` (upsert user, 2-min cooldown, always 200 to prevent enumeration), `GET /auth/verify?token=X` (atomic `UPDATE ... RETURNING` to close TOCTOU race), `GET /auth/me`
- `app/routers/onboarding.py` — `POST /onboarding/persona` (atomic delete + re-insert `UserPersona`; primary weight=1.0, secondary weight=0.4; validates slugs)
- `app/seeds.py` — `seed_personas()` upserts 5 personas with trilingual display names and affinity vectors
- `requirements.txt` — added `email-validator>=2.0.0`
- **Tests:** `tests/auth/test_auth.py` — 20 tests (token util: 10, routers: 7); 96/96 passing

### Days 8–10 — LLM layer `2026-05-07–08`
- `app/llm/router.py` — `llm_json(task, prompt, db)`: Groq (`llama-3.3-70b-versatile`) → Cerebras (`qwen-3-235b-a22b-instruct-2507`) → Mistral fallback chain; skips providers with missing API keys; SHA-256 `content_hash` cache against `llm_calls` table (identical prompts never re-sent); records every attempt (success and failure) for audit; raises `LLMError` if all providers fail
- `app/llm/classifier.py` — `classify_pending(db)`: fetches canonical draft events in batches (`LLM_CLASSIFY_BATCH_SIZE`); builds classify prompt (title + venue + description, hard-truncated to `LLM_MAX_PROMPT_CHARS`); parses and validates response against fixed taxonomy; writes `EventClassification` + advances `event.status` to `classified`
- `app/dedup/llm_tiebreaker.py` — `run_dedup_pass_llm(db)`: wraps rule-based `run_dedup_pass` with LLM tiebreaker; LLM called only on candidate pairs; merge confirmed when `{"same": true, "confidence": ≥ 0.7}`; `LLMError` and parse errors treated as "distinct" (fail-safe); cap of `LLM_DEDUP_MAX_CANDIDATE_PAIRS_PER_PASS` to bound token spend per run
- `alembic/versions/0003_llm_calls.py` — `llm_calls` table: `task`, `event_id`, `content_hash`, `provider`, `model`, `prompt_tokens`, `completion_tokens`, `response_json` (JSONB); indexes on `content_hash` and `(task, created_at)`
- `app/main.py` — `classify_pending` job wired to APScheduler every 6h (alongside dedup); `build_daily_feeds` still stub-commented
- `app/constants.py` — all LLM prompt templates, token budgets, batch sizes, confidence thresholds, and provider config centralized; `LLM_PROVIDERS` ordered list drives router fallback
- **Tests:** `tests/llm/test_router.py` — 14 unit tests (cache hit, provider fallback, 429 fall-through, `LLMError` on all-fail, all-providers-unavailable); `tests/llm/test_live.py` — 3 live integration tests (one per provider, `pytest -m live`, skip when API key absent); 112 total tests passing

### Day 11 (frontend) — Vite/React SPA scaffold `2026-05-10`
- `frontend/` — Vite 5 + React 18 + TypeScript + TanStack Query v5 + React Router v6; no CSS framework (CSS Modules throughout)
- `frontend/index.html` — Google Fonts preconnect: Cormorant Garamond (display/headings) + DM Sans (body); Baltic editorial dark theme
- `frontend/vite.config.ts` — dev proxy: `/api/*` → `http://localhost:8000` (strips `/api` prefix); avoids CORS in dev
- `frontend/src/lib/auth.ts` — `getToken/setToken/clearToken/isAuthenticated` + locale helpers; localStorage
- `frontend/src/api/client.ts` — fetch wrapper: Bearer auth header, Content-Type only when body present, 401 → clearToken + redirect, throws `ApiError` on 4xx/5xx
- `frontend/src/App.tsx` — `Protected` wrapper component; routes: `/login`, `/auth/verify`, `/onboarding` (protected), `/` (protected)
- `frontend/src/routes/Login.tsx` + CSS — magic link form; idle/loading/success/error states; "Check your inbox" success card
- `frontend/src/routes/AuthVerify.tsx` + CSS — reads `?token=` from URL; calls GET /auth/verify; stores session token; always redirects to `/onboarding` on success (MVP: no persona-check)
- `frontend/src/routes/Onboarding.tsx` + CSS — 5 persona cards in 3-col grid; primary + optional secondary selection; locale pill toggle (en/et/ru); saves locale to localStorage; POSTs to /onboarding/persona
- `frontend/src/routes/Feed.tsx` + CSS — GET /feed with TanStack Query; date header formatted per locale; ordered list of EventCards; empty state; logout button; invalidates feed query on feedback
- `frontend/src/components/EventCard.tsx` + CSS — event card: gradient placeholder (category-keyed) when no image; Cormorant title; formatted time/venue; ◆ why_go bullets; like/dislike/bookmark (POST /feedback); active signal prevents duplicate POSTs; click_external on Tickets link
- `frontend/src/components/PersonaCard.tsx` + CSS — primary (amber border+badge), secondary (muted amber), none states; separate primary/secondary click handlers
- `backend/app/main.py` + `config.py` — `CORSMiddleware` added; `CORS_ORIGINS` list[str] setting (default: localhost:5173 + :4173); production note: set in Render env vars

### Days 11–13 — Ranking + feed/feedback endpoints `2026-05-09–10`
- `app/ranking/score.py` — pure scoring formula: `persona_affinity` (normalized dot-product), `recency_boost` (linear decay 21 days), `feedback_signal` (per-day 0.9^t decay, indirect category matching, hard-exclude via `_HARD_EXCLUDE` sentinel), `locality_bonus` (central Tallinn bounding box); `score_event` combines all five components; `_mmr_pick` MMR-lite diversity (max 2 per category); `build_daily_feeds` async job (upserts `daily_feeds` for all users)
- `app/routers/feed.py` — `GET /feed` (today's Daily 5 for authenticated user, preserves feed ordering from `daily_feeds.event_ids`)
- `app/routers/events.py` — `GET /events/{id}` (published-only; unauthenticated access; no internal metadata exposed)
- `app/routers/feedback.py` — `POST /feedback` (like/dislike/bookmark/view/click_external; invalidates `user_event_scores` cache row)
- `app/main.py` — wires three new routers + `build_daily_feeds` APScheduler job at 06:00 EET
- `app/config.py` — persona affinity vectors rewritten to use only `VALID_CATEGORIES` / `VALID_VIBES` taxonomy keys
- `app/seeds.py` — `_validate_affinity_vector()` validates persona affinity keys against taxonomy at startup
- **Tests:** `tests/ranking/test_score.py` (38 tests) + `tests/routers/test_feed.py` (8 tests) + `tests/routers/test_feedback.py` (6 tests) — 155 total passing

### Day 12 — Event detail page (frontend) `2026-05-10`
- `frontend/src/routes/EventDetail.tsx` + CSS — full event detail page: hero image (or gradient), meta, title, venue block with map link, why-go bullets, full description, category/vibe tags, feedback buttons (like/dislike/bookmark), tickets CTA button; fires `click_external` signal on tickets click
- `frontend/src/App.tsx` — added `/events/:id` protected route
- `frontend/src/components/EventCard.tsx` — title now links to internal `/events/:id` (React Router `Link`); added `description`, `lat`, `lng` to `EventData` interface; "Tickets →" remains as external link

### Day 13 (addendum) — Time-slot affinity `2026-05-10`
- `app/constants.py` — `VALID_TIMES` frozenset (`late_night`, `evening`, `daytime`, `morning`, `weekend`, `weekday`) + boundary hour constants
- `app/ranking/score.py` — `_time_slots_for_event(starts_at)` derives 1–2 time slots from `event.starts_at` in Europe/Tallinn (hour bucket + weekday/weekend); `_affinity_for_vector` / `persona_affinity` extended with `time_slots` parameter; `score_event` derives and passes time slots; max_possible normalization includes `times` weights so adding them doesn't distort category/vibe discrimination
- `app/config.py` — restored `times` sub-dict to 4 of 5 persona vectors (culture_buff omitted — attends any time); keys from `VALID_TIMES`
- `app/seeds.py` — `_validate_affinity_vector()` now also checks `times` keys against `VALID_TIMES`
- **Tests:** 12 new tests (`TestTimeSlotsForEvent`, time-aware `_affinity_for_vector` cases) — 151 total passing (excl. test_feed.py which has a stale `from backend.app…` import)

### Day 14 — Newsletter inbound webhook + LLM extractor `2026-05-10`
- `backend/alembic/versions/0004_raw_inbound_emails.py` — migration adds `raw_inbound_emails` table (id, received_at, from_addr, to_addr, subject, raw_payload JSONB, processed_at); index on `received_at`
- `backend/app/models/models.py` — `RawInboundEmail` ORM model
- `backend/app/routers/webhooks.py` — `POST /webhooks/inbound-mail`: stores raw email payload, fires background LLM extraction; optional `?secret=` query-param guard (timing-safe `hmac.compare_digest`); controlled by `RESEND_WEBHOOK_SECRET` env var
- `backend/app/llm/newsletter_extractor.py` — `extract_events_from_email()`: calls LLM router with newsletter prompt, parses `{"events": [...]}` response, creates `RawEvent` rows linked to `newsletter_inbound` source; race-safe source upsert via `INSERT ... ON CONFLICT DO NOTHING`
- `backend/app/constants.py` — `LLM_TASK_NEWSLETTER`, `NEWSLETTER_SOURCE_SLUG`, `NEWSLETTER_SUBJECT_MAX_LEN` (200), `NEWSLETTER_BODY_MAX_LEN` (1500), `NEWSLETTER_EXTRACT_PROMPT_TEMPLATE`
- `backend/app/config.py` — `RESEND_WEBHOOK_SECRET` setting (empty = dev mode, no verification)
- `backend/app/seeds.py` — seeds `newsletter_inbound` source row on startup
- `backend/app/main.py` — wires `webhooks_router`
- **Key fix (caught in review):** `llm_json` returns `tuple[dict, str]`, not a plain dict. Extractor correctly unpacks as `raw, _model = await llm_json(...)`. LLM `json_object` format always returns a dict, so prompt instructs `{"events": [...]}` shape.

### Day 15 — Settings page, locale toggle, unsubscribe `2026-05-13`
- `backend/alembic/versions/0005_add_email_digest_opt_in.py` — migration adds `email_digest_opt_in` boolean column to `users` (server_default=true)
- `backend/app/models/models.py` — `email_digest_opt_in: Mapped[bool]` field added to `User`
- `backend/app/constants.py` — `VALID_LOCALES: frozenset[str]` added as single source of truth for supported locales (`en`, `et`, `ru`)
- `backend/app/routers/settings.py` — `GET /users/me` (profile + personas) and `PATCH /users/me` (update locale and/or `email_digest_opt_in`); locale validator uses `VALID_LOCALES` from constants
- `backend/app/main.py` — wires `settings_router`
- `frontend/src/api/client.ts` — adds `api.patch<T>()` method
- `frontend/src/routes/Settings.tsx` + CSS — settings page: account email, language pill toggle (locale-only writes to localStorage on server confirmation, rolls back on error), persona display with "Change persona" link to `/onboarding`, email digest toggle; all mutations via `PATCH /users/me`
- `frontend/src/routes/Feed.tsx` — Settings link added to topbar
- `frontend/src/routes/Feed.module.css` — `.topActions`, `.settingsLink` classes for the topbar grouping
- `frontend/src/App.tsx` — `/settings` protected route added
- **Tests:** `tests/routers/test_settings.py` — 7 tests (get settings: 2, patch settings: 5) — 213 total passing
- **Key fix (reviewer-caught):** locale optimistic update was writing to localStorage before server confirmed; now writes only in `onSuccess` and rolls back UI state (`setLocaleState(getLocale())`) in `onError`

---

## Issues & fixes

| Symptom | Root cause | Fix |
|---|---|---|
| Persona affinity vector scoring was flat for multi-match events | `_affinity_for_vector` clipped raw sum to [-1,1] instead of normalizing — events with 1 or 5 matching categories all scored identically | Normalized by `max_possible = sum(vector.values())` so score discriminates across match quality |
| `GET /events/{id}` exposed draft/cancelled events + internal `dedup_group_id` | No status filter on public endpoint | Added `Event.status == published` filter; removed `dedup_group_id` from response |
| Persona affinity vector keys didn't match taxonomy | Old vectors used `arts`, `tech`, `business` etc. not in `VALID_CATEGORIES` | Rewrote all 5 vectors to use only taxonomy keys; added `_validate_affinity_vector()` startup check in `seeds.py` |
| `daily_feeds.event_ids` typed `ARRAY(Integer)` | Copy-paste; `events.id` is `BigInteger` | Changed to `ARRAY(BigInteger)` in ORM + migration |
| `SECRET_KEY` had hardcoded default | Magic-link forgery risk if deployed without setting env var | Made required (no default); app fails at startup if unset |
| `price_raw.get('min') or fallback` drops free events (price=0) | Python `or` treats 0 as falsy | `_first_not_none()` helper using `next(v for v in vals if v is not None)` |
| `price_raw = raw.get("price") or {}` drops `"price": 0` integer | `0 or {}` evaluates to `{}` | Changed to `isinstance(price_raw, dict)` guard; integers fall through to top-level fields |
| SSRF guard compared `netloc` (includes port) instead of `hostname` | `urlparse(url).netloc` returns `"fienta.com:8443"` on non-standard ports | Changed to `urlparse(url).hostname`; log level escalated to ERROR |
| Single organizer 4xx/5xx aborted entire Fienta fetch | `raise_for_status()` propagated unhandled inside organizer loop | Per-organizer try/except on `HTTPStatusError` + `RequestError`; log warning + continue |

---

## Decisions & deviations

| Date | Decision | Why | Plan section |
|---|---|---|---|
| 2026-05-03 | Single root `.gitignore` instead of per-subdir | Simpler for solo dev; rules don't conflict | None |
| 2026-05-03 | `SECRET_KEY` required, no default | Known default enables magic-link forgery on misconfigured deploys | Auth |
| 2026-05-03 | `/internal/tick` had no auth initially | MVP scope; endpoint returned only `{status: ok}` | Architecture |
| 2026-05-03 | `IngestionRun` record lost on caller rollback | Proper fix (separate transaction) deferred to Day 5 scheduler wiring | Architecture |
| 2026-05-03 | Fienta pagination initially unhandled | API field names unconfirmed without a live organizer ID | Data sources |

---

## Future considerations

Deferred items — each tied back to `plan.md` so context isn't lost.

- **pgvector cosine** — replace category-overlap heuristic in feedback scoring once Neon pgvector is enabled _(plan.md § Personalization, v1.1)_
- **Ticketmaster Discovery API** (`countryCode=EE`) — headline concerts, scheduled Day 17 _(plan.md § Phased delivery)_
- **Additional JSON-LD venues** — KUMU, Estonia theatre _(plan.md § Data sources, Stretch)_
- **Email digest of Daily 5** — Resend HTML template, Day 16; first on the cut list _(plan.md § Phased delivery)_
- **Secondary persona blending at 0.4 weight** — on the cut list; ship only if onboarding feels monodimensional in QA _(plan.md § Personalization)_
- **Bookmarks** — UI + endpoint exist in v0 model; explicitly cuttable _(plan.md § Honest cuts)_
- **Submit-an-event form** — manual escape hatch for source-coverage thinness _(plan.md § Top 3 risks, Risk #1)_
- **Render Starter upgrade** — only if free-tier sleep becomes an issue post-launch _(plan.md § Risk #3)_

---

## Quota / cost watch

Updated weekly. >50% sustained utilization = yellow flag (plan.md Risk #2).

| Week of | Cerebras tok/day (cap 1M) | Groq req/day (cap ~1k) | Mistral tok/mo (cap 1B) | Resend sends/mo (cap 3k) | Neon CU-h/mo (cap 100) |
|---|---|---|---|---|---|
| _(none yet)_ | — | — | — | — | — |
