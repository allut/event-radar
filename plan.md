# Event Radar — Plan

AI-powered event discovery for **Tallinn**. Personalized "Daily 5" curated feed per user, free-tier infra only. Solo Python developer, target steady-state cost **$0/mo**.

Tallinn speaks **Estonian, English, Russian** — every user-facing string and LLM output supports `et`/`en`/`ru`.

**Status (2026-05-19):** Days 1–20 complete. Day 21 (soft launch) pending E2E QA.

---

## Confirmed decisions

- **Stack:** FastAPI 3.12 + SQLAlchemy 2 + Alembic; Vite/React SPA (TanStack Query, React Router, CSS Modules)
- **DB:** Neon Postgres free (eu-central-1, 0.5 GB, scale-to-zero, pgvector available for v1.1)
- **Auth:** magic-link email (`itsdangerous` signed token, 50 LOC); 7-day session token `X-Session-Token`
- **Email:** Resend free (3k/mo) — magic links + daily digest
- **LLM:** Groq primary (`llama-3.3-70b-versatile`, 14,400 req/day, 30 req/min burst) → Cerebras (`qwen-3-235b-a22b-instruct-2507`, 1 req/min Preview) → Mistral (1B tok/mo overnight batch)
- **Scheduler:** APScheduler embedded; Render Cron Job pings `/internal/tick` every 15 min to survive free-tier sleep
- **Hosting:** Render free Web Service (backend) + Vercel/Cloudflare Pages (frontend)
- **Differentiator:** persona-based onboarding + like/dislike learning
- **No Celery/Redis** — single-process MVP

---

## Architecture

```
Vite/React SPA  ──HTTPS/JSON──▶  FastAPI (single process)
                                    ├── Routers: /auth /admin /onboarding /events /feed
                                    │            /feedback /users/me /settings /webhooks
                                    └── APScheduler (in-process)
                                        ├── Sun 03:00:  sync_fienta_organizers
                                        ├── Hourly:     ingest_all_enabled
                                        ├── 6-hourly:   dedup_pass + classify_pending
                                        ├── 06:00 EET:  build_daily_feeds
                                        └── 07:00 EET:  send_daily_digests
                                          ↓
                                Neon Postgres (pgvector available)
                                          ↓
                              LLM Router: Groq → Cerebras → Mistral
```

Inbound newsletter: `Resend Inbound webhook → /webhooks/inbound-mail → raw_inbound_emails → LLM extractor → raw_events`.

---

## Data sources (live)

1. **Fienta API** — `GET /api/v1/public/events?organizer=<id>`; ~15 Tallinn organizer IDs; weekly auto-discovery (≥3 events → auto-add)
2. **Piletilevi HTML scraper** — 6 listing categories, Tallinn city filter, detail-page description fetch, 200-event cap
3. **JSON-LD venues** — Telliskivi, Kultuurikatel, Fotografiska, KUMU, Estonia Concert Hall
4. **Newsletter inbound** — Resend Inbound webhook → LLM extractor (unique-coverage moat for underground/niche)

**Skipped (decisions preserved):**
- **Eventbrite** — `/v3/events/search/` deprecated for non-partners; adapter removed 2026-05-14
- **Ticketmaster** — no EE inventory
- **Facebook/Meetup scraping** — fragile bot-detection, out of MVP

---

## Data model (Postgres key tables)

- `users` — email (citext unique), locale (et|en|ru), home_city, email_digest_opt_in
- `auth_magic_links` — token_hash (sha256), expires_at (15 min), used_at
- `personas` — 5 static slugs, trilingual display names, affinity_vector JSONB
- `user_personas` — M2M, primary 1.0 / secondary 0.4
- `sources`, `ingestion_runs`, `raw_events`, `event_sources`
- `events` — slug, title/description_orig, starts_at/ends_at, venue, lat/lng, price, status (draft|classified|published|cancelled), dedup_group_id
- `event_classifications` — categories[], vibes[], quality_score, why_go_bullets[3], **why_go_localized** JSONB ({locale: [bullets]}), language_detected, model_used
- `user_event_feedback` — like/dislike/bookmark/view/click_external
- `user_event_scores` — cached score per (user, event)
- `daily_feeds` — user_id, feed_date, event_ids BigInteger[]
- `raw_inbound_emails` — Resend inbound payload + LLM-extraction state
- `llm_calls` — content_hash cache + audit (provider, model, tokens, response JSONB)

Indexes: `events(starts_at, status)`, `events(dedup_group_id)`, `event_classifications(categories)` GIN, `user_event_feedback(user_id, created_at)`, `events(status)`, `raw_events(source_id)`.

---

## Pipeline

```
fetcher → raw_events → normalizer → dedup → events(draft) → classify → events(published)
```

- **Dedup (two-stage):** rule-based pre-filter (`rapidfuzz.token_set_ratio > 70` + `|Δstart| < 12h` + venue-compatible), then LLM tiebreaker only on candidate pairs (cached by content hash). Merge on `same=true && confidence ≥ 0.7`.
- **Classification:** one LLM call per dedup group; input = title + description + venue + url (≤1200 chars); output = JSON `{categories, vibes, why_go: {en,et,ru}, quality, language}` against fixed 12-cat / 10-vibe / 6-time taxonomy.
- **Hard cap:** ≤600 tokens per LLM call. Cache by content hash. Provider fallback Groq → Cerebras → Mistral.

---

## Personalization

**Personas:** `underground_clubber`, `networking_pro`, `weekend_hobbyist`, `culture_buff`, `family_explorer`. User picks 1 primary + optional 1 secondary at 0.4 weight.

**Scoring:**
```
score = 0.45·persona_affinity + 0.20·recency_boost + 0.20·feedback_signal
      + 0.10·quality_score + 0.05·locality_bonus
```

- `persona_affinity` = normalized dot product over (category, vibe, time_slot) vectors
- `recency_boost` = linear decay, 1.0 today → 0 at +21d
- `feedback_signal` = per-day 0.9^t decay; +1 for category match w/ liked events, −1 for disliked; `dedup_group_id` of disliked events hard-excluded
- `locality_bonus` = 1.0 if lat/lng in central Tallinn bbox
- Cached in `user_event_scores`; invalidated on each feedback row

**Daily 5 builder:** runs 06:00 Europe/Tallinn; scores all published events in next 14 days; MMR-lite diversity (max 2 per category); writes `daily_feeds`.

---

## Frontend

Routes (`frontend/src/routes/`): Login, AuthVerify, Onboarding, Feed, EventDetail, Settings, NotFound.
Components (`frontend/src/components/`): EventCard, PersonaCard, ErrorBoundary.
Server state via TanStack Query. i18n custom `frontend/src/i18n.ts` (no library) with `t()`, `ti()`, `personaName()`, `personaVibe()`.

---

## Code quality

- **Backend constants** → `app/constants.py` (single source of truth)
- **Backend utils** → `app/routers/utils.py`
- **Frontend constants** → `frontend/src/constants.ts`
- **Frontend utils** → `frontend/src/utils.ts`
- **CSS design tokens** → `:root` vars in `frontend/src/index.css`; `.module.css` consumes vars only
- **HTTP retry:** all source adapters use `_http_get()` from `app/ingestion/base.py` (tenacity, 3 attempts, 2–30s backoff)
- **Taxonomy:** `validate_categories()` / `validate_vibes()` before persisting any LLM output
- **Migrations:** chain `down_revision = "PREV"`; small & reversible
- **Datetimes:** tz-aware via `zoneinfo` (`Europe/Tallinn`) — no naive UTC anywhere
- **Email columns:** `citext`

---

## Next steps

### P0 — Blocking soft launch

1. **End-to-end QA against 30 real Tallinn events** (Day 20 was repurposed for backend i18n; QA never executed)
2. **Soft launch to ~10 personal contacts** (Day 21) — depends on QA passing

**QA checklist:**
- [ ] Ingestion smoke — trigger `/admin/ingest` per source; check `ingestion_runs.new_count`; inspect 5 random `events` rows per source
- [ ] Dedup spot-check — find event on Fienta + venue site (e.g. Tallinn Music Week); confirm single `dedup_group_id` + two `event_sources` rows
- [ ] Classification — 10 random events; categories/vibes/why_go sane in all 3 locales; `language_detected` correct for ET/RU events
- [ ] Personalization — 3 test users (clubber / pro / family); run 06:00 builder; verify `daily_feeds` differ; like/dislike shifts next feed
- [ ] Auth flow — request magic link → Resend dashboard → click → land authenticated
- [ ] Free-tier sanity — 24h: Neon CU-h <3/day, Groq req <500/day, Resend send count
- [ ] Cold-start — Render dyno sleeps 15+ min; first paint <2s after cron warm

### P1 — High value pre-launch or first week post-launch

3. **Submit-an-event form** — manual escape hatch; elevated after Eventbrite removal
4. **Plausible analytics** — deferred from Day 19; trivial once domain confirmed

### P2 — Post-launch / v1.1

5. **pgvector cosine feedback scoring** — replace category-overlap heuristic; Neon pgvector available; needs accumulated feedback data
6. **Render Starter ($7/mo)** — reactive, only if free-tier sleep causes issues

### P3 — Already built, validate in QA

7. **Secondary persona blending (0.4 weight)** — implemented in `onboarding.py`; confirm feel
8. **Bookmarks** — signal + endpoint + UI exist; verify end-to-end

**Recommended execution order:** P0.1 QA → fix surfaced issues → P0.2 soft launch → P1.4 Plausible (post-domain) → P1.3 submit form (first week post-launch) → P2.5 pgvector (once feedback data exists).

---

## Top 3 risks

1. **Source coverage thinness** — Tallinn has no Songkick-grade aggregator. *Mitigation:* heavy investment in newsletter ingestion + submit-event form.
2. **Free LLM quota exhaustion on backfill** — *Mitigation:* Groq → Cerebras → Mistral chain, ≤600 token prompts, content-hash dedup cache, classify post-dedup only, push backfill to Mistral 1B tok/mo tier.
3. **Render free-tier sleep killing scheduler** — *Mitigation:* external Cron Job pings `/internal/tick` every 15 min. Render Starter ($7/mo) removes sleep if needed.

---

## Code-comment TODOs

Synthesized from comments in the codebase (2026-06-04). Ranked by priority.
Items the code documents as intentional design (full score-cache invalidation,
admin-auth refusal, migration dedup guards) are excluded — these are real
deferred/hardening items only.

### P1 — Pre-production hardening

1. **IP-level rate limiting on magic-link request endpoint**
   — `backend/app/routers/auth.py:108` (`# TODO before production: add IP-level
   rate limiting (SlowAPI/fastapi-limiter)`). Today only a per-email 2-minute
   cooldown guards Resend quota; an attacker varying the email address can still
   exhaust the 3k/mo Resend free tier. Add SlowAPI or fastapi-limiter IP throttling
   before/at soft launch.
