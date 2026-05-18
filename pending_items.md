# Event Radar — Pending Items

_Analysis date: 2026-05-19. Source: plan.md + progress.md._

---

## Status

Days 1–20 complete. Day 21 (soft launch) not started.

---

## Pending Tasks (prioritized)

### P0 — Blocking soft launch

| # | Task | Source | Notes |
|---|---|---|---|
| 1 | **End-to-end QA verification** (7-item checklist) | plan.md §Verification | Day 20 was repurposed for backend i18n; actual QA against 30 real events not documented as done |
| 2 | **Soft launch to ~10 personal contacts** | plan.md Day 21 | Depends on QA passing |

**QA checklist items (all unverified):**
- [ ] Ingestion smoke test — trigger `/admin/ingest` for each source; check `ingestion_runs.new_count`
- [ ] Dedup spot-check — find event listed on Fienta + venue site; confirm single `dedup_group_id`
- [ ] Classification check — 10 random events; verify categories/vibes/why_go in all 3 locales (`et`/`en`/`ru`)
- [ ] Personalization check — 3 test users (clubber/professional/family); run 06:00 builder; verify `daily_feeds` differ; like/dislike shifts next feed
- [ ] Auth flow — request magic link → Resend dashboard → click → land authenticated
- [ ] Free-tier sanity — after 24h: Neon CU-h (<3/day), Groq req/day (<500), Resend count
- [ ] Cold-start test — let Render dyno sleep 15+ min; first paint <2s after cron warm

### P1 — High value, pre-launch or first week post-launch

| # | Task | Source | Notes |
|---|---|---|---|
| 3 | **Submit-an-event form** | plan.md Risk #1, progress.md | Elevated after Eventbrite removal; manual escape hatch for source-coverage thinness |
| 4 | **Plausible analytics setup** | progress.md | Deferred from Day 19 — blocked on domain decision; trivial once domain confirmed |

### P2 — Post-launch, v1.1

| # | Task | Source | Notes |
|---|---|---|---|
| 5 | **pgvector cosine feedback scoring** | plan.md §Personalization v1.1 | Replace category-overlap heuristic; Neon pgvector already available; implement once feedback data exists |
| 6 | **Render Starter upgrade ($7/mo)** | plan.md Risk #3 | Reactive — only if free-tier sleep causes problems post-launch |

### P3 — Already implemented, just validate in QA

| # | Task | Source | Notes |
|---|---|---|---|
| 7 | **Secondary persona blending (0.4 weight)** | progress.md Day 7 | Implemented in `onboarding.py`; validate it feels non-monodimensional |
| 8 | **Bookmarks feature** | plan.md §Honest cuts | Signal + endpoint + UI all exist; verify end-to-end in QA |

---

## Explicitly out of scope (documented decisions)

- Ticketmaster Discovery API — no EE inventory; replaced by Piletilevi
- Eventbrite — deprecated `/v3/events/search/` for non-partners; removed 2026-05-14
- Facebook/Meetup UI scraping — fragile, explicitly excluded from MVP

---

## Recommended execution order

1. Run QA checklist (P0.1) — find and fix issues
2. Fix top issues surfaced by QA
3. Soft launch to 10 contacts (P0.2)
4. Add Plausible once domain confirmed (P1.4)
5. Build submit-an-event form (P1.3) — within first week post-launch
6. pgvector once feedback data accumulates (P2.5)
