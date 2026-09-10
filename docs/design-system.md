# Design System

What's in here: the visual language of What's on Radar — the C1 direction, the token system in `frontend/src/index.css`, the shared CSS layer in `frontend/src/components/shared/`, the type/color/shape/motion rules, the per-surface registers (consumer, organizer, admin), the light/dark theming machinery, and the design decisions that are already settled and must not be re-litigated.

Read this before touching any `.module.css`, `frontend/src/index.css`, `frontend/src/components/shared/`, `frontend/src/lib/theme.ts`, `backend/app/email/styles.py`, or any component whose change is visual rather than behavioral. Structure/routing/i18n/SEO detail lives in `docs/frontend.md`; the *rule* form of the token/shared-class imperatives lives in `CLAUDE.md` and `docs/conventions.md`.

## 1. The direction: C1 (cinematic-on-brand)

The app runs one visual language, **C1**: editorial-cinematic type over the existing navy/gold brand. Its signature is type and hairline rules doing the work, not palette novelty or decorative chrome.

Concretely, C1 means:

- **Display serif over imagery.** Cormorant Garamond at large sizes, hairline `--rule` separators between sections, gold used sparingly as an accent rather than as fill.
- **Sharp interactive corners.** Every button, input, and menu popover is `border-radius: 0`. Cards, images, and chips keep `--radius`.
- **No decorative iconography.** No pictographic emoji anywhere in the consumer or organizer surfaces (one carryover exception, `FeedbackButtonRow` — see §9). Structure and type carry meaning; a hairline is preferred over a box.
- **Imagery amplifies, never load-bearing.** Every surface must still read with photography stripped — the Landing proof section and the plate rows are both designed to survive `noimg`.

**History, so it isn't re-tried:** an alternative direction (C2 — oxblood/bone/silver palette + Playfair Display, dropping navy/gold entirely) was fully built, shipped, reviewed live at 2880×1620, and reverted: a new palette without new information architecture read stale rather than considered. C1 was then locked and migrated across every surface. A palette push is not an open question — reopening it means redoing the IA too.

## 2. Surface registers

Four registers share one token/geometry system. They differ only in type stack and imagery appetite.

| Register | Surfaces | Type | Imagery |
|---|---|---|---|
| **Landing** | `routes/Landing/` | Cormorant display at hero scale, Manrope body | Full-bleed poster, grain, scrims, plate rows |
| **Consumer app** | Feed, Explore, EventDetail, SavedEvents, Settings, auth, static/legal | Cormorant on page headings, section eyebrows, card/event titles; Manrope everywhere else | Event photography in cards/hero only |
| **Organizer portal** | `/organizer/*` | Same as consumer — deliberately a *product* surface, not an admin panel | None beyond event images |
| **Admin console** | `/admin/*` | `--font-system` (OS-native sans) + `--font-mono` for data. **Never** Cormorant, never Manrope | None, ever |

**The admin boundary rule** (state it this way for any new admin screen, rather than listing screens): admin inherits colors, spacing, hairlines, and the sharp-corner geometry, but runs its own type stack and declines all display/imagery treatment. No `--font-display`, no `--font-size-display-*`, no scrims/grain/posters. Density biases to the small end of the `--fs-*` scale; emphasis comes from `font-weight`, not a bigger scale.

Application mechanism: `--font-body` is set globally on `html` (`index.css`), so admin overrides it locally — `AdminShell.module.css`'s `.shell` sets `font-family: var(--font-system)` and cascades to every screen mounted inside it; `AdminLogin` renders *outside* `AdminShell` (see `AdminApp.tsx`) and carries its own declaration. `Page.module.css`'s `.adminPageTitle` and `AdminQueue.module.css`'s `.queueDetailTitle` are the shared admin-chrome classes that also pin `--font-system`.

## 3. Tokens

Every color, radius, shadow, z-index, transition, easing, duration, blur, spacing step, type size, tracking, leading, weight, and component-geometry value is a custom property in `:root` (`frontend/src/index.css`). **Never hardcode one in a `.module.css`** — define the token first, then `var(--token-name)`. This holds across the whole app: a grep for hex literals outside `index.css` and `Landing.module.css` returns nothing, and keeping it that way is what makes the light theme a token-swap rather than a rewrite.

Token groups, in `index.css` order: palette primitives → semantic alpha/overlay derivations → typography (families, `--fs-*`, `--tracking-*`) → spacing scale (`--space-1`…`--space-9` plus explicitly-named fractional steps) → shape → layering → opacity → border widths → transforms → grid/flex geometry → blur → image caps → per-component geometry (spinner, toggle, DatePicker, SelectField, FileField, status circle, page widths, admin rail/queue) → heading scale → leading → weight → animation durations → shadows → atmosphere (`--rule`) → category gradients → Landing/C1 display + plate tokens.

Rules that bite:

- **Naming is semantic, not locational**, unless the token is deliberately scoped. `--hair-width` names a treatment; `--font-size-display-hero` names its one consumer on purpose.
- **Hero-only tokens stay hero-only.** `--poster-frame`, `--grain`, `--scrim-vertical`, `--poster-glow-*`, `--font-size-display-hero` have exactly one consumer (`Landing.module.css`) and are documented as scoped rather than renamed. If a future surface genuinely needs one, that's a decision made against a real consumer — not a speculative generalization now.
- **Breakpoint tokens are documentation only.** CSS custom properties cannot drive `@media` conditions, so `--bp-narrow: 640px` exists to name the value; the `@media` rules themselves still carry the literal. Keep the literal and the token in sync; don't try `@media (max-width: var(--bp-narrow))`. (A `--bp-wide: 1680px` companion token existed for the Landing wide-screen hero side panel — removed along with the token once that treatment was cut from scope; see §12.)
- **Off-scale spacing is allowed but must be named.** Steps like `--space-0-42` exist because two or more call sites needed them; add a named step rather than inlining a rem literal or forcing a layout onto the wrong scale step.
- **Category gradients mirror the taxonomy.** The `--gradient-<category>` keys mirror `VALID_CATEGORIES` in `shared/app-config.json`; anything without an entry falls through `categoryGradient()` (`utils.ts`) to `--gradient-fallback`. Add a category to the taxonomy → add both theme's gradient pair.

## 4. Typography

```
--font-display: 'Cormorant Garamond', Georgia, serif;
--font-body:    'Manrope Variable', system-ui, sans-serif;   /* set on html */
--font-mono:    ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
--font-system:  -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
```

**Two hard constraints on ever adding a face:**

1. **CSP.** The SPA serves `font-src 'self'` (see `docs/backend-ops.md`), so a face must ship as an `@fontsource` npm package imported in `frontend/src/main.tsx` and bundled by Vite. No Google Fonts `<link>`, no CDN. `--font-mono` and `--font-system` are system stacks precisely because of this.
2. **Cyrillic.** `ru` is a first-class locale with its own routes and emails. A face without a `cyrillic` subset silently falls back to `system-ui` on every Russian character — this is why DM Sans was replaced by Manrope Variable (no Cyrillic cut) and why Cormorant Garamond survived (`cyrillic`, `cyrillic-ext`, `latin`, `latin-ext`, `vietnamese`). Check `node_modules/@fontsource*/<face>/metadata.json`'s `subsets` before proposing a face. Prefer the `@fontsource-variable/*` package where one exists: one file per subset covering the whole weight axis, usually cheaper than two static weights.

Bundled weights today: Manrope Variable (200–800 axis, one file), Cormorant Garamond 300/300-italic/400/400-italic/500/600.

**Where display type is allowed:** page headings (`Page.module.css`'s `.pageTitle`/`.gridHeading`, Feed's date heading, EventDetail's `h1`, Settings' title), section eyebrows, `LegalPage`'s section headings, card/event titles (`EventCard`, `PersonaCard`'s `.name`), the auth brand lockup. **Never** on a control, a form field, a data value, a meta row, or anywhere inside `/admin/*`.

**Display scale.** The C1 display sizes are `clamp()`-based tokens, not per-component inline clamps: `--font-size-display-hero`, `--font-size-display-plate`, `--font-size-display-section`, `--font-size-display-card`. `clamp()` here is load-bearing, not decorative — Estonian and Russian UI strings run ~1.6× the English (`landing_personas_title` is 52 ch ET / 51 ch RU vs ~32 EN; `landing_hero_h1` goes 42 ch EN → 60 ch ET). **Test every display heading against the Estonian and Russian strings, never the English one.** A fixed-px hero breaks; a button sized to an English label wraps in Russian. Real catalogue event titles run to 60+ characters and must be allowed two or three lines in any listing layout.

## 5. Color and theming

**Dark is the origin palette; light is a literal inversion.** The full dark palette is defined on bare `:root`. `:root[data-theme="light"]` redefines *only* the tokens that need a light value — backgrounds, text ramp, borders, success/danger (darkened for AA as text on white), card shadows (lighter, and the gold glow *stronger* since it nearly vanishes on white), the category gradients (hue and stop-2 saturation preserved, lightness relationship flipped), the poster scrim/glows, and `--bg-placeholder`/`--bg-overlay*` (inverted onto the light `--bg` rgb at the same alpha). Everything else — spacing, type scale, geometry, accent hue and all accent-alpha overlays, `--overlay-scrim` — is theme-neutral and inherited.

When adding a token: if it encodes a color that reads differently on a near-white ground, it needs a light-block value. If it's an alpha overlay of the accent, it usually doesn't. Never define a color *only* inside the light block.

**Resolution order** (`frontend/src/lib/theme.ts`, `resolveTheme` — pure, unit-tested): account preference → `localStorage` (`theme_preference`) → OS `prefers-color-scheme`. The resolved value is binary (`light`/`dark`) and lands on `document.documentElement.dataset.theme`; the stored *preference* is tri-state (`system`/`light`/`dark`).

- An inline script in `frontend/index.html` re-resolves this synchronously before first paint to avoid a flash of the wrong theme. It **duplicates** `resolveTheme`'s logic (it must run with zero module loading) — the two must never disagree, and the storage-key literal there must stay in sync with `THEME_PREFERENCE_KEY` in `constants.ts`.
- `lib/theme.ts` is imported for side effects in `main.tsx`: it listens for cross-tab `storage` writes and for OS theme flips (the latter only while the preference is `system` — an explicit override must not be disturbed).
- `syncAccountTheme()` is the shared post-verify policy for both auth tracks: an existing account preference wins and is mirrored locally; otherwise an explicit local override seeds the account. Each track passes its own PATCH so consumer and organizer state stay independent.
- UI: `ThemeSelector` (consumer + organizer top bars, `useThemePreference`), `AdminThemeToggle` in the admin rail.

**Email theming.** Emails can't read a media query reliably, so `backend/app/email/styles.py::get_email_styles(theme_preference)` returns a `DARK_STYLES`/`LIGHT_STYLES` bundle keyed on the recipient's stored preference — **light is the default**; only an explicit `dark` preference gets the dark bundle. Structural (non-color) email styling is shared between the two. Presentation stays split three ways per the repo rule: CSS in `styles.py`, markup in `templates.py`, assembly in the delivery module.

## 6. Shape

- **Interactive controls are square.** `border-radius: 0` is baked into the shared base classes — `Button.module.css`'s `.btnPrimary`/`.btnOutline`, `Field.module.css`'s `.fieldInput`/`.fieldWrap`, `Menu.module.css`'s popover/trigger chrome, `Bar.module.css`'s nav links. It is *not* an opt-in variant class; there is no `buttonSharp`/`fieldSharp`/`menuSharp` to compose (an earlier plan proposed those, then the treatment was made universal in the base classes instead — don't reintroduce the variants). Components that render a bordered control outside those bases (`SegmentedControl`, `SelectField`, `DatePicker`, `DateRangeMenu`, `FileField`, `VenuePicker`, `RichTextEditor`, `Modal`, `MobileMenu`, `Chip`, `EventOverflowMenu`, `FeedbackButtonRow`) carry their own `border-radius: 0`.
- **Containers are not.** `--radius` is untouched on cards, images, and chips-as-meta. `.card` keeps its rounding; a card row in the organizer dashboard is a card, not a control.
- **Hairlines, not boxes.** `--rule` (`1px solid var(--border-subtle)`) separates sections; `--hair-width` sizes the plate/empty-state hairline. Reach for a rule before a border or a background change.

## 7. The shared CSS layer

`frontend/src/components/shared/` holds 16 pure-CSS modules plus one component folder, `GoogleSignInButton/` (`.tsx` + `GoogleGMark.tsx` + test) — the one exception to the CSS-only rule. Consume the CSS modules with CSS Modules `composes:`; **never copy-paste** their rules into a route or component stylesheet. Component CSS composes from `'../shared/X.module.css'`, route CSS from `'../../components/shared/X.module.css'`.

| Module | Holds |
|---|---|
| `Page.module.css` | Page shells (`.page`, `.pageCentered`, `.pageMain`, `.pageTitle`, `.proseBody`), the Explore/SavedEvents grid shell (`.gridMain`, `.gridMasthead`, `.gridHeading`, `.cardGrid`), admin route-header chrome (`.adminEyebrow`, `.adminPageTitle`) |
| `Card.module.css` | `.card`, `.cardAccentTop`, `.cardDangerTop`, `.cardPage`, plus the auth shell (`.authCard`, `.authHeader`, `.authRadar`, `.authBrand`) |
| `Button.module.css` | `.btnPrimary`, `.btnOutline`, `.btnSubmit`, `.textButton`, `.iconAction`, `.successBlock` |
| `Field.module.css` | `.fieldLabel`, `.fieldInput`, `.fieldWrap` (chrome-only outer box for composite controls) |
| `Menu.module.css` | Popover/trigger chrome for `FacetMenu`, `SelectMenu`, `MobileMenu`, `DatePicker`, `SelectField` |
| `Bar.module.css` | Top-bar chrome shared by `TopBar` and `OrganizerTopBar` |
| `Animations.module.css` | Keyframes + classes — see §8 |
| `AdminQueue.module.css` | Admin queue row/detail typography, resolved panel |
| `Alert`, `Chip`, `Link`, `Media`, `Spinner`, `StatusCircle`, `Visually`, `DesktopGate` | Inline alert, chip pill, accent link, image backdrop, spinner rings, status circles, sr-only/offscreen utilities, the admin desktop-only gate |

Add a new shared pattern here rather than growing a second copy. New variants follow base-class + modifier (`.card` / `.cardAccentTop`) — **never restyle a base class in place** to suit one consumer.

**A note on Landing:** `Landing.module.css` is the least shared-dependent stylesheet (it composes `Page`, `Alert`, `Spinner`, `StatusCircle`, `Animations`, `Media` and re-rolls the hero/ticker/plate/proof/footer chrome locally). That is deliberate — its hero treatment has no second consumer. Don't "fix" it by hoisting hero CSS into `shared/`.

**One exception to "never copy-paste":** `composes:` resolves to a class-name string at build time, so it cannot be scoped inside a `@media` block — a shared rule that must apply only above/below a breakpoint has to be restated locally rather than composed. `Feed.module.css`'s media-scoped `.srOnly` override is the one live instance (`Visually.module.css`'s own `.srOnly` is unconditional); keep any such restatement in sync with the shared rule it mirrors.

## 8. Motion

App-wide vocabulary in `Animations.module.css`: `.spin`, `.breathe`, `.rise`, `.fadeIn`, `.fadeInScale`, tuned per call site via `--spin-duration`/`--breathe-duration`/`--rise-duration`/`--rise-distance` custom properties. `.rise` uses `animation-fill-mode: backwards`, **not `both`** — holding the end transform leaves a non-`none` computed transform forever, which makes the element a containing block for any `position: fixed` descendant and breaks popover positioning (`EventOverflowMenu`'s mobile popover). Don't "improve" it to `forwards`/`both`.

Landing/C1 vocabulary, in the same file but Landing-exclusive: `heroRise` (masked headline lines translating up, staggered via `--hero-rise-delay`), `hairlineDraw` (a rule scaling in from zero width), `posterDrift` (26s slow scale/pan on the hero poster), `tickerSlide` (linear marquee). All four collapse to `animation: none` under `prefers-reduced-motion: reduce`. They live sitewide rather than inside `Landing.module.css` so a future surface reusing the poster/ticker treatment needn't re-prefix them.

`--easing` is the app curve; `--easing-landing` is C1's single motion curve; `--easing-breathe` is the looping pulse. Two constraints on any new motion: it must collapse under reduced motion, and it must complete (or be irrelevant) within the prerender gate's wait — `frontend/scripts/prerender.ts` snapshots Landing, `/explore`, and every event page with Playwright, so a scroll-gated reveal that never fires headlessly ships as invisible content.

## 9. Component-level rules

- **`EventCard` has exactly two variants: `standard` and `featured`.** An `editorial` split-row plate variant was specced and built twice (Explore, SavedEvents) and reverted both times on product review against the standard grid. The variant and its shared plate CSS do not exist. Landing's `.plate` showcase rows are Landing-local and unrelated. Don't add a third variant without a live visual review first.
- **`EmptyState` has no icon.** Its shape is: optional small-caps eyebrow (an existing i18n string reused from the route — not new copy) → `--rule` hairline → Cormorant title → Manrope message → optional hint, **left-aligned**, matching the flat-proof-section rhythm. There is no `icon` prop.
- **`PageState` stays centered.** A viewport-centered spinner is the conventional pattern for a transient full-page load, not a "centered everything" tell. It is deliberately untouched by the C1 pass.
- **No pictographic emoji in consumer or organizer UI.** `PersonaCard` renders no emoji (its `.name` is the visual anchor, with a hairline to `.vibe`); Settings' persona summary is text only. `shared/personas.json` still carries the `emoji` field as data — it is simply not rendered. Unicode *status* marks (`✓ ✕ ⚠ ☰`) are functional glyphs, not iconography, and are allowed on every surface (`AuthCard`, `MagicLinkForm`, `Modal`, `MobileMenu`, `Landing`/`Contact` success checks, and the admin console's run/queue status marks all use them). **One live exception:** `FeedbackButtonRow` still renders `👍 👎 🔖` (`SIGNAL_CONFIG` in `frontend/src/constants.ts`) on `EventCard` and `EventDetail` — a pre-C1 carryover that the migration never replaced. It is the only pictographic emoji shipping in consumer UI; don't add a second, and treat replacing it as open work rather than as a counter-example to the rule.
- **`RichTextEditor`'s toolbar icons are functional controls, not iconography.** Its bold/italic/underline/list/link/quote glyphs are local inline SVGs (`RichTextEditor/icons.tsx`), not an icon library and not emoji — a toolbar button has no text label that could carry the meaning instead. This does not open the door to icons elsewhere; every other surface still uses type and hairlines.
- **Two top bars stay separate.** `OrganizerTopBar` does not converge on `TopBar`: `TopBar`'s nav/auth links are hardcoded to consumer routes, and each renders its own `<header>`/`<nav>` markup. They share `Bar.module.css`, `LocaleSelector`, and — since the organizer mobile burger menu shipped — `MobileMenu` itself, parameterized via its `navItems`/`navAriaLabelKey` props so each top bar passes its own link set (`NAV_ITEMS` vs `ORGANIZER_NAV_ITEMS`). Extracting a prop-driven base *header* component to save ~15 lines of JSX still costs more indirection than it returns; that's the part of the merge that stays rejected.
- **`OrganizerDashboard` stays a row-list**, on consumer-register typography (Cormorant heading, Manrope body) — not admin's sub-language, not Explore's grid. That line is what keeps the portal a self-service product surface.
- **The organizer submit/edit form keeps its original structure** — content-language segmented control, stacked labeled fields, two-column date/price rows, `VenuePicker`/`SelectField`/`FileField`. A plate-anatomy rebuild (numbered plates, eyebrow labels, hairline-separated field rows) was prototyped and rejected. Cormorant heading over Manrope-with-sharp-corners fields is the *intended* contrast, not an inconsistency to resolve.
- **`EventDetail` is reskinned, never restructured.** Full-width hero, sharp-corner controls, Cormorant title. It's the most-linked, SEO-critical, prerender-gated page: the lowest-risk change is the smallest structural diff.
- **Static/legal is the editorial surface.** `LegalPage` section headings are Cormorant, each `.section` carries a `--rule` hairline above it so a legal document reads as a sequence of blocks rather than one text wall. Body copy stays Manrope.

## 10. Layout and breakpoints

- One named breakpoint: **640px** (mobile, the only one that recurs — 15+ stylesheets), tokenized as `--bp-narrow` but written as a literal in `@media` rules; see §3. A handful of one-off unnamed breakpoints exist where 640px didn't fit the layout: **560px** (`Onboarding`), **641px** (`Landing`, the `min-width` complement to its own 640px `max-width` rule), **900px** (`Landing`), and **1024px** (`DesktopGate`, the admin desktop gate).
- Page widths are tokenized per surface (`--page-max-narrow`/`-legal`/`-medium`/`-grid`/`-wide`/`-feed`/`-organizer`/`-settings`/`-showcase`). Pick an existing one before adding another.
- The browse grid is `Page.module.css`'s `.cardGrid` — `repeat(auto-fill, minmax(var(--card-grid-min), 1fr))`, collapsing to one column at 640px. Explore and SavedEvents both compose it; Feed deliberately does *not* (a lead `featured` card plus a list — five curated picks is a different problem from an unbounded browse list, and converging the two would flatten the curated-vs-browse distinction).
- Admin geometry has its own tokens (`--admin-rail-width`, `--admin-queue-list-width`, `--admin-tile-min`, `--admin-trigger-min`, …) and its own desktop gate (`DesktopGate.module.css`).

## 11. Landing structure

Section order, locked:

1. **Hero** — full-bleed poster with `--grain` overlay and `--scrim-vertical` for legibility, a `--poster-frame` gold hairline inset (hero-only, never repeated), dateline + live counts strip pinned top, headline + subcopy + email capture pinned bottom, plus a split-rail browse CTA.
2. **Ticker** — single-line "tonight" marquee of time-stamped titles (`tickerSlide`), paused under reduced motion.
3. **Showcase plates** — split-panel rows: a fixed-height image panel (`--plate-media-min-height`, compact variant on mobile) filled with `object-fit: cover`, text column beside it, alternating sides (`.plate`/`.plateFlip`), a `--hair-width` gold hairline, meta row beneath. A cover-filled fixed panel is ratio-proof by construction — that is the whole point of the shape. An earlier full-bleed treatment that fit posters into a viewport-shaped box needed a blurred backdrop, an edge mask, and a lateral scrim to disguise letterboxing, and three rounds of tuning those constants failed; the structural fix replaced them.
4. **Flat proof section** — how-it-works steps plus a stat row, designed to read with imagery stripped.
5. **Organizer CTA** — one row: headline, one line, outlined button.
6. **Footer** — trust line (no password / no tracking / free), locale list, year.

**Landing copy must be honest about the catalogue.** Numbers on the page come from the live counts endpoint (`app/routers/public.py`), never hardcoded. Settled rules:

- Show **upcoming** published events, not all-time — and round it ("over 1,000 events") so daily attrition doesn't force copy edits.
- Venue counts are **published-scoped**. An unscoped `count(distinct venue_name)` across all statuses is roughly 50% higher and is wrong for the page.
- "Tonight" is genuinely volatile and can be zero — a real empty-tonight is a valid, non-error state, and the endpoint widens to a fallback window rather than rendering an empty ticker.
- Do **not** ship: any "N new events every week" throughput claim (the data can't support it honestly), the price ceiling (quote only "tickets from €1"), or the thin category tail by name.
- Safe permanent copy: five picks every morning at six, digest at seven, hourly source re-reads, three locales, 14 categories.

## 12. Settled — do not re-litigate

| Decision | Status |
|---|---|
| Palette push (new accent/ground, dropping navy/gold) | Built, shipped, reverted after live review. Closed. |
| `EventCard` `editorial`/plate variant | Built twice, reverted twice. The variant does not exist. |
| `buttonSharp`/`fieldSharp`/`menuSharp` opt-in variants | Superseded — sharp corners are universal in the base classes. |
| `Landing` retrofitted onto shared plate classes | Deliberately not done; its hero CSS stays local. |
| `OrganizerTopBar` merged into `TopBar` | Rejected — indirection cost exceeds the saving. |
| Organizer form rebuilt on plate anatomy | Prototyped, rejected. |
| Cormorant anywhere in `/admin/*` | Removed, unqualified — no logotype exception. |
| `--radius: 0` sitewide (containers too) | Rejected — controls only. |
| Emoji as iconography | Removed from consumer/organizer surfaces; admin status glyphs stay. |
| Landing wide-screen hero side panel | Specced, never implemented, removed from scope. |
| Third-party identity-provider brand marks (class exception) | The full-colour Google "G" mark is pictographic iconography, which §1/§9 forbid, and per Google's branding guidelines it may not be made monochrome, redrawn, or dropped. Recorded as a **class** exception — third-party identity-provider brand marks, mandated by that provider's published branding terms, rendered as a local inline SVG (never `<img>` — the current asset is a masked conic-gradient + Gaussian-blur composition that silently loses layers through an `<img>` reference), scoped to the sign-in surface only. Does not reopen §9's general no-iconography rule elsewhere. The button itself ships `border-radius: 0` (composed from the shared `Button` module, unmodified) — Google's written guidelines state no minimum size and no corner radius, so this is a defensible reading against the prose, not a violation, even though it visibly departs from Google's own shipped assets. See `docs/adr/0002-google-sign-in-oauth-pkce.md`. |

## 13. Working checklist for a visual change

1. Read the token list in `index.css` before writing any value. If the value you need isn't there, add the token first.
2. Check `components/shared/` for an existing base class before writing chrome. Compose; don't copy.
3. If it's a color, decide whether it needs a `:root[data-theme="light"]` value.
4. Test the layout against the **Estonian and Russian** strings, not English.
5. Verify with imagery stripped, and under `prefers-reduced-motion: reduce`.
6. Verify visually before landing — a CSS retrofit that reads correct in the diff can still look wrong on screen. Ticket wording is not proof.
7. Run `npm run lint` and `npm run type-check` (house rules; CI does not enforce them).
