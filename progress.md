# Event Radar — Implementation Progress

Audit trail against [`plan.md`](./plan.md). `plan.md` is the original spec and stays unchanged.

---

## Status snapshot

| Field | Value |
|---|---|
| Phase | Week 1 → Week 2 |
| Plan day | Day 7 complete |
| Week progress | 100% (Days 1–7) — Week 1 checkpoint reached |
| Current focus | Day 8: LLM router (Cerebras→Groq→Mistral) |
| Last updated | 2026-05-06 |

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

---

## Issues & fixes

| Symptom | Root cause | Fix |
|---|---|---|
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
