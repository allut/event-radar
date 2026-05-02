# Event Radar — Implementation Progress

Living log of execution against [`plan.md`](./plan.md). `plan.md` is the original spec and stays unchanged; this file is the audit trail.

---

## Status snapshot

| Field | Value |
|---|---|
| Phase | Pre-Day-1 (repo scaffolding) |
| Plan day | — |
| Week progress | 0% |
| Current focus | Repo bootstrap: `.gitignore`, `progress.md` |
| Last updated | 2026-05-03 |

---

## Implemented

Grouped by plan-day. Format: `[YYYY-MM-DD] (Plan: Day N — <plan title>) — what shipped`.

- `[2026-05-03]` (Pre-Day-1) — Repo bootstrapped: `plan.md` committed; added root `.gitignore` covering FastAPI + Vite/React stack, and seeded this `progress.md`.

---

## Issues & fixes

Format per entry:
- **Symptom:** what was observed
- **Root cause:** why it happened
- **Fix:** what was changed
- **Time lost:** rough wall-clock

_(none yet)_

---

## Decisions / deviations from plan

Anything that contradicts or extends `plan.md`. Format: *What changed → Why → Plan section affected.*

- **2026-05-03 — Single root `.gitignore` instead of per-subdir (`backend/.gitignore` + `frontend/.gitignore`).**
  - *Why:* simpler for a solo dev; the backend/ and frontend/ trees are small and the rules don't conflict.
  - *Plan section affected:* none directly; revisit if backend/frontend ever split into separate repos.

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
