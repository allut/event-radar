# Design System

What's in here: the C1 visual language, tokens, the shared CSS layer, type, color and theming, shape, motion, component rules, layout, Landing, and settled decisions.

## 1. The direction: C1 (cinematic-on-brand)

The app runs one visual language, **C1**: editorial-cinematic type over the navy/gold brand. Type and hairline rules do the work, not palette novelty or decorative chrome.

- **Display serif over imagery.** Cormorant Garamond at large sizes, hairline `--rule` separators between sections, and gold as a sparing accent rather than a fill.
- **Interactive corners are sharp.** Buttons, inputs and menu popovers are `border-radius: 0`. Cards, images and chips keep `--radius`. See §6.
- **No decorative iconography.** Structure and type carry meaning, and a hairline beats a box. The few functional glyphs and the one emoji carryover are listed in §9.
- **Imagery amplifies; it never carries the page.** Every surface must still read with photography stripped. The Landing proof section and the plate rows are built to survive `noimg`.
- **The palette is not an open question.** An alternative, C2 (oxblood/bone/silver with Playfair Display, no navy/gold), was built, shipped, reviewed live and reverted. A new palette without new information architecture read stale. Reopening it means redoing the IA too.

## 2. Surface registers

Four registers share one token and geometry system. They differ only in type stack and appetite for imagery.

| Register | Surfaces | Type | Imagery |
|---|---|---|---|
| **Landing** | `routes/Landing/` | Cormorant at hero scale, Manrope body | Full-bleed poster, grain, scrims, plate rows |
| **Consumer app** | Feed, Explore, EventDetail, Saved, Settings, auth, static/legal | Cormorant on headings, eyebrows and titles; Manrope elsewhere | Event photography in cards and hero only |
| **Organizer portal** | `/organizer/*` | Same as consumer | Event images only |
| **Admin console** | `/admin/*` | `--font-system`, `--font-mono` for data | None |

- **The organizer portal is a product surface, not an admin panel.** That's why it runs the consumer register.
- **Admin inherits colors, spacing, hairlines and sharp corners, and declines everything display.** No `--font-display`, no `--font-size-display-*`, no Manrope, no scrims, grain or posters. State the rule this way for a new admin screen rather than listing screens.
- **Admin density sits at the small end of the `--fs-*` scale.** Emphasis comes from `font-weight`, not a bigger size.
- **Admin overrides the global `--font-body` locally.** `AdminShell.module.css`'s `.shell` sets `font-family: var(--font-system)` for every screen inside it. `AdminLogin` renders outside `AdminShell` (see `AdminApp.tsx`), so it carries its own declaration.

## 3. Tokens

Every visual value is a custom property in `:root` in `frontend/src/index.css`. That covers color, radius, shadow, z-index, motion, spacing, type, blur and component geometry. Define the token first, then use `var(--token)`.

- **Hex literals stay in `index.css` and `Landing.module.css`.** Keeping them out of every other stylesheet is what makes the light theme a token swap rather than a rewrite.
- **Name tokens by treatment, not location**, unless the scoping is deliberate. `--hair-width` names a treatment; `--font-size-display-hero` names its one consumer on purpose.
- **Hero-only tokens stay hero-only.** `--poster-frame`, `--grain`, `--scrim-vertical`, `--poster-glow-*` and `--font-size-display-hero` have one consumer, `Landing.module.css`. Generalise one only when a real second consumer arrives.
- **Gold as text uses `--accent-ink`**, never `--accent` or `--accent-light`. Those fail AA as text on the light ground.
- **Breakpoint tokens are documentation only.** Custom properties can't drive `@media` conditions, so `--bp-narrow`, `--bp-wide` and their single-consumer siblings name a value the `@media` rule still writes as a literal. Keep the two in sync, and leave `@media (max-width: var(--bp-narrow))` unwritten.
- **An off-scale spacing step gets a name.** Steps like `--space-0-42` exist because two or more call sites needed them. Add a named step rather than inlining a rem literal or forcing the wrong step.
- **Category gradients mirror the taxonomy.** The `--gradient-<category>` keys follow `VALID_CATEGORIES` in `shared/app-config.json`. A missing key falls through `utils.ts::categoryGradient()` to `--gradient-fallback`. A new category needs a gradient pair in both themes.

## 4. Typography

```
--font-display: 'Cormorant Garamond', Georgia, serif;
--font-body:    'Manrope Variable', system-ui, sans-serif;   /* set on html */
--font-mono:    ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
--font-system:  -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
```

### Adding a Face

- **A face ships as an `@fontsource` package imported in `frontend/src/main.tsx`.** The SPA's CSP is `font-src 'self'`, so a Google Fonts `<link>` or CDN is blocked. That's also why `--font-mono` and `--font-system` are system stacks.
- **A face needs a `cyrillic` subset.** `ru` is a first-class locale, and a face without one silently falls back to `system-ui` on every Russian character. DM Sans was replaced by Manrope for this reason.
- **Check `node_modules/@fontsource*/<face>/metadata.json`'s `subsets` before proposing a face.** Prefer an `@fontsource-variable/*` package: one file per subset covers the whole weight axis, usually cheaper than two static weights.

### Where Display Type Goes

- **Cormorant is for headings and titles.** That means page headings, section eyebrows, legal section headings, FAQ question rows, card and event titles, and the auth brand lockup.
- **Never on a control, form field, data value or meta row**, and never inside `/admin/*`. Those take Manrope, or `--font-system` in admin.

### Display Scale

- **Display sizes are `clamp()` tokens, never per-component clamps.** They're the `--font-size-display-*` family in `index.css`.
- **Size for Estonian and Russian, not English.** ET and RU UI strings run about 1.6× the English; `landing_hero_h1` goes from 42 characters in EN to 60 in ET. A fixed-px hero breaks, and a button sized to an English label wraps in Russian.
- **Real event titles run past 60 characters.** Any listing layout must allow them two or three lines.

### Browser Zoom

Zoom shrinks the CSS viewport, so a `vw` term shrinks as much as zoom enlarges it. Inside its fluid range a display size doesn't grow at all. `frontend/src/displayTokens.test.ts` guards both rules below (WCAG 1.4.4).

- **Display bounds are in `rem`, with max ÷ min ≤ 1.5.** At zoom *z* a token renders at least *z* × its min, so 1.5 guarantees 2× by 300%, Safari's cap. The common "≤ 2.5" only promises 2× by 500%. `rem` bounds also follow the user's default font size.
- **Never resize a display-token selector inside `@media`.** A zoomed desktop window crosses 640px, and the old Landing hero override made it shrink to 0.74× at 200%. Let the token's own clamp floor handle mobile sizing.
- **The price is a narrower range.** The hero runs 64px on phones to 96px on desktop, so phone layouts get taller type. Check new display tokens at 375px in ET and RU.
- **When taller type pushes a call to action off screen, change the layout, not the size.** On phones, Landing's `.heroTop` and `.heroBot` become `display: contents`, and flex `order` moves the capture bar above the sub and counter. The email input stays above the fold at 375×667.
- **A larger default font size stretches the layout too.** At 24px on a 320px phone, controls and long words must wrap, not overflow.

## 5. Color and theming

### Light Palette

- **Dark is the origin palette, on bare `:root`.** `:root[data-theme="light"]` redefines only the tokens that need a light value.
- **The light block covers grounds, text, borders, status colors, shadows, gradients and scrims.** Success and danger darken for AA on white. The gold card glow gets stronger, since it nearly vanishes on white. Gradients keep hue and saturation but flip lightness.
- **Everything else is theme-neutral:** spacing, type, geometry, the accent hue and its alpha overlays, `--overlay-scrim`, and every wide-band token.
- **A new color token that reads differently on near-white needs a light value.** An accent alpha overlay usually doesn't. Define a color in `:root` first, never only inside the light block.

### Theme Resolution

`frontend/src/lib/theme.ts::resolveTheme()` is pure and unit-tested. ADR 0003 records the model.

- **The device theme (OS `prefers-color-scheme`) is the default.** A theme override in `localStorage` (`theme_override`, plus `theme_override_device` for the device theme it was chosen under) wins only while that device theme still matches.
- **A device flip expires the override.** The OS listener re-resolves on every flip, so the device theme wins again.
- **The result is always binary, `light` or `dark`,** written to `document.documentElement.dataset.theme`. There is no stored "System" state: following the device is the fallback, not a choice.
- **The override lives in the browser, never on an account.** Signing in on either track neither reads nor writes a theme.
- **Both theme controls offer exactly Light and Dark:** the `PrefsMenu` theme row (both top bars and the phone drawer) and `AdminThemeToggle` in the admin rail. The `PrefsMenu` trigger is a fixed half-filled circle, so prerendered HTML can't show the wrong theme.

### Pre-Paint Script

- **An inline script in `frontend/index.html` resolves the theme before first paint**, so there's no flash of the wrong theme. It duplicates `resolveTheme`'s logic because it must run with no module loading. The two must never disagree.
- **Its storage keys mirror `THEME_OVERRIDE_KEY` and `THEME_OVERRIDE_DEVICE_KEY` in `frontend/src/constants/theme.ts`.** It also wipes the legacy `theme_preference` key unread.
- **Its body is pinned by a CSP hash in `frontend/public/_headers`.** Editing it means updating the hash, or production silently falls back to the boot self-heal with a flash on every load. See [security.md](security.md)'s Frontend CSP section.
- **`main.tsx` calls `applyTheme()` at boot, just before `createRoot(...).render(...)`.** It's a self-heal: if the pre-paint script is blocked or a snapshot shipped a baked `data-theme`, the theme corrects itself once JS runs.
- **Prerendered snapshots are theme-neutral.** `stripBakedThemeAttr` drops the build browser's `data-theme`; see [seo.md](seo.md)'s Theme-Neutral Snapshots section.

### Email Theming

- **Every email renders from one bundle,** `backend/app/email/styles.py::get_email_styles()` returning `EMAIL_STYLES` (ADR 0003). There's no per-recipient theme: a stored theme can't track a device that changes after the mail is sent.
- **The base is the light palette.** A client that strips `<style>` still gets a readable, intentional render.
- **A `prefers-color-scheme: dark` block repaints it dark.** `_THEME_CLASS_RULES` in `styles.py` drives the `e-*` class hooks in `templates.py`.
- **`EMAIL_DOCUMENT` declares `color-scheme: light dark` in its meta tags.** Without the declaration, Apple Mail and others apply their own dark inversion. That can turn a dark render into a washed-out, contrast-broken one.
- **CSS stays in `styles.py`, apart from markup and delivery.** See [frontend.md](frontend.md)'s Email section for the three-way split.

## 6. Shape

- **Interactive controls are square, in the base classes.** `border-radius: 0` lives in `Button`, `Field`, `Menu` and `Bar` modules' control classes. There is no opt-in `buttonSharp`/`fieldSharp`/`menuSharp` variant; leave those out.
- **A bordered control outside those bases sets its own `border-radius: 0`.** That covers components like `SegmentedControl`, `SelectField`, `DatePicker`, `Modal`, `Chip` and `FeedbackButtonRow`.
- **Containers keep `--radius`:** cards, images and consumer meta chips. A bordered sub-panel inside a form is a container too, like `VenuePicker`'s `.miniForm` or the EventSubmit content-language group.
- **Organizer status badges and tags are square.** "Chips keep `--radius`" applies to consumer meta chips only.
- **Hairlines, not boxes.** `--rule` (`1px solid var(--border-subtle)`) separates sections, and `--hair-width` sizes the plate and empty-state hairline. Reach for a rule before a border or a background change.

## 7. The shared CSS layer

`frontend/src/components/shared/` holds pure-CSS modules for page, card, button, field, menu, bar, calendar, settings and prose chrome. `GoogleSignInButton/` is the one component folder in it.

- **Consume shared modules with CSS Modules `composes:`.** Component CSS composes from `'../shared/X.module.css'`, route CSS from `'../../components/shared/X.module.css'`. Copy-pasting their rules is the drift this layer exists to stop.
- **`cssRules.test.ts` enforces the layer's rules.** It rejects `composes:` inside `@media` or `@container`, literal durations and radii, `@media` widths with no `--bp-*` token, and a block of 6+ declarations copied across modules.
- **Add a new shared pattern here rather than growing a second copy.** Variants follow base class plus modifier, like `.card` and `.cardAccentTop`. Restyling a base class in place for one consumer changes every other consumer.
- **`composes:` can't be scoped inside `@media`.** It resolves to a class-name string at build time. A shared rule needed only on one side of a breakpoint is restated locally, as `Feed.module.css`'s media-scoped `.srOnly` does. Keep a restatement in sync with its source.
- **A local override of a composed property must out-rank the shared rule.** Vite can bundle the shared module after the consumer, so a same-specificity override loses. Double the local selector (`.main.main`) or qualify it (`.main.mainWide`) like `Menu.module.css`'s `.menuPopFill.menuPopFill`. A modifier in the shared module itself (`AdminCommerce.module.css`'s `.inputFieldSize`) needs neither, because one file's source order is stable.
- **`Pager/` composes `Button.module.css`'s `.btnOutline` for every page link**, with `--space-2-75` (44px) targets. Callers place it and add spacing or a rule through `className`; it has no audience variant.
- **`PageSettle.module.css`'s `.settleTarget` gives a paged list's results heading its `scroll-margin-top`.** It clears the top bar at its full, unscrolled height (`--bar-h`, `--bar-h-phone`), so the heading clears the bar whether or not it has condensed.
- **Every bar and drawer link sets its own `:hover` color.** `index.css`'s global gold `a:hover` otherwise outranks a single-class link color.
- **`Prose.module.css` is the one typography for sanitized-HTML bodies.** `EventDetail` and `AdminEventDetail` compose it. `RichTextEditor`'s editing surface keeps its own margin model.
- **`AdminCommerce.module.css` is the admin commerce chrome:** pills, tags, chips, callouts, inline panels, hairline tables and the three admin buttons. The Promotions queue, Trust review and Stripe look compose it. Callouts take `.alertDanger` or `.alertSuccess` as modifiers.
- **`Landing.module.css` re-rolls its hero, ticker, plate and footer chrome locally, on purpose.** That treatment has no second consumer. Hoisting it into `shared/` adds indirection for nothing.

## 8. Motion

- **The app vocabulary lives in `Animations.module.css`:** `.spin`, `.breathe`, `.rise`, `.fadeIn` and `.fadeInScale`. Call sites tune them through `--spin-duration`, `--breathe-duration`, `--rise-duration` and `--rise-distance`.
- **`.rise` fills `backwards`, never `forwards` or `both`.** A held end transform leaves a non-`none` computed transform. That makes the element a containing block for any `position: fixed` descendant and breaks popovers, such as `EventOverflowMenu` on mobile.
- **Landing's keyframes live in the same file:** `heroRise`, `hairlineDraw`, `posterDrift` and `tickerSlide`. They're sitewide so a future surface reusing the poster or ticker needn't re-prefix them.
- **Three curves:** `--easing` for the app, `--easing-landing` for C1 motion, `--easing-breathe` for the looping pulse.
- **New motion collapses to `animation: none` under `prefers-reduced-motion: reduce`.**
- **New motion completes within the prerender's wait, or doesn't matter.** The prerender snapshots Landing, `/explore` and every event page headlessly. A scroll-gated reveal that never fires ships as invisible content. See [seo.md](seo.md)'s Readiness section.

## 9. Component-level rules

### Iconography

- **No pictographic emoji in consumer or organizer UI.** `PersonaCard` and Settings' persona summary render none. `shared/personas.json` keeps its `emoji` field as data only.
- **Unicode status marks (`✓ ✕ ⚠ ☰`) are functional glyphs, allowed everywhere.** Auth, modal, drawer and success states use them, and so do admin run and queue statuses.
- **One emoji exception: the `👍 👎 🔖` signal glyphs.** They come from `SIGNAL_CONFIG` in `frontend/src/constants/feedback.ts`, on `FeedbackButtonRow` and the Saved page tabs. The tabs keep them by owner decision, so a tab reads as the same signal as the button that saved the event.
- **Treat that exception as open work, not precedent.** Replacing the glyphs is fine; a second emoji set is not.
- **`RichTextEditor`'s toolbar glyphs are controls, not iconography.** They're local inline SVGs in `RichTextEditor/icons.tsx`, because a toolbar button has no text label to carry the meaning.
- **A few small inline SVGs are documented functional exceptions.** They're the footer social marks, the overflow menu's Share/Flag, the search magnifiers, the preferences glyph, the account chevron, and label-less kebab, chevron, calendar and remove controls.
- **Each inline SVG is `aria-hidden` and sized by a CSS token,** never `width`/`height` in markup. A new icon needs a case added to this list first.

### Google Sign-In Mark

- **Third-party identity-provider brand marks are a class exception.** Google's branding terms forbid making the full-colour "G" monochrome, redrawing it or dropping it. The exception is scoped to the sign-in surface and doesn't reopen the no-iconography rule.
- **The mark is a local inline SVG, never `<img>`.** That saves a request and an `img-src` CSP surface, and the test asserts it. It's the flat four-colour G, chosen over the gradient "super G" for legibility at 20px.
- **The button is square,** composed unmodified from the shared `Button` module. Google's written guidelines set no corner radius, so this is a defensible reading even though it departs from Google's own assets. See `docs/adr/0002-google-sign-in-oauth-pkce.md`.

### The Dial

- **`DialMark` is the brand mark, not an icon.** Rim, inner ring and pivot are `currentColor`; hand and tip dot are `--accent-ink`. It appears in both bars, `Footer`, `AuthCard`, `Login` and `OrganizerLogin`.
- **The intro plays on the first bar mount per page load only.** A module-level flag gates it, since every route mounts its own bar. `Footer` and `AuthCard` render it static.
- **Its animations fill `backwards` only.** The rim's `stroke-dasharray` lives only in the keyframes; on the resting ring it leaves a hairline gap at 12 o'clock.
- **Admin keeps `BRAND_GLYPH` (`◉`).** `AdminShell` and `AdminLogin` get no brand imagery, so the constant stays in `frontend/src/constants/core.ts` for those two alone.

`frontend/scripts/generate-icons.ts` draws the off-page marks: favicons, app icons, the email header mark and the OG fallback image.

- **Every off-page mark sits on a sharp, opaque navy square tile.** The tile stays navy under every browser chrome theme, and iOS and Android apply their own masks.
- **The email mark is the exception: its tile is rounded (`--radius` at 32px) with transparent corners.** No OS mask rounds it, and a sharp navy square read as a black box on the light email palette. The tile stays navy in both email themes, because clients that force-invert dark mode leave images alone.
- **Two optical sizes come from one geometry function.** The small size (favicons, the 32px email mark) drops the inner ring and thickens rim, hand, pivot and tip dot. The large size (app icons, apple-touch, maskable) stays faithful to `DialMark`.
- **Both sizes stroke the tip dot in the tile color**, so it cuts the rim instead of merging into it. The maskable icon keeps rim and tip dot inside the 40%-radius safe zone.
- **`og-fallback.png` is one image for all three locales,** so it carries no tagline. Its fonts are embedded from `@fontsource`, never a CDN.

### Components

- **`EventCard` has two variants: `standard` and `featured`.** An `editorial` split-row plate variant was built twice and reverted twice on product review. Add a third only after a live visual review. Landing's `.plate` rows are unrelated.
- **A Sponsored slot is `EventCard` with an optional `sponsored` caption slot, not a third variant.** The caption sits above the image, outside the stretched link. The label is bold small caps in `--text`, then `· {org}` in `--text-muted`, then a "Why?" text button in `--text-soft`.
- **The "Why?" button opens a panel over the card body (never the caption).** It is `--bg-raised` with a gold `--border-w-accent` top rule, the surface's explanation and a plain link to `/ranking#paid-slots`.
- **Gold text in a Sponsored slot uses `--accent-ink`, not `--accent-light`,** so the link passes AA on the light palette. The card is never banner-styled and carries the `SPONSORED_SLOT_ATTR` marker from `shared/`.
- **On Daily 5 the card sits in its own section after the list.** A `--rule` hairline and a `--fs-xs` `--text-muted` caption set it apart, so it never reads as pick #6.
- **`EmptyState` has no icon and is left-aligned.** Its shape is an optional small-caps eyebrow (an existing i18n string), a `--rule` hairline, a Cormorant title, a Manrope message, then an optional hint.
- **`PageState` stays centered.** A viewport-centered spinner is the conventional pattern for a transient full-page load.
- **The two top bars stay separate.** `TopBar` hardcodes consumer routes, and each bar renders its own `<header>`/`<nav>`. They share `Bar.module.css`, the bar sub-components and `MobileMenu`, which takes per-bar props. A shared base header would save about 15 lines for more indirection than it's worth.
- **`OrganizerDashboard` stays a row list in the consumer register.** That's what keeps the portal a self-service product surface rather than admin or a browse grid.
- **The organizer submit/edit form keeps its structure.** A plate-anatomy rebuild was prototyped and rejected. A Cormorant heading over sharp-cornered Manrope fields is the intended contrast.
- **`EventDetail` changes with the smallest structural diff.** It's the most-linked, SEO-critical, prerender-gated page. The one sanctioned restructure is the wide-band rail/body split in §10.
- **Legal pages are the editorial surface.** `LegalPage` section headings are Cormorant, and each `.section` has a `--rule` above it so a document reads as blocks, not a text wall.

## 10. Layout and breakpoints

- **640px is the one shared breakpoint**, written as a literal and named by `--bp-narrow` (§3). `Landing`'s 641px is its `min-width` complement, not a new breakpoint.
- **Five one-off breakpoints each have a doc token:** 560px for Onboarding, 900px for Landing's stat row, 1024px for the admin desktop gate, 760px for `PromotionTrust` and 1280px for the top bar (`--bp-bar-wide`). The Organizer promotion request form also collapses at 900px.
- **`Pager.module.css` holds the only container queries**, on the pager's own width. At `--bp-pager-stack` the label stacks over the buttons; at `--bp-pager-collapse` it keeps first, current and last. That fits a 340px admin column at any viewport. Like `@media`, `composes:` can't sit inside `@container`.
- **The top bar switches at 1280px (`--bp-bar-wide`).** Below it, `Bar.module.css` hides `.wideOnly` (pulse chip, inline search) and shows `.narrowOnly` (search icon and popover).
- **Page widths are `--page-max-*` tokens per surface.** Pick an existing one before adding another.
- **The browse grid is `Page.module.css`'s `.cardGrid`,** composed by Explore and Saved. It auto-fills below the wide band, uses fixed column counts inside it and collapses to one column at 640px.
- **Feed doesn't use the browse grid.** Five curated picks (a lead `featured` card plus a list) are a different problem from an unbounded browse list. Converging them would flatten that distinction.
- **Admin has its own geometry tokens and its own desktop gate** (`DesktopGate.module.css`).

### Top Bar Height

- **The bar condenses on scroll on every route.** Desktop goes from `--bar-h` to `--bar-h-condensed`; phones from `--bar-h-phone` to `--bar-h-phone-condensed`.
- **Anything sticky or anchor-scrolled under the bar keys off the condensed height.** `EventDetail`'s rail `top` and `Faq`'s `scroll-margin-top` both do.
- **Landing's hero runs up under the transparent bar** through a negative `margin-top` of `--bar-h`, with its grid padding and poster frame offset to match.

### Wide viewports (≥2000px)

The wide band is **pure reflow**: one `@media (min-width: 2000px)` band, a fixed 1760px page centred above it, and no fluid tokens. Everything up to 1999px renders the original layout.

- **The floor sits between a laptop and a monitor.** It started at 1280px, but a 1920px-CSS laptop (2880×1620 at 150%) read better on the original layout. Re-check that laptop before lowering the floor below 1920.
- **One wide `:root` block at the end of `index.css`** sets `--page-max-wide` to 1760px and points `--page-max-medium` and `-grid` at it. Every wide token is theme-neutral.
- **The band has six grid columns.** `frontend/src/cardGridColumns.test.ts` asserts each fixed count divides the 24-event page size, so every full page ends on a full row.
- **Bar content aligns to the 1760 wrap through `--wrap-inset`;** the bar background stays full-bleed. The token's `100%` resolves at each use site, so any full-bleed strip can reuse it.

#### Landing in the Band

- **The hero still fills the height; its small type steps up the `--fs-*` scale.** An 820px height cap was prototyped and dropped.
- **The `h1` stays on `--font-size-display-hero` (96px max).** Growing it fights the 60-character Estonian headline.
- **The ticker stays full-bleed, with its label and marquee window inset to the wrap.** Items enter and leave at the same insets.
- **Plates stagger:** `.plate` hugs the wrap's left edge and `.plateFlip` its right, each capped at `--plates-max-width`. The media panel has a fixed width, so long ET/RU text makes it taller than 16:9. That's accepted, since the image is `contain` over a backdrop.

#### EventDetail in the Band

- **Two columns: `.rail` (hero, date, title, actions, then details and claim) beside `.body` (why-go, about, important info).**
- **There's one copy of each block; layout never duplicates DOM.** Below the band, `.rail` is `display: contents` and `order` restores the stacked sequence.
- **Known trade-off:** below the band, DOM and tab order reach details and claim before why-go and about, while they render after.
- **The rail sticks only while it fits the viewport.** `hooks/useFitsViewport` compares its height plus CSS `top` to `innerHeight` and toggles `.railFits`, so a tall ET/RU rail never clips.

#### Other Surfaces in the Band

- **Explore's search and filters become one hairline-ruled `.toolbar` row,** with search capped at `--explore-search-max`. `flex-wrap` is the fallback when ET/RU labels outgrow it. Saved follows the grid.
- **Feed, the organizer portal and admin keep their narrow widths at every viewport.** Wider versions were prototyped on the real monitor and read too wide. Their top bar still aligns to the 1760 wrap.
- **Images use no `srcset`;** sources hold up at wide sizes. The prerender's 1280×720 viewport is harmless, since snapshots are DOM-only.

## 11. Landing structure

Section order is locked:

1. **Hero:** full-bleed poster with `--grain` and `--scrim-vertical`, a `--poster-frame` gold hairline inset, dateline and live counts at the top, then headline, subcopy, email capture and a browse CTA at the bottom.
2. **Ticker:** a one-line "tonight" marquee of time-stamped titles, paused under reduced motion.
3. **Showcase plates:** split rows with a fixed-height image panel (`object-fit: cover`) beside the text, alternating sides, with a gold hairline and meta row.
4. **Flat proof section:** how-it-works steps and a stat row, built to read with imagery stripped.
5. **Organizer CTA:** one row with a headline, one line and an outlined button.
6. **Footer:** trust line, locale list and year.

- **The plate's cover-filled fixed panel is ratio-proof by construction.** An earlier full-bleed fit needed a blurred backdrop, edge mask and lateral scrim to hide letterboxing. Three rounds of tuning failed before the structural fix.

### Honest Copy

Landing's numbers come from the live counts endpoint, `GET /public/counts` in `app/routers/public.py`, never hardcoded.

- **Show upcoming published events, rounded** ("over 1,000 events"), so daily attrition doesn't force copy edits.
- **Venue counts are published-scoped.** Counting distinct venues across all statuses runs about 50% high.
- **"Tonight" can be zero, and that's valid.** The endpoint widens to a fallback window rather than render an empty ticker.
- **Leave out throughput claims, the price ceiling and the thin category tail.** The data can't honestly support "N new events every week". Quote prices only as "tickets from €1".
- **Safe permanent copy:** five picks every morning at six, the digest at seven, hourly source re-reads, three locales, 14 categories.
- **The top bar's pulse chip counts today, not tonight.** It matches exactly what its `/explore?date=today` link lists, hides at zero while keeping its slot, and is absent on Landing. [pipeline.md](pipeline.md) owns the query.

## 12. Settled — do not re-litigate

Each of these was built or prototyped, reviewed and decided. Reopen one only with a new live review.

- **Palette push (new accent and ground, no navy/gold):** shipped and reverted. See §1.
- **`EventCard` `editorial`/plate variant:** built twice, reverted twice. It doesn't exist.
- **`buttonSharp`/`fieldSharp`/`menuSharp` variants:** superseded; sharp corners live in the base classes.
- **`--radius: 0` sitewide, containers included:** rejected. Controls only.
- **App and favicon tile shape:** a sharp square, not a rounded rect. Platforms mask app icons themselves.
- **Landing on shared plate classes:** not done. Its hero CSS stays local.
- **`OrganizerTopBar` merged into `TopBar`:** rejected. The indirection costs more than it saves.
- **Top bar direction:** A · Programme shipped (wordmark and Dial, nav with a gold rule, pulse chip, underline search, account and preferences menus). B · Scope and C · Stub were prototyped and not chosen.
- **Organizer form on plate anatomy:** prototyped, rejected.
- **Cormorant anywhere in `/admin/*`:** removed, with no logotype exception.
- **Emoji as iconography:** removed from consumer and organizer surfaces. Admin status glyphs stay, and so does the signal-glyph exception in §9.
- **Small inline SVGs:** documented in §9 rather than removed. No new icon ships without a §9 entry.
- **Wide viewports by scaling, fluid type or fluid tokens:** prototyped against reflow; reflow won. No `vw`-driven page tokens and no root font-size scaling.
- **Wide band at a 1280px floor:** shipped, then raised to 2000px. See §10.
- **Widening Feed, the organizer portal or admin:** rejected on the real monitor as too wide.
- **Landing hero height cap and side panel:** both dropped. The hero fills the height at every width.

## 13. Working checklist for a visual change

1. Read the tokens in `index.css` before writing a value. If the one you need is missing, add it first.
2. Check `components/shared/` for a base class before writing chrome. Compose; don't copy.
3. For a color, decide whether it needs a `:root[data-theme="light"]` value.
4. Test the layout against the **Estonian and Russian** strings, not English.
5. Check with imagery stripped and under `prefers-reduced-motion: reduce`. For display type, also zoom to 300% and raise the default font size (§4's Browser Zoom).
6. Verify visually before landing. A CSS retrofit that reads correctly in the diff can still look wrong on screen.
7. Run `npm run lint` and `npm run type-check` before committing; CI's `lint` job runs both.
8. Start a new surface from an approved prototype built on the shell below.

### Prototype Shell

- **A prototype is approved before UI work starts.** It uses the real tokens, the real components and the real `DatePicker`. Fake form styles and hand-copied palettes cost a review round each.
- **Load the `frontend-design` skill before building a prototype.** Its aesthetic direction applies inside the tokens: it picks layout and hierarchy and never new colors, fonts or radii.
- **`cd frontend && npx tsx scripts/prototype-shell.ts <out.html>` writes the shell.** It scopes the real `src/index.css` to `#app`, loads Manrope and Cormorant, and adds a working theme switch.
- **Mount every modal and dialog inside `#app`.** Outside it, a dialog loses the theme tokens and renders unthemed in the light theme.
- **Keep prototypes out of the repo.** Write them to the session scratchpad and delete them after approval.
- **Name no id or class with a bare `ad` or `ads` word.** Ad blockers hide those elements. `frontend/src/adBlockerNames.test.ts` enforces it across the CSS Modules and JSX.
