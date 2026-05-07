# Event Radar — MVP Implementation Plan

## Context

You want to validate an AI-powered event-discovery idea cheaply: a personalized "Daily 5" of curated events for **Tallinn**, built by a solo Python developer in 2–3 weeks, on free-tier infrastructure only. This plan keeps Python full-stack, drops scraping in favor of APIs/JSON-LD/newsletters, and commits to **Personalization** as the single product differentiator.

Tallinn's population speaks three languages — **Estonian, English, and Russian** — so the product targets all three from day one. Every user-facing string, event classification output, and LLM prompt must support `et`, `en`, and `ru` locales.

Confirmed decisions:
- **Stack:** FastAPI + Vite/React SPA, Postgres on Neon free
- **City:** Tallinn (one city, hyper-local)
- **Auth:** magic-link email
- **AI:** free-tier LLMs only (Groq → Cerebras → Mistral fallback chain)
- **Differentiator:** persona-based onboarding + like/dislike learning
- **Sources:** free APIs + ICS/RSS + newsletter parsing — **no UI scraping** of FB/Meetup/Eventbrite

Steady-state cost: **$0/mo** (optional $10/yr for an `.ee` domain).

---

## Architecture

```
                     ┌─────────────────────────────────────────────┐
                     │              Vite/React SPA                 │
                     │   (Vercel CDN, talks to api.eventradar...)  │
                     └────────────────────┬────────────────────────┘
                                          │ HTTPS / JSON
                                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                       FastAPI app (single process)               │
│  ┌────────────┐  ┌────────────┐  ┌─────────────┐  ┌───────────┐  │
│  │  /auth     │  │  /feed     │  │  /events    │  │ /feedback │  │
│  └────────────┘  └────────────┘  └─────────────┘  └───────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │           AsyncIOScheduler  (APScheduler)                  │  │
│  │  hourly: ingest_fienta, ingest_venues, ingest_newsletters  │  │
│  │  every 6h: dedup_pass, classify_pending                    │  │
│  │  daily 06:00 Europe/Tallinn: build_daily_feeds             │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────┬──────────────────────────────────┬────────────────┘
               ▼                                  ▼
       ┌──────────────┐                  ┌────────────────┐
       │ Neon Postgres│                  │   LLM Router   │
       │ (scale-to-0) │                  │ Groq→Cerebras→ │
       └──────────────┘                  │   Mistral      │
                                         └───────┬────────┘
                                                 ▼
                                   ┌───────────────────────────┐
                                   │  External (free-tier LLM) │
                                   └───────────────────────────┘

Inbound newsletter pipeline:
  Resend Inbound webhook → /webhooks/inbound-mail
       → raw_inbound_emails table → LLM extractor → raw_events
```

Single-process design: APScheduler shares the FastAPI DB pool. **No Celery, no Redis** — Gemini was right that the original stack was overweight for an MVP. A Render external Cron Job pings `/internal/tick` every 15 min so scheduler ticks survive Render free-tier sleep.

---

## Tech & service choices

| Layer | Choice | Notes |
|---|---|---|
| Backend | FastAPI 3.12 + SQLAlchemy 2 + Alembic | |
| DB | **Neon free** (`eu-central-1`, 0.5 GB, 100 CU-h/mo, scale-to-zero) | Better than Supabase free which pauses projects after 7 days idle |
| Auth | Self-hosted magic link (`itsdangerous` signed token + email) | No third-party auth lock-in; ~50 LOC |
| Email | **Resend free** (3k/mo, 100/day) | Magic links + daily digest fits |
| LLM primary | **Groq free** (14,400 req/day, `llama-3.3-70b-versatile`, Production) | 30 req/min burst; no sleep loop needed in batch jobs |
| LLM secondary | **Cerebras free** (1M tok/day, `qwen-3-235b-a22b-instruct-2507`, Preview) | 1 req/min; Preview model — monitor for deprecation |
| LLM batch | Mistral La Plateforme free (1B tok/mo, 2 RPM) | Overnight backfill only |
| Scheduler | APScheduler `AsyncIOScheduler` embedded | + external Render Cron Job pinging `/internal/tick` every 15 min |
| Backend host | **Render free Web Service** + free Render Cron Job keepalive | 750 hrs/mo covers 24/7 |
| Frontend host | Vercel free (or Cloudflare Pages) | Static React build |
| Domain | Optional `eventradar.ee` ~$10/yr | Or free `*.onrender.com` for v0 |

**Multilingual tip:** Llama 3.3 70B handles Estonian well per the Estonian Native LLM Benchmark (arxiv 2510.21193) and is strong on Russian natively. Always pass the original event text in the prompt and let the model answer in the user's chosen UI locale (`et`/`en`/`ru`) — works far better than asking it to translate first. Test all three locale paths explicitly, including Estonian diacritics and Cyrillic.

---

## Data sources (wire these 5 first)

1. **Fienta public API** (`GET /api/v1/public/events?organizer=<id>`) — curated list of ~15 Tallinn organizer IDs (Sveta Baar, HALL, Telliskivi tenants, Tallinn Music Week, etc.). One adapter handles all of them.
2. **Telliskivi Loomelinnak** (`telliskivi.cc/en/events/`) — JSON-LD `Event` blocks.
3. **Kultuurikatel** (`kultuurikatel.ee/en/events/`) — JSON-LD.
4. **Fotografiska Tallinn** (`tallinn.fotografiska.com/en/events`) — JSON-LD.
5. **Newsletter inbox** (`radar+tallinn@<domain>` via Resend Inbound webhook) — LLM-extracted events. **This is the highest-ROI channel** and the unique-coverage moat for the underground/niche events that justify persona-based ranking.

Stretch (Week 3): Ticketmaster Discovery API (`countryCode=EE`) for headline concerts; one or two more JSON-LD venues (KUMU, Estonia theatre).

**Skipped** (with reasoning preserved so we don't relitigate later):
- **Eventbrite** — `/v3/events/search/` is deprecated; useless for third-party aggregation.
- **Piletilevi** — no public API, Eventival-backed; could parse JSON-LD on category pages as fallback if a primary source breaks.
- **Facebook / Meetup UI scraping** — explicitly out; fragile bot-detection time-sink, not worth it for an MVP.

---

## Data model (Postgres, key tables)

- `users` — id, email (citext unique), locale (et|en|ru), home_city, created_at
- `auth_magic_links` — id, user_id, token_hash, expires_at (15 min TTL), used_at
- `personas` — id, slug, display_name_{en,et,ru}, affinity_vector (JSONB)
- `user_personas` — user_id, persona_id, weight (primary 1.0, optional secondary 0.4)
- `sources` — id, slug, kind (api|ics|rss|html_jsonld|inbound_email), config (JSONB), enabled, last_run_at, last_status
- `ingestion_runs` — id, source_id, started_at, finished_at, raw_count, new_count, error
- `raw_events` — id, source_id, external_id, payload (JSONB), fetched_at, processed_at NULL
- `events` — id, slug, title_orig, description_orig, starts_at, ends_at, venue_name, venue_address, lat, lng, url, image_url, price_min/max, currency, status (draft|classified|published|cancelled), dedup_group_id
- `event_sources` — M2M; preserves provenance after dedup merges
- `event_classifications` — event_id, categories (text[]), vibes (text[]), quality_score, why_go_bullets (text[3]), language_detected, model_used
- `user_event_feedback` — user_id, event_id, signal (like|dislike|bookmark|view|click_external), created_at
- `user_event_scores` — user_id, event_id, score, computed_at (cached, invalidated on feedback)
- `daily_feeds` — user_id, feed_date, event_ids (int[])

Indexes: `events(starts_at, status)`, `events(dedup_group_id)`, `event_classifications(categories)` GIN, `user_event_feedback(user_id, created_at)`.

---

## Ingestion pipeline (unified for all source kinds)

```
fetcher → raw_events → normalizer → dedup → events(draft) → classify → events(published)
```

- **Fienta API** — async httpx loop over organizer IDs.
- **HTML + JSON-LD** — fetch listing page, extract `<script type="application/ld+json">` with `extruct`, filter `@type == "Event"`. Per-source CSS-selector fallback if JSON-LD missing.
- **ICS** — `icalendar` lib, one VEVENT per RawEvent. (Wire when we discover one — TalTech/TLU calendars are likely candidates.)
- **Inbound email** — Resend Inbound webhook posts raw MIME to `/webhooks/inbound-mail` → `raw_inbound_emails` → LLM extraction prompt → RawEvents.

**Dedup (two-stage, deliberate):** rule-based pre-filter (rapidfuzz `token_set_ratio > 70` + `|Δstart| < 12h` + venue compatibility), then LLM tiebreaker on bucketed candidates only (1 call per pair, JSON response, cached by content hash). On `same=true && confidence>0.7`, merge under one `dedup_group_id`. This is Gemini's "LLM dedup" suggestion implemented sanely — we don't blow tokens by sending every pair, just the candidate pairs that already passed rule-based filtering.

**Classification** — one call per dedup group: input is title + description + venue + url (cap 1200 tokens); output is JSON `{categories, vibes, why_go: [3 bullets], quality, language}` against a fixed 12-category / 10-vibe taxonomy (no ontology drift).

---

## Personalization

**Personas (v0, 5 slugs):** `underground_clubber`, `networking_pro`, `weekend_hobbyist`, `culture_buff`, `family_explorer`. Each is a static affinity vector over (category, vibe, time) seeded as JSONB. User picks 1 primary at onboarding + optional 1 secondary at 0.4 weight.

**Scoring formula (v0, rule-based):**

```
score = 0.45 * persona_affinity(user, event)
      + 0.20 * recency_boost(event)        # 1.0 today/tomorrow → 0 at +21d
      + 0.20 * feedback_signal(user, event)
      + 0.10 * quality(event)
      + 0.05 * locality_bonus              # 1.0 if lat/lng in central Tallinn
```

- `persona_affinity = clip(Σ persona_vec · event_tags, -1, 1)` then mapped to [0,1]
- `feedback_signal`: +1 for events sharing ≥1 category with a liked event (decay `0.9^days_since`), −1 for disliked; events in the user's disliked `dedup_group_id` set are hard-excluded. Aggregated, normalized.
- Cached nightly into `user_event_scores`; invalidated and lazily recomputed on each new feedback row.

**Daily 5 builder** runs at 06:00 Europe/Tallinn: take all `events.status='published'` in next 14 days, score per active user, apply MMR-lite diversity (max 2 per category in top 5), write `daily_feeds`.

v1.1 enhancement (only if pgvector enabled on Neon — it is): replace category-overlap feedback with embedding cosine to user's liked centroid.

---

## Frontend pages (Vite + React + TanStack Query)

- **Login** — single email field → magic link → `/auth/verify?token=...`
- **Onboarding** — pick primary persona (cards with 1-line vibe), optional secondary, locale toggle
- **Daily feed** (home) — header date, the 5 cards: image, title, time, venue, 3-bullet "why go", like/dislike/bookmark buttons
- **Event detail** — full description, map link, "tickets" CTA (external), feedback buttons
- **Settings** — persona re-pick, locale, unsubscribe

That's it for v0. No infinite scroll, no search, no calendar view — those add cognitive load and undercut the "Daily 5" promise.

---

## Phased delivery (3 weeks, solo)

**Week 1 — Skeleton + ingestion**
- Day 1: Repo, FastAPI scaffold, Alembic, Neon DB, Render deploy + healthcheck
- Day 2: Migrations for users / sources / raw_events / events / event_sources / ingestion_runs
- Day 3: Fienta adapter end-to-end; seed 5–10 Tallinn organizer IDs
- Day 4: JSON-LD adapter base class; wire Telliskivi + Kultuurikatel + Fotografiska
- Day 5: APScheduler hourly + `/admin/ingest` page (basic auth)
- Day 6: Rule-based dedup; eyeball cross-source matches
- Day 7: Magic-link auth + onboarding endpoint with persona pick

**Checkpoint:** ≥200 canonical events in DB, no obvious duplicates, login works.

**Week 2 — AI layer + frontend**
- Day 8: LLM router (Groq→Cerebras→Mistral) with rate-limit awareness + `llm_calls` table
- Day 9: LLM dedup tiebreaker layered on rule pre-filter
- Day 10: LLM classifier (categories, vibes, why_go, quality, language); backfill all existing events
- Day 11: Vite/React skeleton, login + onboarding pages, feed page wired to `/feed`
- Day 12: Event detail + like/dislike/bookmark; feedback writes through
- Day 13: Daily 5 builder + scoring formula; test with 2–3 fake users on different personas
- Day 14: Newsletter inbound webhook + LLM extractor

**Checkpoint:** "Daily 5" lands every morning; like/dislike visibly shifts tomorrow's feed.

**Week 3 — Polish + ship**
- Day 15: Settings page, locale toggle, unsubscribe
- Day 16: Email digest of Daily 5 (Resend HTML template)
- Day 17: Ticketmaster adapter + 2 more JSON-LD venues
- Day 18: Estonian + Russian UI strings (i18n pass for all three locales), locale toggle in Settings, Europe/Tallinn date formatting (`zoneinfo`)
- Day 19: Error pages, empty states, Plausible analytics
- Day 20: Manual QA against 30 real Tallinn events of next 14 days; fix worst 5 issues
- Day 21: Soft launch to ~10 personal contacts

**Honest cuts if behind** (in order): extra venues + Ticketmaster (Day 17), email digest (Day 16), secondary persona blending, bookmarks. **Do not cut:** dedup, classification, personalization scoring, magic link, Daily 5.

---

## Critical files to create first

- `C:\Users\Aleksei\event-radar\backend\app\main.py` — FastAPI app + APScheduler bootstrap
- `C:\Users\Aleksei\event-radar\backend\app\ingestion\base.py` — `SourceAdapter` ABC; the unified RawEvent → NormalizedEvent → Event pipeline
- `C:\Users\Aleksei\event-radar\backend\app\ingestion\sources\fienta.py` — first concrete adapter; template for the JSON-LD adapters
- `C:\Users\Aleksei\event-radar\backend\app\ai\router.py` — provider chain (Groq → Cerebras → Mistral) with rate-limit awareness; classifier and dedup-tiebreaker prompts live next to it
- `C:\Users\Aleksei\event-radar\backend\app\ranking\score.py` — persona affinity + recency + feedback formula and the Daily 5 builder
- `C:\Users\Aleksei\event-radar\backend\alembic/versions/0001_init.py` — first migration with all v0 tables
- `C:\Users\Aleksei\event-radar\frontend\src\routes\Feed.tsx` — Daily 5 page (the product surface)

---

## Top 3 risks

1. **Source coverage thinness.** Tallinn has no Songkick-grade aggregator; 5 sources may yield 50–100 events/week, not 500. *Mitigation:* hard investment in newsletter ingestion (Resend Inbound + LLM extractor) — uniquely captures niche/underground events. Add a "submit an event" form as a manual escape hatch.
2. **Free LLM quota exhaustion during backfill.** Initial dedup + classification across hundreds of events can exhaust Groq's 14,400 req/day or Cerebras's 1M-token budget quickly. *Mitigation:* (a) Groq→Cerebras→Mistral fallback chain, (b) cap prompts ≤600 tokens, (c) cache dedup decisions by content hash, (d) classify only canonical events (post-dedup), (e) push overnight backfill to Mistral's 1B tok/mo batch tier.
3. **Render free-tier sleep killing scheduled jobs.** *Mitigation:* external Render Cron Job pings `/internal/tick` every 15 min as the actual scheduling trigger; APScheduler is the source of truth, the cron just nudges it. If traffic warrants, $7/mo Render Starter removes sleep without architecture changes.

---

## Verification (end-to-end test plan)

1. **Ingestion smoke test:** trigger `/admin/ingest` for each source; check `ingestion_runs.new_count` rows and inspect 5 random `events` rows per source.
2. **Dedup spot-check:** find a Tallinn event listed on both Fienta and a venue site (Tallinn Music Week is a likely overlap); confirm one `dedup_group_id` and two rows in `event_sources`.
3. **Classification check:** pick 10 random `events`; verify `categories`/`vibes`/`why_go` make sense to a human; confirm Estonian-language events get `language_detected='et'` and Russian-language events get `language_detected='ru'`; verify why_go renders correctly in all three locales (`et`/`en`/`ru`).
4. **Personalization check:** create 3 test users with different personas (clubber, professional, family); run the 06:00 Daily 5 builder; verify `daily_feeds` contents differ in expected directions; like one event, dislike another, manually invalidate score cache, confirm next feed shifts.
5. **Auth flow:** request magic link → check Resend dashboard → click link → land on feed authenticated.
6. **Free-tier sanity:** after 24 h of running, check Neon CU-hours used (<3 CU-h/day expected), Groq req/day (<500 expected), Cerebras token spend if fallback was hit, Resend send count.
7. **Cold-start test:** let Render free dyno sleep (no traffic 15+ min), then hit the feed; first paint should still be <2s after the cron-warmed Neon connection.
