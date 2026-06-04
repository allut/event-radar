# Event Radar — Implementation Progress

Audit trail against [`plan.md`](./plan.md).

---

## Status snapshot

| Field | Value |
|---|---|
| Phase | Week 3 |
| Plan day | Day 20 complete + pre-launch dedup refactor + CSS SSOT component refactor |
| Current focus | Day 21: E2E QA against 30 real Tallinn events, then soft launch |
| Tests | 279 passing (unit, excl. integration + live) |
| Last updated | 2026-05-19 |

---

## Completed days

### Week 1 — Skeleton + ingestion

- **Pre-Day 1 (2026-05-03)** — Repo bootstrap, `.gitignore`, `plan.md`, `progress.md`.
- **Day 1 (2026-05-03)** — FastAPI scaffold, pydantic-settings, async SQLAlchemy, `/health` + `/internal/tick`, `render.yaml`.
- **Day 2 (2026-05-03)** — Alembic init; `0001_init.py` with all 13 v0 tables (citext, JSONB/ARRAY, all indexes).
- **Day 3 (2026-05-03–04)** — Fienta adapter: per-organizer error isolation, free-event price=0 handling, savepoint slug-collision recovery, pagination (3 shapes), SSRF guard, `_MAX_PAGES=50`. Weekly Sun-03:00 organizer sync (auto-add ≥3 events). 20 tests.
- **Day 4 (2026-05-04)** — `JsonLdAdapter` base + Telliskivi / Kultuurikatel / Fotografiska adapters. 30 tests.
- **Code quality pass (2026-05-05)** — `app/constants.py` centralised; `taxonomy.py` 12-cat / 10-vibe frozensets + validators; `_http_get()` tenacity retry; index migration `0002`; `.env.example` keys.
- **Day 5 (2026-05-05)** — `ADAPTER_REGISTRY`, `ingest_source` / `ingest_all_enabled` with per-source isolation, `/admin/ingest` (HTTP Basic, 503 in prod if `ADMIN_PASSWORD` unset), hourly APScheduler job, `X-Internal-Token` on `/internal/tick`.
- **Day 6 (2026-05-05)** — Rule-based dedup (`token_set_ratio>70`, |Δstart|≤12h, venue-compatible), union-find clustering, `/admin/dedup`, 6-hourly job. 25 tests.
- **Day 7 (2026-05-06)** — Magic-link auth (`itsdangerous`, SHA-256 hash, 15-min TTL), 7-day session token, `/auth/request-link` (2-min cooldown, always 200), atomic `/auth/verify` (TOCTOU-safe `UPDATE ... RETURNING`), Resend email send + fallback log. Onboarding atomic persona pick. 20 tests.

### Week 2 — AI + frontend

- **Days 8–10 (2026-05-07–08)** — LLM router (`llm_json`): Groq → Cerebras → Mistral fallback, SHA-256 cache against `llm_calls`, audit every attempt. Classifier with fixed taxonomy + truncation cap. LLM dedup tiebreaker (rule pre-filter → LLM on candidates only, fail-safe to "distinct"). Migration `0003_llm_calls`. 14 router unit tests + 3 live (`pytest -m live`).
- **Day 11 (2026-05-10)** — Vite/React 18 SPA scaffold; TanStack Query; Cormorant Garamond + DM Sans; CSS Modules dark theme; auth lib + API client (Bearer, 401→clear+redirect); Login / AuthVerify / Onboarding / Feed pages; EventCard + PersonaCard; CORSMiddleware backend-side.
- **Days 11–13 (2026-05-09–10)** — Scoring formula (persona_affinity + recency + feedback + quality + locality), MMR-lite diversity, `build_daily_feeds` 06:00 EET job. `/feed`, `/events/{id}` (published-only, no internal metadata), `/feedback` (invalidates score cache). 52 tests.
- **Day 12 (2026-05-10)** — Event detail page (hero / meta / venue map link / why-go / description / tags / feedback / tickets CTA); EventCard title links to `/events/:id`.
- **Day 13 addendum (2026-05-10)** — Time-slot affinity: `VALID_TIMES` (late_night/evening/daytime/morning/weekend/weekday); `_time_slots_for_event` derives slots in Europe/Tallinn; `times` sub-dict added to 4/5 personas; normalization includes `times` weights. 12 tests.
- **Day 14 (2026-05-10)** — Inbound email: migration `0004_raw_inbound_emails`, `/webhooks/inbound-mail` (timing-safe `?secret=` guard, background extraction), `extract_events_from_email()` calls LLM router and creates `RawEvent` rows linked to `newsletter_inbound` source. **Fix:** `llm_json` returns `tuple[dict, str]`, not dict.

### Week 3 — Polish + ship

- **Day 15 (2026-05-13)** — Migration `0005_add_email_digest_opt_in`. `VALID_LOCALES` frozenset. `GET/PATCH /users/me`. Settings page (locale pill, persona display, digest toggle); optimistic locale rollback on server error. 7 tests.
- **Day 16 (2026-05-13)** — `email/digest.py`: `build_digest_html` (HTML-escaped, locale-aware day/month names), `send_digest_email` (raises on non-2xx so counters stay accurate), `send_daily_digests` (queries opted-in users, bulk-fetches events). APScheduler 07:00 EET. 24 tests.
- **Day 17 (2026-05-14)** — `KumuAdapter` + `EstoniaConcertHallAdapter` (JSON-LD). Eventbrite adapter added (later removed). 25 tests.
- **Day 17 addendum — Piletilevi scraper (2026-05-14)** — Replaces Eventbrite. 6 listing categories on piletilevi.ee, BS4 CSS selectors, Tallinn city filter, href deduplication, detail-page description fetch, `PILETILEVI_MAX_DETAIL_FETCHES=200`. Date parser for `"We 19.08.2026 • 19:00"`. 23 unit tests + 28 live tests in `test_piletilevi_live.py` (module-level result cache; `pytest.skip` on network failure).
- **Day 17 addendum — Eventbrite removed (2026-05-14)** — `/v3/events/search/` deprecated for non-partners (always 404). Adapter, tests, constants, config field, seeds fn, DB row all removed.
- **Day 18 (2026-05-17)** — Full EN/ET/RU UI i18n. New `frontend/src/i18n.ts` with `t()`, `ti()`, `personaName()`, `personaVibe()` (en falls back to `PERSONAS` from `constants.ts`). All 7 route/component files updated. `tsconfig.json` target ES2021 for `String.replaceAll`. Settings digest button uses action-verb aria-labels (WCAG 4.1.2).
- **Day 19 (2026-05-18)** — `NotFound` 404 page + `ErrorBoundary` (try/catch around `getLocale()` so localStorage failures in private-browsing don't re-throw). Wildcard route renders `<Protected><NotFound/></Protected>`. 6 new i18n keys × 3 locales. Plausible deferred (no domain yet).
- **Day 20 (2026-05-18)** — Backend i18n. `MAGIC_LINK_EMAIL_HTML` → locale dict + subjects dict. `_detect_locale(Accept-Language)` for new users; existing users keep stored locale. `LLM_CLASSIFY_PROMPT_TEMPLATE` updated: `why_go` now `{en,et,ru}` dict (~180 tokens, within 600 cap). `why_go_localized` JSONB column (migration `0006`). Classifier backward-compat: handles dict and old list formats. `serialize_event(event, locale)` fallback chain `locale → en → why_go_bullets`. 11 new tests.
- **Pre-launch dedup sweep (2026-05-19)** — Mechanical SSOT consolidation, no behavior change. Backend: `serialize_user(user, **extras)`, `get_optional_user_locale(authorization, db)`, `select_events_with_classification()` in `routers/utils.py`; `normalize_currency(raw, has_price)` in `ingestion/base.py`; shared `mock_db`/`make_user`/`make_event` pytest fixtures in `tests/conftest.py`. Frontend: `PageState`, `LocaleSelector`, `FeedbackButtonRow` components; `cx()`, `formatHourMinute()`, `trackExternalClick()` helpers in `utils.ts`; `--anim-fast/base/slow` + `--shadow-card/hover/accent` tokens on `:root`. 4 route .module.css files trimmed of duplicate selectors. Verified: 279 unit tests pass, `tsc` + `vite build` clean. Adversarial review (claude + openai) → no blockers.
- **CSS SSOT pass (2026-05-19)** — All hardcoded CSS values replaced with `:root` design tokens across 10 module files. Added 19 new tokens: `--accent-soft/muted/minimal/hover-bg`, `--bg-placeholder`, `--radius-pill`, `--spinner-size/size-md/size-sm`, `--toggle-*` (5 vars), `--heading-xl/lg/md/sm/xs`, `--rise-distance`. Global `@keyframes rise` added to `index.css`; 5 local duplicates removed (EventCard, AuthVerify, Login, NotFound, EventDetail). Per-component `--rise-distance` overrides preserve original motion distances. Toggle dimensions and border-radius tokenized via `calc()`. Spinner sizes unified (AuthVerify 36px → `--spinner-size-md`). `tsc` + `vite build` clean. Adversarial review: 4 regressions caught and fixed pre-commit.
- **CSS SSOT component refactor (2026-05-19)** — Four deferred SSOT patterns applied. (1) Heading scale: `--heading-2xl: 2rem` added to `:root`; raw `rem` values in `Onboarding.heading`, `Feed.heading`, `Feed.emptyTitle` replaced with tokens. (2) Shared `Card.module.css`: base `.card`, `.cardAccentTop`, `.cardDangerTop`, `.cardElevated`, `.cardPage` classes; Login/AuthVerify/ErrorBoundary/EventCard/NotFound compose from it via CSS Modules `composes`. (3) Shared `Button.module.css`: `.btnPrimary` + `.btnOutline` base classes; Login/Onboarding/EventDetail(ticketsBtn+backBtn)/ErrorBoundary/Feed compose from it. (4) `EmptyState` component extracted from Feed — new `EmptyState.tsx` + `EmptyState.module.css`; empty-state selectors removed from `Feed.module.css`. `tsc` + `vite build` clean. Adversarial review (claude + openai) → no blockers.

---

## Decisions & deviations

| Date | Decision | Why |
|---|---|---|
| 2026-05-03 | Single root `.gitignore` | Solo dev simplicity; no conflicting rules |
| 2026-05-03 | `SECRET_KEY` required, no default | Known default enables magic-link forgery on misconfigured deploys |
| 2026-05-14 | Piletilevi scraper replaces Eventbrite adapter | Eventbrite `/v3/events/search/` deprecated for non-partners (404) |
| 2026-05-14 | Ticketmaster never wired | Discovery API has zero EE inventory |

---

## Quota / cost watch

Updated weekly. >50% sustained = yellow flag (plan.md Risk #2).

| Week of | Cerebras tok/day (cap 1M) | Groq req/day (cap ~1k) | Mistral tok/mo (cap 1B) | Resend sends/mo (cap 3k) | Neon CU-h/mo (cap 100) |
|---|---|---|---|---|---|
| _(none yet — pre-launch)_ | — | — | — | — | — |
