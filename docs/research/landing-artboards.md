# Landing Artboards

What's in here: the record of the ten Landing prototypes built for wayfinder #184 (under #181) — where the source lives, what each artboard commits to, the Cyrillic specimen judgement the ticket asked for, what the real Estonian/Russian strings did to the layouts, and the caveats a reader must carry before picking a winner. It does **not** pick the winner; that is the dev's call.

## Where it lives

- **Artifact (the comparison sheet):** <https://claude.ai/code/artifact/d069d0ae-72c0-41c4-85f9-daa74e75208a>
- **Source:** `prototypes/landing/artboards/{a1,a2,a3,b1,b2,b3,c1,c2,d1,d2}.html` — ten standalone single-file documents, no build step, no React, no wiring to the app. Throwaway per the ticket.
- **Assembler:** `prototypes/landing/build.py` inlines each document into a `<script type="text/plain">` block and emits `prototypes/landing/artboards.html`, the exact file published as the Artifact. Re-run it after editing any artboard.

Each artboard is rendered in its own `srcdoc` iframe, so the ten CSS systems cannot contaminate each other. The sheet carries three evaluation controls:

| Control | What it does |
|---|---|
| **Width** 1280 / 900 / 390 | Re-renders every artboard at that viewport and rescales to fit the column. |
| **Strip imagery** | Adds `noimg` to each artboard's root, hiding every photographic plate — the direct test of the ticket's "imagery amplifies, never load-bearing" rule. |
| **Reduced motion** | Adds `rm`, applying the same collapse each artboard's `prefers-reduced-motion: reduce` block applies. |

## The ten

Six keep the current brand (`#13161e` / `#c8922a` / Cormorant Garamond). Four push. Body face is **Manrope everywhere**, per #190 — not a lever any direction pulls.

| # | Variant | Brand | Display face | Locale | Signature |
|---|---|---|---|---|---|
| A1 | dark-editorial | on-brand | Cormorant Garamond | EN | Dateline masthead, drop cap, boxed classified ad; density from type, not boxes |
| A2 | light-paper | **push** — newsprint grey + one spot red, no gold | PT Serif | **ET** | Two-colour press; email capture is a dashed subscription coupon |
| A3 | dense-index | on-brand | Cormorant Garamond | EN | The page *is* the listings; fourteen category letter-codes with a legend; sticky capture rule |
| B1 | full-instrument | on-brand | Cormorant + JetBrains Mono | EN | Live sweep with labelled returns, monospaced signal ledger, CSS-only counting gauges |
| B2 | restrained-instrument | on-brand | Cormorant + JetBrains Mono | **RU** | One instrument only — the eight-week volume histogram; margin ticks; nothing spins |
| B3 | instrument-with-imagery | **push** — night-cockpit red instead of gold | Cormorant + JetBrains Mono | EN | Photography arrives as duotone channel feeds with mono readouts |
| C1 | cinematic-on-brand | on-brand | Cormorant Garamond | **ET** | Stacked full-bleed posters under scrims, gold hairline cutting each frame, flat proof section below |
| C2 | cinematic-new-type | **push** — oxblood/bone/silver, no gold, no navy | Playfair Display (variable) | EN | Sticky filmstrip rail of tonight's times down the left margin; Playfair very large, very tight |
| D1 | dark-board | on-brand | Cormorant + Manrope 800 tabular | EN | Split-flap reveal on the destination and every row; the email capture is itself a board row at 06:00 |
| D2 | warm-light-board | **push** — warm light ground, black rules, one signal blue | Oswald (variable) | **RU** | Condensed Cyrillic at ~100 px on a warm board; the Oswald specimen test |

Every artboard carries the IA floor: email capture, proof-of-events, organizer CTA.

## Cyrillic specimen judgement

The ticket asked for a judgement on rendered Russian, not just subset coverage. Four faces were put under real `ru` copy (B2 and D2 are written entirely in Russian; A3 and D1 carry Russian event titles inside otherwise-English pages).

- **Manrope body copy — passes, no reservation.** Rendered at 15–16 px across B2's standfirst, step bodies and event list, the Cyrillic holds the same x-height, stroke contrast and terminal treatment as the Latin. `щ` (*площадки*), `ж` (*ждут*), `д`, `у`, `я` are all properly constructed rather than assembled from Latin parts, and the Russian sets to the same colour on the page as the English does. This is what #190 predicted from the designer attribution; it is now confirmed visually. **No reason to reconsider the body face.**
- **Cormorant Garamond display — passes.** At 68 px (B2's `h1`) and in italic (*из дома*) the Cyrillic is a real Garamond-flavoured cut, not a mechanical widening. Worth knowing since six of the ten artboards ride on it and #182 never had to check it.
- **Oswald display — passes, and is the best of the pushes.** At ~100 px on D2's split-flap destination (**ТАЛЛИНН**) and at 44 px in the headline, the condensed forms are even and the counters survive the compression; the Cyreal retrofit credited in #182 shows no seam. If D2 wins, its Cyrillic is not a risk.
- **JetBrains Mono — legible, but unvetted.** B1/B2/B3 use it for instrument labels. Its Cyrillic renders fine at 10–12 px, but **it is a fourth face that #182 never evaluated** — payload, licence and subset economics are unmeasured. If direction B wins, that face needs its own pass before it ships (or the mono role collapses onto a system stack).

## What the real ET/RU strings did to the layouts

Four artboards were written in the target locale rather than translated English, so the pressure is real:

- **`landing_personas_title`** is the worst string in the set. Estonian *"Loodud selle järgi, kuidas sina tegelikult välja lähed"* (52 ch) and Russian *"Создано под то, как вы на самом деле проводите время"* (51 ch) are ~1.6× the English. Both need a section heading that can run to two lines at display size — A2 and B2 both had to give the heading its own row rather than sharing a baseline with a right-hand label.
- **`landing_hero_h1`** grows from 42 ch (EN) to 60 ch (ET). C1's hero and A2's lead both hold it at three lines only because the display size is clamped by `vw`; a fixed-px hero would break. **Any hero headline in the winning direction must be `clamp()`-sized and tested against the Estonian string, not the English one.**
- **Russian runs long in short slots**, not just long ones: *"Отправить ссылку →"* vs *"Send link →"*, *"Добавить событие →"* vs *"List your event →"*. B2's inline submit and D2's board-row button both needed `white-space: nowrap` plus a wider column. A button sized to the English label will wrap in `ru`.
- **Event titles are the real stress test, not the UI copy.** Genuine catalogue rows like *"Внутри «Деловых ведомостей»: как работает и зарабатывает редакция"* (63 ch) and *"Pokudel külas: haridusprogramm Edgar Valteri raamatute ainetel"* force two- and three-line titles in every listing layout. A3 and D1 handle it; a design that assumes one-line titles will not survive contact with the catalogue.

## Facts on the page

Everything numeric comes from `docs/research/landing-true-facts.md` (31 Aug 2026 snapshot): **1 008** upcoming, **82** in the next seven days, **8** tonight, **205** venues, **14** categories, booked into **2027**, cheapest ticket **€1**, Telliskivi 60a/9 at **170** events, source counts Piletilevi 752 / Fienta 663 / KUMU 31 / Estonia Concert Hall 11 plus organizers, feed built 06:00 and digest sent 07:00 Europe/Tallinn, sources re-read hourly, three locales. B2's histogram uses the real eight-week band (80 / 81 / 81 / 73 / 69 / 64 / 75).

Deliberately **not** used, per that research: the 308-venues figure (wrong scope), any "N new events per week" throughput claim (the snapshot is a bulk seed load), the €420 price ceiling, and the thin category tail — A3's legend prints counts only down to Nightlife (92) and shows Food & drink, Sport, Networking, Romantic and Cinema as codes without numbers.

## Caveats before picking a winner

1. **The photography is fake, the layout is not.** The Artifact sandbox blocks external images, so every "photo" is layered CSS gradients with SVG film grain. Judge composition, scrim behaviour and how type sits over an image — not the picture. C1, C2 and B3 will all look materially better with real event imagery (99.9 % of published events carry one).
2. **Fonts come from the Google Fonts CDN in the prototypes.** Production CSP is `font-src 'self'`, so the winner must switch to `@fontsource` self-hosting. Every face used is confirmed self-hostable by #182/#190 except JetBrains Mono (see above).
3. **B1's counting gauges use `@property` + `counter()`.** They animate 0 → 1 008 with no JS. Where `@property` is unsupported the number renders static and correct, so it degrades safely — but it is a modern-CSS trick, not a universal one.
4. **The prerender gate is untested here.** `frontend/scripts/prerender.ts` drives Landing with Playwright and waits on `<link rel="canonical">`. All motion in all ten artboards is CSS-only and completes within ~2.5 s, but no artboard has been run through the actual prerender pass.
5. **Mobile is sketched, not resolved.** Every artboard has a 900 px and a 390 px breakpoint and none breaks, but the 390 px treatments are first-pass — the departure-board rows in particular reflow into a two-line stack that would want more design if D wins.
6. **D2's board is dark on a light page.** "Warm-light-board" reads as a warm light ground with a black board on it, which is what a real departure board looks like. If the intent was a fully light board, that is a one-token change.
