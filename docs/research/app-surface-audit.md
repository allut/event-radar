# App Surface Audit

What's in here: a factual baseline of the app *as it exists today* (2026-09-02), read directly from the frontend source — for wayfinder #194, under the C1-migration map #193. Landing (`frontend/src/routes/Landing/`) is excluded throughout; it already shipped the C1 redesign (commit `f3c5419`). This file does not propose a migration plan or a spec — it is the "what is" input that plan would work from. Format follows `docs/research/landing-true-facts.md`.

## 1. Composition map

`frontend/src/components/shared/` holds 16 CSS-module files, all pure CSS (no `.tsx` — confirmed via `find components/shared -type f`; only `Landing.tsx:18` imports one directly, for `Animations.module.css` class names used in inline JSX). Every one of the 16 names named in the ticket exists: `Page`, `Card`, `Button`, `Field`, `Bar`, `Menu`, `Animations`, `Media`, `Chip`, `Link`, `Alert`, `Spinner`, `StatusCircle`, `Visually`, `AdminQueue`, `DesktopGate`. "Composes from shared" below means a CSS Modules `composes: … from '.../shared/X.module.css'` declaration; "re-rolls locally" is a non-exhaustive sample of same-purpose rules defined from scratch in that file instead.

**Correction to the ticket's framing:** `Landing.module.css` is *not* fully "composes nothing" — it composes `Page` (page shell), `Spinner`/`Alert`/`StatusCircle` (email-capture form states), and `Animations` (`rise`, `breathe`) at `Landing.module.css:2,225,229,236,244,546`. It re-rolls everything else (hero, ticker, showcase-card plates, proof section, organizer CTA, footer) from scratch — 647 lines total, ~12 shared `composes:` lines. The "extreme" framing is directionally right (it's the least shared-dependent route) but not literally "composes nothing."

**Also stale:** `docs/frontend.md`'s line 11 says Landing has "own `RadarHero` subcomponent beside it" — no such file exists (`find routes/Landing -type f` → only `Landing.module.css`, `Landing.tsx`, `Landing.test.tsx`, `index.ts`). The hero markup was folded directly into `Landing.tsx` at some point during the C1 rounds; the doc wasn't updated.

### Routes

| Route | Composes from shared | Re-rolls locally (sample) | CSS module lines |
|---|---|---|---|
| Landing | Page, Alert, Animations, Spinner, StatusCircle (12 lines total, see above) | hero poster/scrim/frame, ticker marquee, showcase plates, proof-section stat row, organizer CTA, footer | 647 |
| EventDetail | Animations, Button, Media, Page | hero media block, price/venue meta layout, share/report menu wiring | 348 |
| Feed | Button, Card, Page | featured-card layout, `auto 1fr` two-col shell, empty/loading states | 205 |
| Explore | Button, Menu, Page (`cardGrid`) | filter bar layout, `repeat(3,1fr)` facet grid (line 143), load-more | 159 |
| Settings | Button, Card, Page | section list layout, centered auth-adjacent blocks (lines 139/145) | 146 |
| AdminEventDetail | AdminQueue, Card, Chip, Page | raw-meta mono block, two-col `auto 1fr` detail grid | 147 |
| OrganizerDashboard | Button, Card, Page | dashboard row/tile layout, centered icon rows (7 `align-items: center`) | 156 |
| OrganizerSettings | Button, Field, Page, Visually | form section layout | 123 |
| Onboarding | Alert, Button, Card, Page, Spinner | `repeat(3,1fr)` persona grid (line 48; `1fr 1fr` below 560px, line 55), centered copy | 120 |
| AdminPipeline | AdminQueue, Button, Card, DesktopGate, Field, Page | trigger tile `repeat(auto-fill,…)` grid, mono run-log lines | 107 |
| SavedEvents | Button, Page (`cardGrid`) | load-more button padding overrides | 31 |
| AdminDedup | AdminQueue, Button, Card, DesktopGate, Page | queue row layout | 66 |
| AdminReports | AdminQueue, Card, Chip, Page | queue/detail split styling | 76 |
| AdminSubmissions | AdminQueue, Card, Chip, Page | queue/detail split styling | 53 |
| AdminDashboard | Card, Page | `repeat(auto-fit,minmax(--admin-tile-min,1fr))` tile grid (line 15) | 63 |
| AdminLogin | Alert, Button, Card, Field, Page | centered auth-card shell | 74 |
| Login | Card, Page | centered auth-card shell | 47 |
| OrganizerLogin | Card, Page | centered auth-card shell | 47 |
| NotFound | Animations, Card, Page | centered 404 copy block | 49 |
| Contact | Alert, Button, Field, Spinner, StatusCircle, Visually | success-state check-circle block | 92 |
| EventSubmit | Alert, Button, Field, Page, Spinner | multi-field form layout (VenuePicker/DatePicker/SelectField/FileField do the heavy lifting, not this file) | 99 |
| Unsubscribe | Button, Link | status copy block | 12 |
| AuthVerify | Link | (3-line file, almost entirely delegated to `AuthCard`) | 3 |
| OrganizerVerify | Link | (3-line file, same pattern) | 3 |
| AdminPipeline/ConfirmRunModal | Button, Card | modal body layout | 54 |
| AdminPipeline/PipelineRunBreakdown | Card | mono error/status line layout | 31 |

### Components (`frontend/src/components/`, non-`shared/`)

| Component | Composes from shared | Re-rolls locally (sample) | CSS module lines |
|---|---|---|---|
| EventCard | Animations, Card, Media | image/meta layout, badge chips, featured-variant sizing | 305 |
| DatePicker | Field, Menu, Visually | calendar grid (`repeat(7,1fr)` ×2, lines 133/149), popover positioning | 323 |
| VenuePicker | Alert, Button, Field, Menu | list-row layout | 162 |
| AdminShell | *(none)* | entire nav-rail chrome from scratch, incl. `--font-display` brand text (line 32) and `--font-mono` labels (lines 39/87) | 147 |
| SelectField | Menu | listbox row layout | 135 |
| FileField | Button, Field, Spinner, Visually | upload/preview shell | 132 |
| DateRangeMenu | Menu | calendar-range specifics, one `border-radius: 0` override (line 130) | 131 |
| AdminQueueSplitView | AdminQueue | `var(--admin-queue-list-width) 1fr` split-grid (line 3) | 96 |
| MobileMenu | Button, Menu | slide-out panel layout | 96 |
| PersonaCard | Card | emoji badge, rank badge | 91 |
| Footer | *(none)* | entire footer chrome from scratch | 83 |
| TopBar | Bar, Button | nav-link layout | 79 |
| Button (shared itself) | — | — | 77 |
| EventOverflowMenu | Button, Menu | kebab trigger sizing | 82 |
| ReportModal | Alert, Button, Field | form layout | 110 |
| AuthCard | Animations, Card, Page, Spinner, StatusCircle | brand/radar block | 63 |
| MagicLinkForm | Alert, Animations, Button, Field, Spinner, StatusCircle | email input row | 63 |
| SegmentedControl | Visually | segment button layout | 107 |
| AdminQueueActionPanel | Button, Card, Field | note-field + action-button row | 51 |
| Modal | Button, Card | overlay/dialog shell | 54 |
| LegalPage | Page | body-copy typography | 52 |
| OrganizerProfileNudge | Button | banner layout | 58 |
| SelectMenu | Menu | one `border-radius: 0` override (line 17) | 61 |
| ErrorBoundary | Button, Card | fallback-screen layout | 39 |
| OrganizerTopBar | Bar | organizer-specific nav links | 39 |
| FacetMenu | Menu | chip-grid popover body | 36 |
| FeedbackButtonRow | Button | icon-button row | 42 |
| Toggle | *(none)* | switch control from scratch | 42 |
| Toast | *(none)* | banner from scratch | 27 |
| EmptyState | Animations | icon/message layout | 36 |
| Chip | Button | chip pill sizing | 27 |
| PageState | Spinner | loading/empty wrapper | 27 |
| StaticPage | Page | flat body layout (no importer today per `docs/frontend.md` — stylesheet reused by `Contact` only) | 16 |

**Reading the spectrum:** `AdminShell`, `Footer`, `Toggle`, `Toast` compose nothing from shared — the first three are structurally unique chrome (nav rail, site footer, a switch control) with no shared equivalent to compose from, not evidence of drift. Everything else composes at least one shared primitive, and `Page`/`Card`/`Button`/`Menu` are genuinely load-bearing across the app (composed by 23, 22, 28, and 9 `.module.css` files respectively, per `grep -rl "from '.*shared/X.module.css'" frontend/src/{routes,components} --include="*.module.css"`). `AdminQueue` and `DesktopGate` are narrowly but consistently used across the six admin-console screens that need them. The instruction-set's expectation of "Landing is the outlier, everything else composes a lot" holds directionally, but Landing is less of an outlier than framed (12 composes lines) and several small app screens (`AuthVerify`, `OrganizerVerify`, `Unsubscribe`, `PipelineRunBreakdown`) are near-100%-delegated, not near-0%.

## 2. Tell inventory

Per issue #181's charting of "made with AI" visual tells that C1 was built to kill. Landing excluded (already migrated). Evidence is file:line.

| Tell | Routes/components affected | Evidence |
|---|---|---|
| (a) hero + symmetric 3-col feature row | None found as a marketing-style hero+feature-row pattern outside Landing — the rest of the app is functional UI (auth forms, dashboards, feeds), not marketing pages, so this tell doesn't structurally apply the same way. Closest analog: Onboarding's persona-picker grid (see (e)/(c) below) reads as a symmetric feature-row even though it isn't marketing copy. | `frontend/src/routes/Onboarding/Onboarding.module.css:48` `grid-template-columns: repeat(3, 1fr)` |
| (b) uniform card grid | Explore, SavedEvents | `frontend/src/routes/Explore/Explore.module.css:99` `.grid { composes: cardGrid from '../../components/shared/Page.module.css'; }`; `frontend/src/routes/SavedEvents/SavedEvents.module.css:18` same. Both compose `Page.module.css:86-90`'s `.cardGrid` — `grid-template-columns: repeat(auto-fill, minmax(var(--card-grid-min), 1fr))`, identical `EventCard`s at uniform size. Feed is the one exception: `frontend/src/routes/Feed/Feed.tsx:103,108` renders a `variant="featured"` first card then a plain list, not a uniform grid. |
| (c) emoji used as iconography | Onboarding (via PersonaCard); admin console uses `✓`/`✕`/`⚠`/`☰` glyphs (arguably a lesser version of the same tell) | `frontend/src/components/PersonaCard/PersonaCard.tsx:33` `<span className={styles.emoji} aria-hidden>{persona.emoji}</span>`, sourced from `shared/personas.json:4,18,32,46,60,74,88,102,116` (🎛️💼🎨🎭👨‍👩‍👧🎤🎬🎙️🌹) — 9 real pictographic emoji as category icons, rendered in `frontend/src/routes/Onboarding/Onboarding.tsx:83`. Secondary: `frontend/src/routes/AdminDedup/AdminDedup.tsx:77` `<EmptyState icon="🔍" .../>`; check/cross glyphs at `frontend/src/routes/AdminPipeline/AdminPipeline.tsx:35,41`, `frontend/src/routes/AdminPipeline/PipelineRunBreakdown.tsx:69,88-89`, `frontend/src/routes/AdminReports/AdminReports.tsx:179`, `frontend/src/routes/AdminSubmissions/AdminSubmissions.tsx:159`, `frontend/src/routes/Contact/Contact.tsx:74`, `frontend/src/components/AuthCard/AuthCard.tsx:36-37`, `frontend/src/components/MagicLinkForm/MagicLinkForm.tsx:31`, `frontend/src/components/ErrorBoundary/ErrorBoundary.tsx:28`, `frontend/src/components/MobileMenu/MobileMenu.tsx:34`, `frontend/src/components/Modal/Modal.tsx:45` — these are Unicode symbol glyphs (status ticks/crosses/hamburger), not full-color pictographic emoji; a weaker instance of the same tell but still not a designed icon set/SVG sprite. |
| (d) decorative gradient blobs | None found outside Landing | `grep -rn "radial-gradient" frontend/src/{routes,components} --include="*.module.css"` returns zero hits outside `routes/Landing/`. This tell appears to already be absent from the rest of the app (nothing to migrate away from here). |
| (e) centered-everything layouts | Login, OrganizerLogin, AdminLogin, NotFound (all centered single-card auth/error shells — arguably expected for this UI class, not necessarily a tell); Onboarding (centered copy above the persona grid); Settings (2 centered text blocks) | `frontend/src/routes/Login/Login.module.css` (2 `text-align: center` rules), `frontend/src/routes/OrganizerLogin/OrganizerLogin.module.css` (2), `frontend/src/routes/AdminLogin/AdminLogin.module.css` (1), `frontend/src/routes/NotFound/NotFound.module.css` (1), `frontend/src/routes/Onboarding/Onboarding.module.css:` 1 `text-align: center` rule plus the centered `repeat(3,1fr)` grid, `frontend/src/routes/Settings/Settings.module.css:139,145` (2). All auth-card and dashboard routes with `max-width` + `margin: 0 auto` centered columns: `frontend/src/routes/{AdminEventDetail,EventDetail,Feed,Onboarding,OrganizerDashboard,OrganizerSettings,Settings}/*.module.css`. |
| (f) no real content density (whitespace-heavy, few data points/screen) | OrganizerDashboard (129-line `.tsx`, 156-line CSS, mostly single-column stacked rows with 7 separate `align-items: center` centering rules); AdminDashboard (63-line CSS, a `repeat(auto-fit, minmax(--admin-tile-min,1fr))` tile grid of summary numbers rather than a dense table); Onboarding (single persona-picker screen, no other content) | `frontend/src/routes/OrganizerDashboard/OrganizerDashboard.module.css:17,37,49,78,126,136,145` (`align-items: center` ×7 across a 156-line file); `frontend/src/routes/AdminDashboard/AdminDashboard.module.css:14-16` tile grid; `frontend/src/routes/EventSubmit/EventSubmit.tsx` (300 lines) and `frontend/src/routes/OrganizerDashboard/OrganizerDashboard.tsx` (129 lines) are comparatively the leanest-content app screens by LOC. This is the softest/most qualitative tell in the set — the evidence above is structural (grid/centering counts, LOC) rather than a grep-able pattern; a visual pass (Playwright screenshot) would sharpen it, which this ticket's scope (source-code audit) doesn't include. |

## 3. Hardcoded literals that should be tokens

**Colors:** `grep -rn "#[0-9a-fA-F]\{3,8\}\b" frontend/src/{routes,components} --include="*.module.css"` (excluding `components/shared/`) returns **zero hits** outside Landing/index.css. Color-token discipline holds across the whole non-Landing app surface today.

**Border-radius:** 35 files use `border-radius: var(...)`; only 4 use a literal, and all 4 are `0` (an explicit override, not drift) or `0` combined with `var(--radius)` on the other corners: `frontend/src/components/DatePicker/DatePicker.module.css:51`, `frontend/src/components/FileField/FileField.module.css:85` (`border-radius: 0 var(--radius) var(--radius) 0;`), `frontend/src/components/DateRangeMenu/DateRangeMenu.module.css:130`, `frontend/src/components/SelectMenu/SelectMenu.module.css:17` (`border-radius: 0;`).

**Spacing/font-size/box-shadow/z-index:** no literal (non-var, non-zero) `padding`/`margin`/`gap`/`font-size`/`box-shadow`/`z-index` values found outside Landing and the expected `margin: 0 auto` centering idiom. Token discipline is strong here too — contrary to the ticket's expectation that CLAUDE.md's "no CI enforcement" note implies drift, the non-Landing app surface currently shows very little.

**The one real repeated-literal pattern:** the `640px` mobile breakpoint is hardcoded (not tokenized) in at least 15 `.module.css` files — `frontend/src/routes/{EventDetail,Explore,Feed,Onboarding}/*.module.css`, `frontend/src/components/{AdminShell,AdminQueueSplitView,DatePicker,EventOverflowMenu,FacetMenu,FileField,SelectMenu,TopBar}/*.module.css`, `frontend/src/components/shared/{Bar,Page,Menu}.module.css`. Only one breakpoint is tokenized today: `--bp-wide: 1680px` (`frontend/src/index.css:235`), added for Landing's C1 wide-screen hero fix and not reused elsewhere. There is no `--bp-mobile`/`--bp-sm` token — `640px` is retyped at each call site.

## 4. `--font-system` / admin font carve-out

**The ticket's premise doesn't match the code: there is no `--font-system` token.** `frontend/src/index.css:60-66` defines three font tokens:

```
--font-display: 'Cormorant Garamond', Georgia, serif;   (index.css:60)
--font-body:    'Manrope Variable', system-ui, sans-serif; (index.css:61)
--font-mono:    ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace; (index.css:66)
```

`--font-body` is applied globally on `body` (`index.css:373`), so every route inherits Manrope by default including the admin console — there is no separate "admin body font," it's the same `--font-body` as everywhere else.

The actual admin-specific carve-out is **`--font-mono`**, used for data-dense/numeric UI: 7 admin files reference it — `frontend/src/routes/AdminDashboard/AdminDashboard.module.css:39,47`, `frontend/src/routes/AdminDedup/AdminDedup.module.css:20,44`, `frontend/src/routes/AdminEventDetail/AdminEventDetail.module.css:136,141`, `frontend/src/routes/AdminLogin/AdminLogin.module.css:22,46,51,70`, `frontend/src/routes/AdminPipeline/AdminPipeline.module.css:41,50`, `frontend/src/routes/AdminPipeline/PipelineRunBreakdown.module.css:12,25`, `frontend/src/components/AdminShell/AdminShell.module.css:39,87`. No other route (outside admin) uses `--font-mono`.

**Admin is not fully carved out of the brand display font either:** `frontend/src/components/AdminShell/AdminShell.module.css:32` sets `font-family: var(--font-display)` (Cormorant Garamond) for the nav-rail brand/logo text — the same serif used in Landing's hero. So today's admin console is a three-way mix per screen: Manrope body (inherited, unstyled), Cormorant Garamond for the one `AdminShell` brand mark, and `--font-mono` for numeric/status data — not a clean "admin uses a different system font" carve-out as the ticket's premise assumed.
