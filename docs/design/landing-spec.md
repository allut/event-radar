# Landing design spec: lock C1 (cinematic-on-brand)

What's in here: the locked spec for the Landing redesign — wayfinder #185, under #181 — for direction **C1 (cinematic-on-brand)**. This supersedes an earlier lock of C2 (cinematic-new-type): C2 was built and shipped, then reverted by the dev after live review (screen 2880×1620) found the palette/type push read as stale rather than considered, so #181 was revisited and this ticket re-run against C1. Read `docs/research/landing-artboards.md` for how both directions compare; read this file for what actually ships.

## Direction

**C1 — cinematic-on-brand.** Source prototype: `prototypes/landing/artboards/c1.html`. Stacked full-bleed event "poster" plates under dark scrims, a thin gold hairline cutting each frame, Cormorant Garamond at large display sizes over the existing navy/gold brand — not a palette push. Six of the ten artboards (including C1) kept the current brand; C1 is the pick among those six.

**Why C1 over C2:** C2's oxblood/bone/silver push read as a deliberate departure on paper and in the artboard sheet, but at real content density and a 2880×1620 desktop it read stale rather than considered (see screenshots attached to the redirect from #181) — new palette without enough new information architecture to justify it. C1 keeps the type-over-imagery cinematic structure (the actual signature worth having) without asking the palette to do the differentiation's heavy lifting.

## Palette

No sitewide token rename. C1 stays on the current brand tokens (`--bg-page` / `--text-primary` / `--accent-gold` etc. — read the live names off `frontend/src/index.css` at implementation time, do not hardcode hex here). This reverses the C2-era plan in the now-stale `docs/design/landing-token-diff.md` (#187, still open — re-run it against this smaller footprint, don't reuse its diff).

New tokens this direction needs (additive only):

- `--poster-frame`: `rgba(<gold>, 0.28)` — the thin inset border on the hero poster.
- `--grain`: the existing SVG-turbulence data-URI texture (already used nowhere in the shipped app; C1's prototype defines it inline — promote it to a token so `Animations.module.css` and Landing share one definition).
- `--scrim-vertical`: the existing bottom-heavy `linear-gradient(0deg, ...)` pattern used for hero legibility scrim — already implicit in several components; name it once.

`--radius` stays at its current value. C2's `--radius: 0` was a deliberate part of that direction's flat/departure-board-adjacent read; C1 doesn't ask for it, and reverting it removes a blast-radius item `#187` otherwise has to re-litigate for every consumer route.

## Type

- **Display:** Cormorant Garamond, already self-hosted (`@fontsource/cormorant-garamond`, weights 400/500/600 + 400-italic imported in `main.tsx`). C1's prototype leans on **300** for large display sizes (`h1`, plate `h2`, step numerals) and 300-italic for the em accents (`<i>välja</i> minna`) — neither weight is imported today. Add `@fontsource/cormorant-garamond/300.css` and `/300-italic.css`.
- **Body:** Manrope — this was already decided independent of C2 vs. C1 (#190: DM Sans has no Cyrillic cut). That decision stands untouched by this redirect. It never shipped (the commit that wired it in was part of the reverted C2 implementation), so **implementing #190's swap is back in scope for the C1 implementation ticket** (#189), not a new decision.
- Scale: per `c1.html` — hero `h1` at `clamp(46px, 8.4vw, 116px)` / line-height .94 / letter-spacing -.03em; plate `h2` at `clamp(32px, 5vw, 64px)`; flat-section `h2` at `clamp(30px, 4.4vw, 56px)`. Carry these as `--font-size-display-hero` / `--font-size-display-plate` / `--font-size-display-section` tokens rather than inline `clamp()` per component, so the wide-viewport fix below has one place to extend from.

## Section IA

Locked to `c1.html`'s structure, in order:

1. **Hero** — full-bleed poster background (placeholder gradient until real photography lands, still fog per #181), dateline + live counts strip pinned top, headline + subcopy + email capture pinned bottom, thin gold frame inset over the whole poster.
2. **Ticker** — a single-line "tonight" marquee of time-stamped event titles, CSS `@keyframes slide` marquee, pauses under `prefers-reduced-motion`.
3. **Three showcase cards** — split-panel event cards (fixed-height `object-fit: cover` image beside the text, alternating left/right), no `EventCard`. Each: eyebrow (day · time · category), headline, one line of proof copy, a gold hairline, a metadata row (venue / price / category).
4. **Flat proof section** — "how it works," 3 numbered steps + a 5-figure stat row (upcoming count / venues / categories / furthest-booked date / cheapest ticket), reads with imagery stripped per the IA floor.
5. **Organizer CTA** — single row, headline + one line + outlined button.
6. **Footer** — trust line (no password / no tracking / free) + locale list + year.

This matches #185's original IA-floor requirement (email capture, proof-of-events, organizer CTA) unchanged from the C2 lock — the IA itself wasn't what needed revisiting, the palette was.

## Motion vocabulary

Reuse, don't redesign — #186 (motion + prerender-gate ticket) is still open and unblocked; its scope (named vocabulary as `Animations.module.css` classes extending `.rise`/`.breathe`/`.spin`, 400ms mount-fallback so scroll-gated reveals fire during prerender) applies unchanged to C1. The concrete motions C1's prototype uses, for #186 to formalize:

- `rise` — headline lines translate up from a masked overflow container on load (hero `h1`, staggered ~120ms).
- `draw` — a hairline scales in from 0 width (the cutline under the hero subcopy, the `.hair` rule on each plate).
- `drift` — the poster background image slow-scales/pans continuously (hero only — dropped from showcase cards, see [Showcase card imagery](#showcase-card-imagery-split-panel-not-full-bleed)), `26s` ease-in-out-alternate.
- `slide` — the tonight-ticker marquee, linear infinite.

No new vocabulary beyond what #186 already scoped; only the palette these motions render against changed.

## Depth and texture

- Grain overlay (`--grain`) on the hero poster image, `mix-blend-mode: overlay`, low opacity (~.3) — breaks up flat gradient placeholders and will sit under real photography too. Hero-only; dropped from showcase cards (see [Showcase card imagery](#showcase-card-imagery-split-panel-not-full-bleed)).
- Thin `1px` gold-tinted frame inset on the hero only (`--poster-frame`), not repeated on showcase cards — keeps the frame as a hero-specific signature rather than a generic border style.
- Hairlines (`--rule`, unchanged token) separate every flat-section region — steps, figures, organizer band, footer — same pattern already in use sitewide, not new.

## Big screens: the empty-hero-space fix

**Problem** (from the C2 review at 2880×1620, screenshot 085647): a `clamp()`-capped display headline plus a `.wrap{max-width:1240px}` centered column leaves a large, visually empty poster region on both sides of the text column once the viewport exceeds roughly 1600–1700px — `vw`-based type scaling caps out (by design, so lines don't run absurdly long) but nothing fills the reclaimed width, so it reads as unfinished rather than cinematic.

**Fix, locked for the implementation ticket:** above a new `--bp-wide: 1680px` breakpoint, the hero becomes a two-column grid — the existing text column (unchanged, still capped) plus a right-hand panel showing a condensed version of the tonight-ticker (3–4 time-stamped rows, not the full marquee) as a static card. This gives the reclaimed width a second point of interest tied to real data (reusing the ticker's existing data source, no new fetch) instead of trying to solve it with type scale alone — `vw` clamping was already in C1's prototype and the empty-space problem still showed up in the shipped build, so scale alone is confirmed insufficient. Below `--bp-wide`, the panel doesn't render and the ticker strip below the hero is the only "tonight" surface, same as `c1.html` today.

This is additive to `c1.html`'s structure (a new conditionally-rendered hero panel), not a rewrite of it. **Status:** this hero side panel was never implemented and was removed from scope in round 3 (commit `318385c`) — this section describes a component that no longer exists in the shipped app.

## Showcase card imagery: split-panel, not full-bleed

**Problem** (found live, three tuning rounds after ship): the shipped showcase cards were full-bleed sections with the image `object-fit: contain`-ed into a viewport-shaped box (`viewportWidth : min(78vh, 620px)`, a ratio no event poster naturally matches), plus a blurred `cover` backdrop, an edge mask, and a lateral scrim to disguise the resulting letterboxing. Three rounds of tuning the scrim/mask constants couldn't fix it, because the root cause was structural: the container's shape came from the viewport, and every image was asked to fit into it regardless of its own aspect ratio.

**Fix, shipped:** each showcase card is a two-column grid — a fixed-height image panel (`--plate-media-min-height`, 300px desktop / 210px stacked) beside the text column, image filled with `object-fit: cover`. A cover-filled fixed panel is ratio-proof by construction: portrait, square, and landscape sources all fill it identically, with no letterbox to disguise — so the backdrop image, edge mask, and lateral scrim are gone, along with the `--scrim-lateral` token. Cards alternate text left/right (`.plate` / `.plateFlip`) the same as before.

**Not carried over from the B3 prototype this borrows its structure from:** the `.readout` mono strip over the image (would duplicate the eyebrow/meta row, and the repo has no mono face), the scanline overlay, the grain layer (stays hero-only), and the `drift` slow-scale animation (a 26s drift on three mid-size panels competed with the hero rather than supporting it).

**Open follow-up, not yet implemented:** a per-event `object-position`/focal-point hint. `EventData` carries no focal point or intrinsic dimensions today, so `center` is the only available anchor without a backend change.

## Open items carried to other tickets

- **#186** (motion/prerender) — unchanged scope, re-run against C1's four motions above (same set C2 used, palette-only difference).
- **#187** (token/component diff) — needs a full re-run: C1's blast radius is materially smaller than C2's (no sitewide rename, no `--radius: 0`), so its existing body describing a rename is stale and should be rewritten, not patched, when that ticket is picked up.
- **#188** (live numbers) — unaffected by the C1/C2 redirect; its `/public/counts` design doesn't depend on which palette renders the numbers.
- **#189** (ship it) — blocked on this ticket, #186, #187, #188 as before; now also carries: implement the `--bp-wide` hero panel (later removed, round 3), the split-panel showcase-card treatment, and execute #190's Manrope swap (never shipped, since the commit that did was reverted with the rest of C2).
