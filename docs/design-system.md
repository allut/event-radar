# Design System

What's in here: the visual language of Event Radar — the C1 direction, the token system in `frontend/src/index.css`, the shared CSS layer in `frontend/src/components/shared/`, the type/color/shape/motion rules, the per-surface registers (consumer, organizer, admin), the light/dark theming machinery, and the design decisions that are already settled and must not be re-litigated.

Read this before touching any `.module.css`, `frontend/src/index.css`, `frontend/src/components/shared/`, `frontend/src/lib/theme.ts`, `backend/app/email/styles.py`, or any component whose change is visual rather than behavioral. Structure/routing/i18n/SEO detail lives in `docs/frontend.md`; the *rule* form of the token/shared-class imperatives lives in `CLAUDE.md` and `docs/conventions.md`.

## 1. The direction: C1 (cinematic-on-brand)

The app runs one visual language, **C1**: editorial-cinematic type over the existing navy/gold brand. Its signature is type and hairline rules doing the work, not palette novelty or decorative chrome.

Concretely, C1 means:

- **Display serif over imagery.** Cormorant Garamond at large sizes, hairline `--rule` separators between sections, gold used sparingly as an accent rather than as fill.
- **Sharp interactive corners.** Every button, input, and menu popover is `border-radius: 0`. Cards, images, and chips keep `--radius`.
- **No decorative iconography.** No pictographic emoji anywhere in the consumer or organizer surfaces (one carryover exception — the `👍 👎 🔖` signal glyphs in `FeedbackButtonRow` and the Saved page tabs — see §9). Structure and type carry meaning; a hairline is preferred over a box.
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

The top bar's tokens (`--bar-h`, `--bar-h-condensed`, `--bar-h-phone`, `--bar-h-phone-condensed`, `--bar-mark`, `--bar-mark-condensed`, `--bar-control-h`, `--bar-search-w`, `--bar-nav-gap`, `--bar-rule-w`, `--fs-bar-word`, `--fs-bar-word-condensed`, `--fs-bar-kicker`, `--fs-drawer-nav`, `--bar-transition`) sit at the end of the geometry block, and `--accent-ink` is gold-as-text (dark value in `:root`, `#8f6316` in the light block). `--topbar-height` and `--topbar-height-mobile` are retired — nothing reads them.

Token groups, in `index.css` order: palette primitives → semantic alpha/overlay derivations → typography (families, `--fs-*`, `--tracking-*`) → spacing scale (`--space-1`…`--space-9` plus explicitly-named fractional steps) → shape → layering → opacity → border widths → transforms → grid/flex geometry → blur → image caps → per-component geometry (spinner, toggle, DatePicker, SelectField, FileField, status circle, page widths, admin rail/queue) → heading scale → leading → weight → animation durations → shadows → atmosphere (`--rule`) → category gradients → Landing/C1 display + plate tokens.

Rules that bite:

- **Naming is semantic, not locational**, unless the token is deliberately scoped. `--hair-width` names a treatment; `--font-size-display-hero` names its one consumer on purpose.
- **Hero-only tokens stay hero-only.** `--poster-frame`, `--grain`, `--scrim-vertical`, `--poster-glow-*`, `--font-size-display-hero` have exactly one consumer (`Landing.module.css`) and are documented as scoped rather than renamed. If a future surface genuinely needs one, that's a decision made against a real consumer — not a speculative generalization now.
- **Breakpoint tokens are documentation only.** CSS custom properties cannot drive `@media` conditions, so `--bp-narrow: 640px` exists to name the value (with three single-consumer siblings in the same role — `--bp-desktop-gate: 1024px`, `--bp-landing-stats: 900px`, `--bp-onboarding-narrow: 560px`); the `@media` rules themselves still carry the literal. Keep the literal and the token in sync; don't try `@media (max-width: var(--bp-narrow))`. The wide band adds one `min-width` sibling in the same role, `--bp-wide: 2000px` (see §10). (An earlier `--bp-wide: 1680px` existed for the never-built Landing hero side panel and was removed with it; the name now means the 2000px wide-band floor.)
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

**Where display type is allowed:** page headings (`Page.module.css`'s `.pageTitle`/`.gridHeading`, Feed's date heading, EventDetail's `h1`, Settings' title), section eyebrows, `LegalPage`'s section headings, the FAQ page's question rows (a `<summary>` whose text is the question heading) and closing heading, card/event titles (`EventCard`, `PersonaCard`'s `.name`), the auth brand lockup. **Never** on a control, a form field, a data value, a meta row, or anywhere inside `/admin/*`.

**Display scale.** The C1 display sizes are `clamp()`-based tokens, not per-component inline clamps: `--font-size-display-hero`, `--font-size-display-plate`, `--font-size-display-section`, `--font-size-display-card`, `--font-size-display-mark`, `--font-size-display-legal`. `clamp()` here is load-bearing, not decorative — Estonian and Russian UI strings run ~1.6× the English (`landing_personas_title` is 52 ch ET / 51 ch RU vs ~32 EN; `landing_hero_h1` goes 42 ch EN → 60 ch ET). **Test every display heading against the Estonian and Russian strings, never the English one.** A fixed-px hero breaks; a button sized to an English label wraps in Russian. Real catalogue event titles run to 60+ characters and must be allowed two or three lines in any listing layout.

**Display tokens must grow under browser zoom (WCAG 1.4.4, #465).** Zoom shrinks the CSS viewport, so the `vw` term shrinks by as much as zoom enlarges it — inside the fluid range a display size doesn't grow at all, only once it hits its lower bound. Two rules, both drift-guarded by `frontend/src/displayTokens.test.ts`:

- **Bounds in `rem`, `max ÷ min ≤ 1.5`.** At zoom *z* every token renders at least *z* × its min, so 1.5 guarantees 2× its 100% size by 300% zoom (Safari's cap) at every window width. The common "≤ 2.5" rule only promises 2× by 500%, which Safari never reaches. A rem *intercept* doesn't help — rem and px scale identically under zoom — the ratio is the lever. `rem` bounds also make the token follow the user's browser default font size (`html { font-size: 100% }`, not a px pin).
- **Never resize a display-token selector inside `@media`.** A zoomed desktop window crosses the 640px breakpoint: the Landing hero's old `≤640 { font-size: --heading-xl }` override made it *shrink* to 0.74× at 200% on a 1280 window. Let the token's own clamp floor do the mobile sizing.

The cost is a narrower range: the hero runs 64px on phones → 96px on desktop (it was 34 → 96), so the phone Landing hero is taller. Budget for that when adding a display token, and check the phone layout in ET and RU at 375px. When the taller type pushes a call to action off the screen, change the layout, not the type size. On phones (≤640px), Landing reorders its hero to put the capture first (#498): `.heroTop` and `.heroBot` become `display: contents`, and flex `order` moves the sub and the counter (restyled as a one-line ledger) below the capture bar. This keeps the email input above the fold at 375×667. The default font size also stretches the layout: at 24px on a 320px phone, the controls and long words must wrap, not overflow.

## 5. Color and theming

**Dark is the origin palette; light is a literal inversion.** The full dark palette is defined on bare `:root`. `:root[data-theme="light"]` redefines *only* the tokens that need a light value — backgrounds, text ramp, borders, success/danger (darkened for AA as text on white), card shadows (lighter, and the gold glow *stronger* since it nearly vanishes on white), the category gradients (hue and stop-2 saturation preserved, lightness relationship flipped), the poster scrim/glows, and `--bg-placeholder`/`--bg-overlay*` (inverted onto the light `--bg` rgb at the same alpha). Everything else — spacing, type scale, geometry, accent hue and all accent-alpha overlays, `--overlay-scrim` — is theme-neutral and inherited.

When adding a token: if it encodes a color that reads differently on a near-white ground, it needs a light-block value. If it's an alpha overlay of the accent, it usually doesn't. Never define a color *only* inside the light block.

**Resolution order** (`frontend/src/lib/theme.ts`, `resolveTheme` — pure, unit-tested): the **device theme** (OS `prefers-color-scheme`) is the default state; a **theme override**, held in `localStorage` (`theme_override` + `theme_override_device`, the device theme it was chosen under), wins only while its recorded device theme still matches the current one — a mismatch means the device flipped since, so the override expired and the device theme wins again (ADR 0003). The resolved value is always binary (`light`/`dark`) and lands on `document.documentElement.dataset.theme`. There is no third, "System" state to store — device-following is what a viewer falls back to, not a chosen value.

- An inline script in `frontend/index.html` re-resolves this synchronously before first paint to avoid a flash of the wrong theme. It **duplicates** `resolveTheme`'s logic (it must run with zero module loading) — the two must never disagree, and the storage-key literals there must stay in sync with `THEME_OVERRIDE_KEY`/`THEME_OVERRIDE_DEVICE_KEY` in `constants.ts`. It also unconditionally wipes the legacy `theme_preference` key (the pre-ADR-0003 permanent tri-state preference) rather than reading it. This script's body is pinned by a `sha256-…` CSP hash in `frontend/public/_headers` (theme-revert-on-refresh fix) — editing the body means regenerating and updating that hash (`docs/security.md`'s CSP paragraph has the exact steps and the drift-guard test), or production silently falls back to the runtime `applyTheme()` self-heal below with a flash of the wrong theme on every load.
- `lib/theme.ts` is imported in `main.tsx` for its `storage`/OS-theme-flip listeners **and** its `applyTheme()` is called directly at boot, immediately before `createRoot(...).render(...)`. This re-resolves from localStorage/OS and re-applies on every load — a deliberate self-heal in case the pre-paint script above is ever blocked (a CSP regression) or a prerendered snapshot shipped a baked-in `data-theme` (see the prerender bullet below): the wrong theme corrects itself the moment JS runs instead of persisting for the whole session. The OS `prefers-color-scheme` listener unconditionally re-resolves on every flip — there's no "System" mode to gate it on any more, so any live override is discarded the moment the device theme changes.
- Prerendered snapshots (`frontend/scripts/prerender.ts`) are theme-neutral: `stripBakedThemeAttr` removes any `data-theme` the build browser baked onto `<html>` before every snapshot write, so a snapshot never ships a frozen copy of the build machine's own OS theme. See `docs/frontend.md`'s prerender section.
- The override is scoped to the browser only, never an account (ADR 0003) — signing in on either track (magic link or Google) neither reads a theme from the account nor writes one to it.
- UI: the `PrefsMenu` theme row (consumer + organizer top bars and the phone drawer, `useResolvedTheme`), `AdminThemeToggle` in the admin rail — both offer exactly two options, Light and Dark. The `PrefsMenu` trigger glyph is a fixed half-filled circle that never reflects the current theme, so the prerendered HTML can't show the wrong one.

**Email theming.** `backend/app/email/styles.py::get_email_styles()` returns the one bundle every email renders from (ADR 0003) — there's no per-recipient theme column to key off, since a stored theme can't track a device that changes after the mail is sent:

| bundle | declared `color-scheme` | dark override CSS |
|---|---|---|
| `EMAIL_STYLES` | `light dark` | yes |

`EMAIL_STYLES` is the light palette as its base (so a client that strips `<style>` still gets a readable, intentional render) plus a `@media (prefers-color-scheme:dark)` override block (`_THEME_CLASS_RULES` in `styles.py`, driving `e-*` class hooks in `templates.py`) that repaints it dark for a client honoring OS theme. It declares its scheme via `<meta name="color-scheme">`/`<meta name="supported-color-schemes">` on `EMAIL_DOCUMENT` — without it, a client (notably Apple Mail) may apply its own undeclared dark-mode inversion, which can disagree with the palette actually rendered (e.g. inverting an already-dark email to a washed-out, contrast-broken "light" render). Presentation stays split three ways per the repo rule: CSS in `styles.py`, markup in `templates.py`, assembly in the delivery module.

## 6. Shape

- **Interactive controls are square.** `border-radius: 0` is baked into the shared base classes — `Button.module.css`'s `.btnPrimary`/`.btnOutline`, `Field.module.css`'s `.fieldInput`/`.fieldWrap`, `Menu.module.css`'s popover/trigger chrome, `Bar.module.css`'s nav links. It is *not* an opt-in variant class; there is no `buttonSharp`/`fieldSharp`/`menuSharp` to compose (an earlier plan proposed those, then the treatment was made universal in the base classes instead — don't reintroduce the variants). Components that render a bordered control outside those bases (`SegmentedControl`, `SelectField`, `DatePicker`, `DateRangeMenu`, `FileField`, `VenuePicker`, `RichTextEditor`, `Modal`, `MobileMenu`, `Chip`, `EventOverflowMenu`, `FeedbackButtonRow`) carry their own `border-radius: 0`. `VenuePicker`'s `.miniForm` panel is the exception inside that folder: it is a container holding controls, so it keeps `--radius`.
- **Containers are not.** `--radius` is untouched on cards, images, and chips-as-meta. `.card` keeps its rounding; a card row in the organizer dashboard is a card, not a control. Bordered sub-panels inside a form (the EventSubmit content-language group, the VenuePicker mini-form, the ClaimEventEdit locked panel) are containers too and take `--radius`. Organizer status badges and tags are square; the "chips-as-meta keep `--radius`" wording applies to consumer meta chips only.
- **Hairlines, not boxes.** `--rule` (`1px solid var(--border-subtle)`) separates sections; `--hair-width` sizes the plate/empty-state hairline. Reach for a rule before a border or a background change.

## 7. The shared CSS layer

`frontend/src/components/shared/` holds 19 pure-CSS modules plus one component folder, `GoogleSignInButton/` (`.tsx` + `GoogleGMark.tsx` + test) — the one exception to the CSS-only rule. Consume the CSS modules with CSS Modules `composes:`; **never copy-paste** their rules into a route or component stylesheet. Component CSS composes from `'../shared/X.module.css'`, route CSS from `'../../components/shared/X.module.css'`.

| Module | Holds |
|---|---|
| `Page.module.css` | Page shells (`.page`, `.pageCentered`, `.pageMain`, `.pageMainNarrow`, `.pageTitle`, `.proseBody`, `.pageHint`), the Explore/SavedEvents grid shell (`.gridMain`, `.gridMasthead`, `.gridHeading`, `.cardGrid`), admin route-header chrome (`.adminEyebrow`, `.adminPageTitle`) |
| `Card.module.css` | `.card`, `.cardAccentTop`, `.cardDangerTop`, `.cardPage`, plus the auth shell (`.authCard`, `.authHeader`, `.authRadar`, `.authBrand`) |
| `Button.module.css` | `.btnPrimary`, `.btnOutline`, `.btnSubmit`, `.textButton`, `.iconAction`, `.successBlock` |
| `Field.module.css` | `.fieldLabel`, `.fieldInput`, `.fieldWrap` (chrome-only outer box for composite controls) |
| `Menu.module.css` | Popover/trigger chrome for `FacetMenu`, `SelectMenu`, `DateRangeMenu`, `MobileMenu`, `DatePicker`, `SelectField`, including the equal-width option list (`.menuValue`, `.menuOptionList`, `.menuOptionRow`, `.menuOptionActive`) |
| `Bar.module.css` | Top-bar layer (direction A · Programme) shared by `TopBar`, `OrganizerTopBar` and the bar sub-components `BarLogo`, `BarNav`, `PulseChip`, `BarSearch`, `AccountMenu`, `PrefsMenu` (bar, condense/transparent states, nav + gold active rule, square outline controls, popovers, joined `.seg` rows, phone/wide visibility). `DialMark/` owns its own module, sized by `--dial-size`/`--dial-color` which the bar sets. `MobileMenu.module.css` is the phone drawer. Every bar/drawer link sets its own `:hover` colour (index.css's global `a:hover` gold would otherwise outrank single-class link colours) |
| `Animations.module.css` | Keyframes + classes — see §8 |
| `AdminQueue.module.css` | Admin queue row/detail typography, resolved panel |
| `Calendar.module.css` | Calendar grid chrome (`.calHead`, `.calNavBtn`, `.calMonthLabel`, `.calWeekdays`, `.calGrid`, `.calDay`, plus the day states `.calSpill`, `.calToday`, `.calSelected`) shared by `DatePicker` and `DateRangeMenu` |
| `Settings.module.css` | Settings-page shell (`.settingsMain`, section/toggle-row/repick-button chrome) shared by `Settings` and `OrganizerSettings` |
| `Prose.module.css` | Typography for sanitized-HTML bodies (`.prose` — paragraph/list/strong/heading/blockquote rules every render surface agrees on), composed by `EventDetail`'s `.description` and `AdminEventDetail`'s `.proseHtml`. `RichTextEditor`'s editing surface keeps its own margin model and does not compose it |
| `Alert` (`.alert`, `.alertAccent` for non-error callouts), `Chip`, `Link`, `Media`, `Spinner`, `StatusCircle`, `Visually`, `DesktopGate` | Inline alert, chip pill, accent link, image backdrop, spinner rings + full-page overlay scrim, status circles, sr-only/offscreen utilities, the admin desktop-only gate |

Add a new shared pattern here rather than growing a second copy. New variants follow base-class + modifier (`.card` / `.cardAccentTop`) — **never restyle a base class in place** to suit one consumer.

**A note on Landing:** `Landing.module.css` is the least shared-dependent stylesheet (it composes `Page`, `Card`, `Alert`, `Spinner`, `StatusCircle`, `Animations`, `Media` and re-rolls the hero/ticker/plate/proof/footer chrome locally). That is deliberate — its hero treatment has no second consumer. Don't "fix" it by hoisting hero CSS into `shared/`.

**One exception to "never copy-paste":** `composes:` resolves to a class-name string at build time, so it cannot be scoped inside a `@media` block — a shared rule that must apply only above/below a breakpoint has to be restated locally rather than composed. `Feed.module.css`'s media-scoped `.srOnly` override is the one live instance (`Visually.module.css`'s own `.srOnly` is unconditional); keep any such restatement in sync with the shared rule it mirrors.

## 8. Motion

App-wide vocabulary in `Animations.module.css`: `.spin`, `.breathe`, `.rise`, `.fadeIn`, `.fadeInScale`, tuned per call site via `--spin-duration`/`--breathe-duration`/`--rise-duration`/`--rise-distance` custom properties. `.rise` uses `animation-fill-mode: backwards`, **not `both`** — holding the end transform leaves a non-`none` computed transform forever, which makes the element a containing block for any `position: fixed` descendant and breaks popover positioning (`EventOverflowMenu`'s mobile popover). Don't "improve" it to `forwards`/`both`.

Landing/C1 vocabulary, in the same file but Landing-exclusive: `heroRise` (masked headline lines translating up, staggered via `--hero-rise-delay`), `hairlineDraw` (a rule scaling in from zero width), `posterDrift` (26s slow scale/pan on the hero poster), `tickerSlide` (linear marquee). All four collapse to `animation: none` under `prefers-reduced-motion: reduce`. They live sitewide rather than inside `Landing.module.css` so a future surface reusing the poster/ticker treatment needn't re-prefix them.

`--easing` is the app curve; `--easing-landing` is C1's single motion curve; `--easing-breathe` is the looping pulse. Two constraints on any new motion: it must collapse under reduced motion, and it must complete (or be irrelevant) within the prerender gate's wait — `frontend/scripts/prerender.ts` snapshots Landing, `/explore`, and every event page with Playwright, so a scroll-gated reveal that never fires headlessly ships as invisible content.

## 9. Component-level rules

- **`EventCard` has exactly two variants: `standard` and `featured`.** An `editorial` split-row plate variant was specced and built twice (Explore, SavedEvents) and reverted both times on product review against the standard grid. The variant and its shared plate CSS do not exist. Landing's `.plate` showcase rows are Landing-local and unrelated. Don't add a third variant without a live visual review first.
- **`EmptyState` has no icon.** Its shape is: optional small-caps eyebrow (an existing i18n string reused from the route — not new copy) → `--rule` hairline → Cormorant title → Manrope message → optional hint, **left-aligned**, matching the flat-proof-section rhythm. There is no `icon` prop.
- **`PageState` stays centered.** A viewport-centered spinner is the conventional pattern for a transient full-page load, not a "centered everything" tell. It is deliberately untouched by the C1 pass.
- **No pictographic emoji in consumer or organizer UI.** `PersonaCard` renders no emoji (its `.name` is the visual anchor, with a hairline to `.vibe`); Settings' persona summary is text only. `shared/personas.json` still carries the `emoji` field as data — it is simply not rendered. Unicode *status* marks (`✓ ✕ ⚠ ☰`) are functional glyphs, not iconography, and are allowed on every surface (`AuthCard`, `MagicLinkForm`, `Modal`, `MobileMenu`, `Landing`/`Contact` success checks, and the admin console's run/queue status marks all use them). **One live exception:** `FeedbackButtonRow` still renders `👍 👎 🔖` (`SIGNAL_CONFIG` in `frontend/src/constants.ts`) on `EventCard` and `EventDetail` — a pre-C1 carryover that the migration never replaced. The same three glyphs also prefix the Saved page's `SegmentedControl` tabs (`SavedEvents.tsx`, via `SIGNAL_CONFIG`): kept deliberately (audit 2026-09-29, owner decision) so the tab reads as the same signal as the button that saved the event. They are one exception — the signal glyph set — used in two places; don't add a second set, and treat replacing them as open work rather than as a counter-example to the rule.
- **`RichTextEditor`'s toolbar icons are functional controls, not iconography.** Its bold/italic/underline/list/link/quote glyphs are local inline SVGs (`RichTextEditor/icons.tsx`), not an icon library and not emoji — a toolbar button has no text label that could carry the meaning instead. This does not open the door to icons elsewhere; every other surface still uses type and hairlines.
- **Other small inline SVGs are documented functional exceptions (audit 2026-09-29).** The `Footer` social-link marks (Instagram/Facebook/X — brand marks for label-less link targets), the `EventOverflowMenu` Share/Flag glyphs, the `Explore` search-field magnifier, the top bar's search glyph, static half-filled-circle preferences glyph and account-menu chevron, and the label-less kebab, chevron, calendar and remove controls all ship as local inline SVGs (`aria-hidden`, sized by CSS token — never `width`/`height` in markup). They mark a control or link target; none is standalone decoration. Same closing rule as above: this does not open the door to new icons — a new one needs a case in this list.
- **Two top bars stay separate.** `OrganizerTopBar` does not converge on `TopBar`: `TopBar`'s nav/auth links are hardcoded to consumer routes, and each renders its own `<header>`/`<nav>` markup. They share `Bar.module.css`, the bar sub-components (`BarLogo`, `BarNav`, `AccountMenu`, `PrefsMenu`) and `MobileMenu` itself, parameterized via its `navItems`/`accountItems`/`track`/`navAriaLabelKey` props so each top bar passes its own link set (`NAV_ITEMS` vs `ORGANIZER_NAV_ITEMS`). Extracting a prop-driven base *header* component to save ~15 lines of JSX still costs more indirection than it returns; that's the part of the merge that stays rejected.
- **The Dial is the brand mark, not an icon.** `DialMark` (rim, inner ring, pivot in `currentColor`; hand and tip dot in `--accent-ink`) replaces `BRAND_GLYPH` (`◉`) in both bars, `Footer` and `AuthCard`. The bars play its intro (hand turns once, rim draws in) on the first bar mount per page load only (a module-level flag — every route mounts its own bar); `Footer` and `AuthCard` render it static. `AdminShell` keeps `◉` — the admin sub-language gets no brand imagery — so `BRAND_GLYPH` stays in `constants.ts` for it alone. Animations are `backwards`-fill only, and the rim's `stroke-dasharray` lives only in the keyframes (on the resting ring it leaves a hairline gap at 12 o'clock). Favicon, app icons, emails and the OG image do not carry it yet.
- **`OrganizerDashboard` stays a row-list**, on consumer-register typography (Cormorant heading, Manrope body) — not admin's sub-language, not Explore's grid. That line is what keeps the portal a self-service product surface.
- **The organizer submit/edit form keeps its original structure** — content-language segmented control, stacked labeled fields, two-column date/price rows, `VenuePicker`/`SelectField`/`FileField`. A plate-anatomy rebuild (numbered plates, eyebrow labels, hairline-separated field rows) was prototyped and rejected. Cormorant heading over Manrope-with-sharp-corners fields is the *intended* contrast, not an inconsistency to resolve.
- **`EventDetail` changes with the smallest structural diff.** Sharp-corner controls, Cormorant title. It's the most-linked, SEO-critical, prerender-gated page. The one sanctioned restructure is the wide-band `.rail`/`.body` split (§10): block *order* within `<main>` changed, content/JSON-LD/price marker did not, and narrow widths render the same stacked sequence.
- **Static/legal is the editorial surface.** `LegalPage` section headings are Cormorant, each `.section` carries a `--rule` hairline above it so a legal document reads as a sequence of blocks rather than one text wall. Body copy stays Manrope.

## 10. Layout and breakpoints

- One shared breakpoint: **640px** (mobile, the only one that recurs — ~20 stylesheets), tokenized as `--bp-narrow` but written as a literal in `@media` rules; see §3. Three one-off breakpoints exist where 640px didn't fit the layout, each documented by its own single-consumer token: **560px** (`Onboarding`, `--bp-onboarding-narrow`), **900px** (`Landing`'s stat row, `--bp-landing-stats`), and **1024px** (`DesktopGate`, the admin desktop gate, `--bp-desktop-gate`). **641px** (`Landing`) is the `min-width` complement to its own 640px `max-width` rule, not a separate breakpoint.
- Page widths are tokenized per surface (`--page-max-narrow`/`-legal`/`-medium`/`-grid`/`-wide`/`-feed`/`-organizer`/`-settings`). Pick an existing one before adding another.
- The browse grid is `Page.module.css`'s `.cardGrid` — `repeat(var(--card-grid-cols), minmax(var(--card-grid-col-min), 1fr))`: auto-fill over `--card-grid-min` below the wide band, fixed counts inside it (see below), collapsing to one column at 640px. Explore and SavedEvents both compose it; Feed deliberately does *not* (a lead `featured` card plus a list — five curated picks is a different problem from an unbounded browse list, and converging the two would flatten the curated-vs-browse distinction).
- Admin geometry has its own tokens (`--admin-rail-width`, `--admin-queue-list-width`, `--admin-tile-min`, `--admin-trigger-min`, …) and its own desktop gate (`DesktopGate.module.css`).

### Wide viewports (≥2000px)

Locked via the wide-viewport map (#459), then revised on the real monitor. On a 3840×2160 monitor at ~150% scaling (2560×1440 CSS px) every surface used to sit in a narrow centre column. The fix is **pure reflow, no fluid tokens**: one wide band from a `min-width: 2000px` floor, fixed 1760px page centred above it, no intermediate step. The floor was first 1280px and moved up after review: a 2880×1620 laptop at 150% (1920×1080 CSS px) read better on the original layout, so the band sits between that laptop and the 2560px monitor. Everything ≤1999px — laptops, tablets, mobile — renders the original layout, and C1 is untouched. Every wide rule lives in a `@media (min-width: 2000px)` block.

- **Tokens.** One wide `:root` block at the end of `index.css` redefines `--page-max-wide` to **1760px** and points `--page-max-medium`/`-grid` at it. Doc token `--bp-wide: 2000px` (the literal still carries the `@media` rule). `--card-grid-cols` is `auto-fill` below the floor and **6** inside the band (the earlier 4-column step at 1280–1699 went with the old floor), with `--card-grid-col-min` dropping to `0` so six tracks fit; `cardGridColumns.test.ts` reads `index.css` and asserts every fixed count divides `BROWSE_PAGE_SIZE` and `SAVED_EVENTS_PAGE_SIZE` (24), so every page and load-more ends on a full row.
- **Top bar layout.** Desktop bar height is `--bar-h` (72px) at the top and `--bar-h-condensed` (54px) once scrolled; phones `--bar-h-phone` (60px) → `--bar-h-phone-condensed` (52px). It condenses on every route (hysteresis 24px/4px). Anything sticky or anchor-scrolled under the bar keys off the condensed height: `EventDetail`'s rail `top` is `--bar-h-condensed` (the bar is condensed whenever the rail is stuck; `useFitsViewport` reads that CSS `top`) and `Faq`'s `scroll-margin-top` uses `--bar-h-condensed`/`--bar-h-phone-condensed`. Landing's hero runs up under the transparent bar (`margin-top: calc(-1 * var(--bar-h))`, grid padded by the same, poster frame `top: var(--bar-h)`).
- **Chrome.** `TopBar`/`OrganizerTopBar` content aligns to the 1760 wrap via `padding-inline: var(--wrap-inset)` on the shared `.bar` (background stays full-bleed). `--wrap-inset` is `max(var(--space-6), calc((100% - var(--page-max-wide)) / 2 + var(--space-6)))`; its `100%` resolves at each use site, so any full-bleed strip can reuse it. `.gridMain` takes `--space-6` side padding inside the band so grid edges meet the bar. `Footer` unchanged (centred, follows `--page-max-wide`).
- **Landing.** The hero still fills the available height (an 820px cap was prototyped and dropped); instead its small type steps up the `--fs-*` scale (counter/dateline/capbar labels `--fs-3xs` → `--fs-sm`, sub and browse CTA → `--fs-lg`, no-password note → `--fs-base`, email input → `--fs-xl`, email submit → `--fs-sm`, ticker label → `--fs-xs`, ticker items → `--fs-base`). The `h1` stays on `--font-size-display-hero` (96px max) — don't grow it against the 60-ch ET headline. Ticker strip stays full-bleed; its label and the marquee window are inset to the wrap on both sides (`.tkLabel` padding, `.tkView` margin + hairline), so items enter and leave at the same insets. Plates are **staggered**: each row is capped at `--plates-max-width` (1240px), `.plate` hugs the wrap's left edge and `.plateFlip` its right; the media panel is `--plate-media-width` = `--plate-media-min-height` (400px in the band) × `--plate-media-aspect` (16 / 9), the text column takes the rest. The width is fixed, so a row that grows past 400px (long ET/RU text) gets a taller-than-16:9 panel — accepted; the image is `contain` over a backdrop either way. Proof section and organizer CTA widen to the 1760 wrap with the same columns.
- **EventDetail.** Two columns: `.rail` (hero → `.railHead` date/title/actions → `.railFoot` details/claim) beside `.body` (why-go, about, important info). Details/claim sit before why-go in the DOM; below the band `.rail` is `display: contents` and `order` puts `.railFoot` after `.body`, so the stacked sequence is unchanged. One copy of each block — never duplicate DOM for a layout. Inside the band the rail sticks under the TopBar only while it fits the viewport: `useFitsViewport` (`hooks/`) compares the rail's height plus its CSS `top` against `innerHeight` and toggles `.railFits`, so a tall ET/RU rail never clips. Content, JSON-LD, the `event-price` marker and the prerender gate are unchanged. **Known trade-off:** below the band, keyboard/reading order (DOM) reaches details/claim before why-go/about while they render after them — accepted to avoid duplicating blocks (#466); tab order inside the band matches the visual rail-then-body order.
- **Explore / Saved.** Explore's search + filter rows sit in a `.toolbar` wrapper: a column below the band, one hairline-ruled row inside it with search capped at `--explore-search-max` (480px) and the category/vibe/free cluster pushed right; `flex-wrap` is the fallback when ET/RU labels outgrow the row. Saved follows the grid automatically.
- **Unchanged at every width: Feed, organizer portal, admin console.** `--page-max-feed` stays 760, `--page-max-organizer` (Dashboard, ClaimEvents, AdminEventDetail) stays 840, `--admin-queue-list-width` stays 340. Widened versions (Feed ~1080, organizer lists at the 1760 wrap, wider admin caps) were prototyped and read too wide. Their TopBar still aligns to the 1760 wrap — accepted.
- **Images.** No `srcset`/`sizes`; sources hold up at wide sizes. Only marginal case is Fienta on the Landing plate/hero (its CDN accepts `width` ≤ 1920 if needed).
- **Prerender / theming.** Prerender's 1280×720 default viewport is harmless (DOM-only). Light theme is token-driven (hairlines via `--rule`); every wide token is theme-neutral, so the light block needs no counterpart.

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
| `OrganizerTopBar` merged into `TopBar` | Rejected — indirection cost exceeds the saving. Stands after the bar restyle. |
| Top bar direction | A · Programme shipped (wordmark + Dial, nav with a gold rule on the bar's hairline, pulse chip, underline search, account + preferences menus). B · Scope and C · Stub were built as prototypes and not chosen. |
| Gold as text | Uses `--accent-ink` (`#e8a838` dark, `#8f6316` light), never `--accent`/`--accent-light` — the latter fails AA as text on the light ground. |
| Pulse chip | Counts **today** (`today_count`, exactly what its `/explore?date=today` link lists), not tonight; hidden at zero (slot stays rendered so its arrival shifts nothing) and not rendered on Landing, whose hero keeps its own counts. |
| Preferences glyph | A fixed half-filled circle that never reflects the current theme, so prerendered HTML can't show the wrong one. |
| Organizer form rebuilt on plate anatomy | Prototyped, rejected. |
| Cormorant anywhere in `/admin/*` | Removed, unqualified — no logotype exception. |
| `--radius: 0` sitewide (containers too) | Rejected — controls only. |
| Small inline SVGs (footer social marks, overflow-menu Share/Flag, search magnifier, kebab/chevron/calendar/remove) | Recorded as functional exceptions in §9 rather than removed; audit chose to document, not delete. No new icon ships without a §9 entry. |
| Emoji as iconography | Removed from consumer/organizer surfaces; admin status glyphs stay. Exception: the `👍 👎 🔖` signal glyphs stay in `FeedbackButtonRow` and the Saved tabs (owner decision, 2026-09-29). |
| Landing wide-screen hero side panel | Specced, never implemented, removed from scope. Re-opened and superseded by the wide-viewport layout (§10): Landing takes a pure-reflow wide composition, no side panel. |
| Wide viewports: scale / fluid type / fluid tokens | Prototyped against reflow; reflow won. No `vw`-driven page tokens, no root font-size scaling. Page width is fixed 1760px from the 2000px floor, centred. |
| Wide viewports: 1280px floor (4 → 6 columns) | Shipped, then raised to 2000px (2026-10-05): a 1920px-CSS laptop (2880×1620 @150%) read better on the original layout. Don't lower the floor below 1920 without re-checking that laptop. |
| Wide viewports: widening Feed, organizer portal, admin console | Prototyped (Feed ~1080, organizer lists at 1760, wider admin caps) and rejected on the real monitor (2026-10-05) — too wide. They keep their narrow widths at every viewport (#480 closed wontfix). |
| Wide viewports: Landing hero height cap | Prototyped at 820px and dropped — the hero fills the available height at every width; its small type grows in the band instead. |
| Third-party identity-provider brand marks (class exception) | The full-colour Google "G" mark is pictographic iconography, which §1/§9 forbid, and per Google's branding guidelines it may not be made monochrome, redrawn, or dropped. Recorded as a **class** exception — third-party identity-provider brand marks, mandated by that provider's published branding terms, rendered as a local inline SVG (never `<img>` — one fewer request, no `img-src` CSP surface, and the test asserts it), scoped to the sign-in surface only. The mark is the flat four-colour G (legacy icon-only asset), chosen over Google's current gradient "super G" on legibility grounds at the 20px render size. Does not reopen §9's general no-iconography rule elsewhere. The button itself ships `border-radius: 0` (composed from the shared `Button` module, unmodified) — Google's written guidelines state no minimum size and no corner radius, so this is a defensible reading against the prose, not a violation, even though it visibly departs from Google's own shipped assets. See `docs/adr/0002-google-sign-in-oauth-pkce.md`. |

## 13. Working checklist for a visual change

1. Read the token list in `index.css` before writing any value. If the value you need isn't there, add the token first.
2. Check `components/shared/` for an existing base class before writing chrome. Compose; don't copy.
3. If it's a color, decide whether it needs a `:root[data-theme="light"]` value.
4. Test the layout against the **Estonian and Russian** strings, not English.
5. Verify with imagery stripped, and under `prefers-reduced-motion: reduce`.
   For display type, also zoom the browser to 300% and raise its default font size (§4, "Display tokens must grow under browser zoom").
6. Verify visually before landing — a CSS retrofit that reads correct in the diff can still look wrong on screen. Ticket wording is not proof.
7. Run `npm run lint` and `npm run type-check` (house rules; CI does not enforce them).
