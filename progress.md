# Event Radar — Implementation Progress

Audit trail against [`plan.md`](./plan.md). `plan.md` is the original spec and stays unchanged.

---

## Status snapshot

| Field | Value |
|---|---|
| Phase | Week 3 |
| Plan day | Day 17 complete |
| Week progress | Days 1–17 complete + Piletilevi adapter |
| Current focus | Day 18: Estonian + Russian UI strings (i18n pass, all three locales), Europe/Tallinn date formatting |
| Piletilevi live tests | 2026-05-14: 28 live integration tests in `tests/ingestion/test_piletilevi_live.py`; `pytest -m live` hits real piletilevi.ee; skip on network failure |
| Eventbrite removed | 2026-05-14: adapter, tests, constants, config field, seeds fn, and DB row all removed; `/v3/events/search/` deprecated for non-partner accounts — dead code |
| Piletilevi added | 2026-05-14: HTML scraper replacing Eventbrite; 6 listing categories, Tallinn city filter, detail-page description fetch, 200-event cap |
| Last updated | 2026-05-14 |

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

### Day 16 — Email digest of Daily 5 `2026-05-13`
- `backend/app/email/digest.py` — `build_digest_html()`: assembles HTML email per user (event title linked to frontend, date/time in Europe/Tallinn, venue, why-go bullets, free/paid price); all user-sourced strings run through `html.escape()`; day names + month names locale-aware for `et`/`ru`/`en`
- `backend/app/email/digest.py` — `send_digest_email()`: delivers via Resend API; raises `RuntimeError` on non-2xx so caller's sent/skipped counters stay accurate; no-op with WARNING log when `RESEND_API_KEY` unset
- `backend/app/email/digest.py` — `send_daily_digests(db)`: queries users with `email_digest_opt_in=True`, loads today's `daily_feeds` rows, bulk-fetches events, sends one digest per user; returns summary dict
- `backend/app/constants.py` — `DIGEST_EMAIL_SUBJECT_TEMPLATE`, `DIGEST_SEND_HOUR=7`, `DIGEST_MAX_WHY_GO_BULLETS=3`
- `backend/app/main.py` — `_run_send_daily_digests()` wired to APScheduler daily 07:00 EET (one hour after `build_daily_feeds`)
- **Tests:** `tests/email/test_digest.py` — 24 tests (date formatting: 6, time formatting: 3, HTML builder: 15) — 237 total passing

### Day 17 — KUMU + Estonia Concert Hall + Eventbrite adapter `2026-05-14`
- `backend/app/ingestion/sources/jsonld.py` — `KumuAdapter` (kumu.ekm.ee) + `EstoniaConcertHallAdapter` (concert.ee) added as `JsonLdAdapter` subclasses
- `backend/app/ingestion/sources/eventbrite.py` — `EventbriteAdapter`: Eventbrite API v3 (`location.address=Tallinn, Estonia`, `expand=venue,ticket_classes`); paginated via `pagination.has_more_items`; `_parse_eb_price` converts minor-unit costs; graceful no-op when `EVENTBRITE_API_KEY` unset
- `backend/app/ingestion/registry.py` — registered `kumu`, `estonia_concert_hall`, `eventbrite` slugs
- `backend/app/config.py` — `KUMU_URL`, `ESTONIA_CONCERT_HALL_URL`, `EVENTBRITE_API_KEY` settings
- `backend/app/seeds.py` — `_upsert_eventbrite()`: seeds source row; cleanup disables legacy `ticketmaster` source row (no delete — FK safety)
- `backend/app/constants.py` — `EVENTBRITE_BASE_URL`, `EVENTBRITE_LOCATION_ADDRESS`, `EVENTBRITE_LOCATION_RADIUS`, `EVENTBRITE_PAGE_SIZE`, `EVENTBRITE_MAX_PAGES`, `EVENTBRITE_SOURCE_SLUG`
- `backend/.env.example` — `KUMU_URL`, `ESTONIA_CONCERT_HALL_URL`, `EVENTBRITE_API_KEY` entries
- **Tests:** `tests/ingestion/test_eventbrite.py` — 25 tests (normalize: 11, helpers: 6, fetch: 5, pagination: 3) — 265 total passing
- **Why Eventbrite over Ticketmaster:** Ticketmaster Discovery API covers no EE inventory (`EE` absent from supported country list; adapter returned zero results); Eventbrite has verified Tallinn coverage, free tier, individual signup

### Day 17 (addendum) — Piletilevi live integration tests `2026-05-14`
- `backend/tests/ingestion/test_piletilevi_live.py` — 28 live tests (`pytest -m live`): `TestLiveFetchRaw` (9 tests — at-least-one-event, required fields, Tallinn filter, href uniqueness via Counter, href format, description fetch); `TestLiveNormalize` (6 tests — no-None normalization, tz-aware starts_at with `tzinfo.key` check, absolute URLs, title/external_id match, ≤5% past-event tolerance); `TestLiveCSSSelectorValidity` (6 tests — card/title/date/venue/image selectors hit real markup, detail description selector verified by fetching a live detail page); `TestLiveDataExtraction` (7 tests — image_url type, at-least-some-have-image, image_url absolute after normalize, date_str bullet separator, date_str HH:MM time, venue field type, href is relative path)
- Module-level result cache: fixture fetches once and reuses across all 28 tests; `pytest.skip()` on `ConnectError`/`TimeoutException`/`RequestError`
- **Tests:** 28 live tests + 23 existing unit tests (51 total for piletilevi); run live with `python3 -m pytest tests/ingestion/test_piletilevi_live.py -v -m live`

### Day 17 (addendum) — Piletilevi HTML scraper `2026-05-14`
- `backend/app/ingestion/sources/piletilevi.py` — `PiletileviAdapter`: scrapes 6 category listing pages on piletilevi.ee; BS4 CSS selector parsing (`a.card[href*="/en/tickets/"]`); Tallinn city filter (keeps events with "Tallinn" in `.card__description` or no city listed); deduplicates by href across listing URLs; fetches detail page per event for `.event__description` text; cap `PILETILEVI_MAX_DETAIL_FETCHES=200` prevents runaway on abnormal listings
- `backend/app/ingestion/sources/piletilevi.py` — `_parse_piletilevi_date()`: parses `"We 19.08.2026 • 19:00"` format (strips weekday abbreviation, strptime `%d.%m.%Y %H:%M`, localized to `TALLINN_TZ`)
- `backend/app/constants.py` — `PILETILEVI_BASE_URL`, `PILETILEVI_SOURCE_SLUG`, `PILETILEVI_TALLINN_FILTER`, `PILETILEVI_DATE_FORMAT`, `PILETILEVI_MAX_DETAIL_FETCHES`, `PILETILEVI_LISTING_URLS`
- `backend/app/ingestion/registry.py` — registered `piletilevi` slug
- `backend/app/seeds.py` — seeds `piletilevi` source row (`kind=html_scrape`)
- `backend/.env.example` — comment entry for `PILETILEVI_BASE_URL` override
- **Tests:** `tests/ingestion/test_piletilevi.py` — 23 tests (date parsing: 6, normalize: 12, fetch_raw: 5) — 260 total passing

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
| Onboarding persona selection auto-submitted on first click; no chance to pick secondary | `PersonaCard` buttons had no `type` attribute — inside `<form>` they defaulted to `type="submit"` | Added `type="button"` to all three buttons (`mainBtn`, `secondaryBtn`, `secondaryBadge`) in `PersonaCard.tsx` |

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
- **Ticketmaster Discovery API** — ✅ Added Day 17, then replaced with Eventbrite (Ticketmaster covers no EE inventory)
- **Additional JSON-LD venues (KUMU, Estonia Concert Hall)** — ✅ Done (Day 17)
- **Eventbrite search endpoint** — ❌ Removed: `/v3/events/search/` deprecated for non-partner accounts (always 404); full adapter removed 2026-05-14; replaced by Piletilevi scraper
- **Piletilevi.ee HTML scraper** — ✅ Done (Day 17+): scrapes 6 category listing pages; Tallinn city filter; detail-page description fetch; 200-event cap; 23 tests; `piletilevi` slug registered
- **Submit-an-event form** — manual escape hatch for source-coverage thinness _(plan.md § Top 3 risks, Risk #1)_ — now higher priority given Eventbrite removal
- **Email digest of Daily 5** — ✅ Done (Day 16)
- **Secondary persona blending at 0.4 weight** — on the cut list; ship only if onboarding feels monodimensional in QA _(plan.md § Personalization)_
- **Bookmarks** — UI + endpoint exist in v0 model; explicitly cuttable _(plan.md § Honest cuts)_
- **Render Starter upgrade** — only if free-tier sleep becomes an issue post-launch _(plan.md § Risk #3)_

---

## Quota / cost watch

Updated weekly. >50% sustained utilization = yellow flag (plan.md Risk #2).

| Week of | Cerebras tok/day (cap 1M) | Groq req/day (cap ~1k) | Mistral tok/mo (cap 1B) | Resend sends/mo (cap 3k) | Neon CU-h/mo (cap 100) |
|---|---|---|---|---|---|
| _(none yet)_ | — | — | — | — | — |
