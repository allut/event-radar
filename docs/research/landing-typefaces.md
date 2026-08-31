# Landing Typefaces

What's in here: primary-sourced research for issue #182 (`wayfinder:research`, Landing redesign wayfinder #181) — which display typefaces the brand-pushing prototypes (A2 light-paper, C2 cinematic-new-type, D2 warm-light-board) can actually ship, given the SPA's `font-src 'self'` CSP and its Cyrillic/Latin Extended locale requirements. Pure research; no code changed, no accompanying implementation.

## Grounding: how fonts work here today

- **CSP.** `docs/backend-ops.md` (Deployment → Frontend — Vercel): the SPA's CSP sets `script-src`/`connect-src`/`font-src` all to `'self'`, which "works because fonts are self-hosted (`@fontsource/dm-sans` + `@fontsource/cormorant-garamond`, imported in `src/main.tsx`, bundled into the build; the former Google Fonts `<link>` is gone)". A Google Fonts CDN `<link>` is explicitly ruled out; any face used on Landing must ship as an `@fontsource` npm package bundled by Vite.
- **Current imports** (`frontend/src/main.tsx`, lines 9–16):
  ```
  import '@fontsource/dm-sans/300.css';
  import '@fontsource/dm-sans/400.css';
  import '@fontsource/dm-sans/500.css';
  import '@fontsource/dm-sans/600.css';
  import '@fontsource/cormorant-garamond/400.css';
  import '@fontsource/cormorant-garamond/400-italic.css';
  import '@fontsource/cormorant-garamond/500.css';
  import '@fontsource/cormorant-garamond/600.css';
  ```
  `frontend/package.json`: `"@fontsource/cormorant-garamond": "^5.3.0"`, `"@fontsource/dm-sans": "^5.3.0"`.
  `frontend/src/index.css`: `--font-display: 'Cormorant Garamond', Georgia, serif;` (line 56); body copy is set directly to `'DM Sans', system-ui, sans-serif` (line 341). `--font-mono` is a system stack only — the file's own comment (lines 57–60) notes this is deliberate: "Never a webfont: `font-src 'self'`... only serves the two `@fontsource` [families]."

- **A load-bearing finding the baseline surfaces:** the installed `@fontsource/dm-sans/metadata.json` lists `"subsets": ["latin", "latin-ext"]` — **no `cyrillic`**. Confirmed independently by fetching the CSS itself (`node_modules/@fontsource/dm-sans/400.css`): its two `@font-face` blocks cover only a `latin` and a `latin-ext` `unicode-range`; there is no third block for Cyrillic code points at all. That means **DM Sans body copy on the `ru` Landing already silently falls back** to the CSS chain's next name — `system-ui, sans-serif` — for every Cyrillic character. This isn't a new prototype's problem to avoid creating; it's the site's current, un-flagged behavior, and it sets the bar: a prototype that adds a Cyrillic-less display face merely repeats a pattern the site already has in production, but the ticket's constraint (a face that drops to fallback on `ru` is disqualified) applies to whatever the *redesign* introduces, so every candidate below is still held to full Cyrillic coverage.
- Cormorant Garamond's own `metadata.json` lists `"subsets": ["cyrillic", "cyrillic-ext", "latin", "latin-ext", "vietnamese"]` — it already covers `ru`, which is why the current serif display face renders correctly there today.
- Mechanism verified directly in the installed CSS: each `@fontsource` weight ships one `@font-face` block per subset, gated by a `unicode-range`, e.g. (from `node_modules/@fontsource/dm-sans/400.css`):
  ```
  unicode-range: U+0100-02BA,U+02BD-02C5,... /* latin-ext */
  unicode-range: U+0000-00FF,U+0131,...      /* latin */
  ```
  A browser only fetches the woff2 file(s) for the subset(s) it actually needs to render the characters on the page — so a page's real payload is per-locale, not the sum of every subset in the package.

## Baseline payload (today, imported weights only)

Measured directly from `frontend/node_modules/@fontsource*/**/files/*.woff2` (`ls -la` / `find`), for exactly the weights `main.tsx` imports:

| Family | Weights imported | Subset | Bytes (sum of imported weights) |
|---|---|---|---|
| DM Sans | 300, 400, 500, 600 (no italic) | latin | 56,356 (≈ 55.0 KB) |
| DM Sans | 300, 400, 500, 600 | latin-ext | 29,404 (≈ 28.7 KB) |
| DM Sans | — | cyrillic | **does not exist** (package has no cyrillic cut) |
| Cormorant Garamond | 400, 400-italic, 500, 600 | latin | 93,244 (≈ 91.1 KB) |
| Cormorant Garamond | 400, 400-italic, 500, 600 | latin-ext | 80,676 (≈ 78.8 KB) |
| Cormorant Garamond | 400, 400-italic, 500, 600 | cyrillic | 51,432 (≈ 50.2 KB) |

Realistic per-visit download (only the subset(s) a page's actual characters trigger get fetched):

- **`en` visit:** DM Sans latin (~55.0 KB) + Cormorant latin (~91.1 KB) ≈ **~146 KB** for both families across all imported weights.
- **`et` visit:** adds latin-ext once õäöü appear in body copy or headings ≈ up to **~253 KB** worst case (both families, both subsets).
- **`ru` visit:** DM Sans contributes **0 bytes** (no cyrillic cut → renders in fallback `system-ui`); Cormorant Garamond contributes only its cyrillic subset, ~50.2 KB. So the current `ru` Landing is, ironically, the *lightest* of the three locales today — but at the cost of the body typeface silently not being on-brand.

**Budget takeaway for Landing (prerendered SEO route, LCP-sensitive):** the existing display face alone already costs ~90–170 KB per visit across the weights in use. A same-scale replacement display face — 2–3 weights, needed subsets only — landing in the same ~50–150 KB band per locale is a lateral move, not a regression. Treat **~150 KB total per candidate** (summed across only the subsets a given locale actually needs) as the ceiling before it becomes a real LCP risk; anything cheaper is a clean win, and variable-font packages (below) make a wider weight range available *under* that ceiling.

## Candidate shortlist

All confirmed via the Fontsource API (`https://api.fontsource.org/v1/fonts/<id>`, `variants[].woff2` URLs served from `cdn.jsdelivr.net/fontsource/fonts/...`) and cross-checked against Google Fonts' own metadata (`https://raw.githubusercontent.com/google/fonts/main/{ofl,apache}/<dir>/METADATA.pb`) for designer/license/subset ground truth. Byte sizes are `Content-Length` from `curl -sI` HEAD requests against the jsdelivr URLs the Fontsource API itself returns — i.e., the actual file a browser would fetch.

| # | Direction | `@fontsource` package | Category | Weights (static) | Variable pkg? | Subsets | Cyrillic confirmed | License | Designer / foundry |
|---|---|---|---|---|---|---|---|---|---|
| 1 | A2 editorial serif | `@fontsource/pt-serif` | serif | 400, 700 (+ italics) | none published | cyrillic, cyrillic-ext, latin, latin-ext | ✅ | OFL-1.1 | ParaType (Russian foundry — Cyrillic-native by design) |
| 2 | A2 editorial serif (alt) | `@fontsource/spectral` | serif | 200–800 (+ italics) | none published | cyrillic, cyrillic-ext, latin, latin-ext, vietnamese | ✅ | OFL-1.1 | Production Type |
| 3 | C2 high-contrast display | `@fontsource-variable/playfair-display` (or static `@fontsource/playfair-display`) | serif/display | 400–900 continuous (variable) or 400,500,600,700,800,900 (static) | **yes** | cyrillic, latin, latin-ext, vietnamese | ✅ | OFL-1.1 | Claus Eggers Sørensen |
| 4 | C2 high-contrast display (alt) | `@fontsource/yeseva-one` | display | 400 only | n/a (single weight) | cyrillic, cyrillic-ext, latin, latin-ext, vietnamese | ✅ | OFL-1.1 | Jovanny Lemonad (Russian type designer/foundry — `lemonad@jovanny.ru`) |
| 5 | D2 slab/grotesk (departure board) | `@fontsource-variable/roboto-slab` (or static `@fontsource/roboto-slab`) | slab serif | 100–900 continuous (variable) or 100–900 in steps of 100 (static) | **yes** | cyrillic, cyrillic-ext, greek, greek-ext, latin, latin-ext, vietnamese | ✅ | Apache-2.0 | Christian Robertson |
| 6 | D2 slab/grotesk (alt) | `@fontsource-variable/oswald` (or static `@fontsource/oswald`) | condensed sans/grotesk | 200–700 continuous (variable) or 200,300,400,500,600,700 (static) | **yes** | cyrillic, cyrillic-ext, latin, latin-ext, vietnamese | ✅ | OFL-1.1 | Vernon Adams, Kalapi Gajjar, **Cyreal** (a Cyrillic type-design studio credited on the retrofit) |

### Per-candidate weight+size detail (only the needed subsets, actual weights a prototype would plausibly use)

Bytes are the sum of `latin + latin-ext + cyrillic` woff2 files for the listed weight(s), from live HEAD requests against `cdn.jsdelivr.net/fontsource/fonts/<id>@latest/...`:

- **PT Serif**, weights 400 + 700 (static only): 400 = 76,792 B (~75.0 KB); 700 = 69,996 B (~68.4 KB). **Total ≈ 146.8 KB** for 2 weights, no variable option exists (`npm view @fontsource-variable/pt-serif` → 404).
- **Spectral**, weights 400 + 600 (static only): 400 = 57,308 B (~56.0 KB); 600 = 60,668 B (~59.3 KB). **Total ≈ 115.3 KB** for 2 weights; no variable package (`@fontsource-variable/spectral` → 404).
- **Playfair Display**, static 400 + 700: 45,636 B + 48,488 B ≈ **94.1 KB for 2 discrete weights**. **Variable** package (`@fontsource-variable/playfair-display`, confirmed on npm, v5.3.0), one file per subset covering the *entire* 400–900 axis: latin 38.4 KB + latin-ext 21.1 KB + cyrillic 21.2 KB = **80.7 KB total for the full weight range** — cheaper than 2 static weights and gives every weight on the axis. Clear recommendation: ship the variable package.
- **Yeseva One**, only weight 400: latin 17,492 B + latin-ext 12,920 B + cyrillic 11,328 B = **41,740 B (~40.8 KB)** — the lightest candidate in the set, but zero weight flexibility (single cut only, no bold/light, no variable axis).
- **Roboto Slab**, static 400 + 700: 64,288 B (~62.8 KB) for 2 weights. **Variable** package (`@fontsource-variable/roboto-slab`, confirmed on npm), one file per subset covering the entire 100–900 axis: latin 34.2 KB + latin-ext 21.2 KB + cyrillic 21.4 KB = **76.8 KB total for all 9 weights** — ~14 KB more than 2 static weights but unlocks the whole range.
- **Oswald**, static 400 + 600 + 700: 93,596 B (~91.4 KB) for 3 weights. **Variable** package (`@fontsource-variable/oswald`, confirmed on npm), covering the full 200–700 axis: latin 28.5 KB + latin-ext 24.0 KB + cyrillic 15.7 KB = **68.2 KB total** — cheaper than even the 3 static weights, and cyrillic is unusually light here (15.7 KB) because Oswald's condensed grotesk skeleton needs comparatively few extra glyphs beyond Latin.

**Variable-font takeaway:** every candidate with a published `@fontsource-variable/*` package (Playfair Display, Roboto Slab, Oswald) is cheaper *or* only marginally more expensive than 2 static weights while exposing the *entire* weight axis — a straightforward win once a direction needs more than one weight. PT Serif, Spectral, and Yeseva One have no variable package (confirmed by 404 on the registry); they cost is whatever their static per-weight files add up to.

### Candidates that fail the Cyrillic filter (ruled out, kept here as the negative-case evidence)

Also checked via the Fontsource API — these are exactly the "ideal face but no Cyrillic cut" cases the ticket asks about:

| Package | Category | Subsets (Fontsource API) | Why it looked tempting |
|---|---|---|---|
| `@fontsource/bodoni-moda` | high-contrast serif/display | latin, latin-ext, math, symbols | The textbook C2 didone — closest thing to a "real" Bodoni on Fontsource — but **no cyrillic subset at all**. |
| `@fontsource/fraunces` | editorial serif | latin, latin-ext, vietnamese | Very on-trend "warm editorial" serif with an optical-size axis; **no cyrillic**. |
| `@fontsource/newsreader` | editorial serif | latin, latin-ext, vietnamese | Designed explicitly as a Google/GT-style editorial serif; **no cyrillic**. |
| `@fontsource/archivo` | grotesk | latin, latin-ext, vietnamese | Strong D2 grotesk candidate; **no cyrillic**. |
| `@fontsource/space-grotesk` | grotesk | latin, latin-ext, vietnamese | Popular "new type" cinematic-grotesk look; **no cyrillic**. |
| `@fontsource/dm-serif-display` | display serif | latin, latin-ext | Same type family as the site's DM Sans; **no cyrillic** (mirrors the DM Sans gap noted above). |
| `@fontsource/abril-fatface` | display | latin, latin-ext | Classic ultra-high-contrast display face; **no cyrillic**. |
| `@fontsource/unna` | serif | latin, latin-ext | **No cyrillic**. |

## Per-direction recommendation

- **A2 (light-paper, editorial serif) → PT Serif.** Purpose-built by ParaType for Latin+Cyrillic parity from the outset (not a Latin face retrofitted with Cyrillic glyphs later) — the most defensible choice for a direction whose entire premise is "this reads like real print" in all three locales at once. Only two weights (400/700) are published, which is a real limit if the design wants a light/regular/medium ladder — if that's needed, **Spectral** is the fallback (200–800 in steps of 100 + italics, still fully cyrillic-covered) at a comparable ~115 KB for two weights.
- **C2 (cinematic-new-type, high-contrast display) → Playfair Display, as the `@fontsource-variable` package.** High contrast, unmistakably "display," cyrillic-covered, and the variable package is *cheaper* than shipping two static weights while making the entire 400–900 axis available for whatever weight the cinematic treatment lands on. **Yeseva One** is the alternate for a more ornate/dramatic single-weight hero treatment (lightest payload of any candidate at ~41 KB) — but it commits to exactly one weight, so it only works if C2's type system never needs a second cut.
- **D2 (warm-light-board, slab/grotesk departure board) → Oswald, as the `@fontsource-variable` package.** Its condensed grotesk skeleton is the closest match to split-flap/departure-board lettering of anything on this list, it's cyrillic-covered via a dedicated Cyrillic retrofit credited to Cyreal (a Cyrillic-specialist studio, not an afterthought), and the variable package's cyrillic cut is unusually cheap (15.7 KB) because the condensed forms need few extra glyphs. **Roboto Slab** is the alternate if the direction wants an actual slab-serif (ticks/serifs on the numerals reading more literally as a printed board) rather than a grotesk — same variable-package economics, Apache-2.0 licensed.

## The two-face-split question

**Verdict: not acceptable for a "brand-pushing" prototype; treat a Cyrillic-less ideal face as a hard disqualifier for that direction, not a two-face workaround.**

Reasoning:

1. **The ticket's own framing rules it out.** "A face which can't ship is a prototype that wins on a lie" — a two-face split doesn't make the face ship, it ships a *different* face on `ru` and calls it the same direction. The A/B/C/D prototypes are explicitly being evaluated as brand directions; a direction whose Cyrillic users see a structurally different letterform (different x-height, different contrast, different voice) isn't the same brand experience, it's two brands wearing one name.
2. **`ru` is not a minority fallback path here.** Per `CLAUDE.md`, `ru` is a first-class locale with its own registered routes, digest emails, and full i18n coverage — not a "best effort" locale that tolerates degraded typography the way, say, a rarely-visited legal page might. A split face on the primary Landing marketing surface is a visible, permanent product decision for a first-class audience, not a quiet degradation.
3. **The concrete alternative costs are low enough that a split isn't buying much.** As shown above, every "ideal but Cyrillic-less" candidate (Bodoni Moda, Fraunces, Archivo, Space Grotesk) has a Cyrillic-covered sibling in the same category at a comparable weight/payload cost (Playfair Display for Bodoni Moda's high-contrast slot; PT Serif/Spectral for Fraunces'/Newsreader's editorial slot; Oswald/Roboto Slab for Archivo's/Space Grotesk's grotesk slot). The "ideal" face's marginal aesthetic edge over its Cyrillic-covered sibling is not obviously worth a permanent brand fork.
4. **Where a split could be defensible:** a narrow, clearly-scoped exception — e.g., a single hero word or logotype treatment rendered as a static image/SVG rather than live webfont text, with the surrounding live type staying on one Cyrillic-covered family across all locales. That's not the two-face split the ticket is asking about (swapping the *body* display face per locale); it's confining the ideal-but-Latin-only face to a decorative, non-live-text role. If a direction can't be made to work that way, it should lose to a direction built on a face that was Cyrillic from the start.

## What could not be verified from a primary source

- Fontsource does not publish a machine-readable "typical KB on a real page" figure — the per-visit numbers above are derived by me from raw subset byte sizes plus the documented `unicode-range` mechanism, not fetched from a Fontsource-published benchmark. This is a calculation from primary data, not an unverified claim, but flagging the method distinction.
- Google Fonts' METADATA.pb files don't carry a "why no Cyrillic" rationale for the ruled-out faces (Bodoni Moda, Fraunces, Newsreader, Archivo, Space Grotesk, DM Serif Display, Abril Fatface, Unna) — only the subset list itself, which is sufficient to disqualify them per the ticket's hard filter, but I can't cite a foundry statement on *why* those cuts were never made.
- I did not attempt to render sample Cyrillic strings in each candidate to eyeball glyph quality/hinting (e.g., whether PT Serif's italic Cyrillic looks as considered as its Latin italic) — subset *presence* is verified from primary sources; subjective Cyrillic type quality is not, and would need a native-reading design review before final sign-off.
