# Admin sub-language spec

What's in here: the locked applied spec for wayfinder #199, under the app-surface design map (#193). Defines the admin console's C1 **sub-language** — what it inherits from the shared layer C1 introduced, and what it deliberately declines. Read `docs/design/shared-layer-plan.md` for the shared variants this spec consumes, and `docs/research/app-surface-audit.md` for the pre-migration baseline facts this spec corrects.

## The boundary rule

**Admin inherits tokens and chrome (colors, spacing, radii-as-zero, hairlines, the shared layer's sharp-corner primitives) but runs on its own type stack and declines all imagery/display treatment.** Stated as a rule applicable to any new admin screen, not a per-screen list:

- Use `--font-system` for all text that isn't `--font-mono`. Never `--font-display` (Cormorant Garamond), never `--font-body` (Manrope).
- Use `--font-mono` for numeric/status data, exactly as today (run logs, badges, meta rows, timestamps).
- No imagery, scrims, grain, or poster treatment. No `--font-size-display-*` scale, no `cardEditorial`/plate family.
- Adopt the shared layer's typeface- and imagery-agnostic primitives: `buttonSharp`, `fieldSharp`, `menuSharp` (sharp corners — `border-radius: 0`, `appearance: none` on real inputs). These are safe because they carry no display-type or imagery dependency.
- Density biases toward the smaller end of the existing `--fs-*` scale (`--fs-2xs` through `--fs-md`) rather than `--fs-lg`/`--fs-xl` territory. No new size tokens — emphasis comes from `font-weight`, not a separate scale.

This settles #187's "insulation" claim more precisely than "admin reads the same `:root` tokens, cosmetic drift is fine": admin isn't merely insulated from breakage, it's a deliberate second type-and-imagery language sharing one token/geometry system with the rest of the app.

## New token: `--font-system`

```css
--font-system: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
```

Added to `frontend/src/index.css` alongside `--font-display`/`--font-body`/`--font-mono`. Deliberately **not** an alias of `--font-body` — it drops Manrope entirely in favor of the OS-native stack, matching the #195 admin-table artboard's `--sans` exactly (`-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif`). This is what makes the sub-language visually distinct rather than "Manrope with a different variable name."

**Scope: admin-wide, not spot-fixes.** `--font-system` replaces `--font-body` for every admin text element — headings, labels, buttons, nav, everything not already `--font-mono`. Not just the two former-Cormorant spots (brand mark, queue title); the whole console moves off Manrope.

**Application mechanism.** `--font-body` is set once, globally, on `body` (`index.css:373`) — every route inherits it by default, including admin today. Rather than touch that global rule, admin overrides it locally:

- `AdminShell.module.css`'s `.shell` gets `font-family: var(--font-system);` — cascades to every screen mounted inside it (`AdminDashboard`, `AdminReports`, `AdminSubmissions`, `AdminPipeline`, `AdminDedup`, `AdminEventDetail`).
- `AdminLogin.module.css`'s own root class gets the same declaration. Confirmed from `AdminApp.tsx:63-70`: `AdminLogin` renders standalone, before `AdminProtected`/`AdminShell` mount — it is not a child of `AdminShell` and needs its own override.
- `Modal` (shared component, used inside admin for confirm dialogs) does not portal (`grep` for `createPortal` in `Modal.tsx` returns nothing) — it renders in normal DOM flow inside whatever mounts it, so it inherits `--font-system` from `AdminShell`'s cascade with no extra wiring.

## The two Cormorant usages: cut

Both real, current Cormorant Garamond usages in admin are removed, matching the #195 artboard's precedent (the artboard's own brand mark and titles run sans + bold weight, no separate display scale, at every size it tested):

- **`AdminShell.module.css:32`** — `.name` (the "Radar" wordmark in the nav rail) currently `font-family: var(--font-display)`. Becomes `font-family: var(--font-system); font-weight: var(--fw-semibold);` at the existing `--fs-lg` — no size change, weight and stack change only.
- **`shared/AdminQueue.module.css:27`** — `.queueDetailTitle` (event/report/submission title in the queue detail panel) currently `font-family: var(--font-display)`. Becomes `font-family: var(--font-system); font-weight: var(--fw-semibold);` at the existing `--fs-lg` — same treatment.

No exceptions carved out: the rule is unqualified "no Cormorant anywhere in admin," not "no Cormorant except the logotype." A future admin screen never has to ask whether its case is the exception.

## Shared-variant adoption

`AdminShell`, `AdminQueueSplitView`, and `AdminQueueActionPanel` adopt `buttonSharp`/`fieldSharp`/`menuSharp` from the shared-layer plan (#196) rather than keep rolling local sharp-corner CSS (`AdminShell`'s nav links, `AdminQueueActionPanel`'s note `<textarea>`/action buttons, any admin `<select>`/menu chrome). This was already flagged safe by the shared-layer plan — none of these three variants are Cormorant-gated or imagery-dependent by construction. One shared source of truth for "sharp everywhere" instead of three local re-implementations that can drift.

`AdminQueue.module.css`'s existing `queueResolvedPanel` (`composes: card from './Card.module.css'`) is unaffected — `.card` itself isn't touched by this plan, only the new `cardEditorial` variant is, and admin explicitly does not adopt `cardEditorial`.

## What stays untouched

Named explicitly so it isn't re-litigated per-screen later:

- **i18n.** Admin stays un-i18n'd, English-only. No locale prefix, no `shared/i18n` strings.
- **Reachability.** Admin stays typed-URL/bookmark-only (`AdminApp.tsx`'s own comment: issue #154). No nav link is added from the consumer or organizer chrome.
- **Unicode status glyphs.** `✓`/`✕`/`⚠`/`☰` in `AdminPipeline`, `AdminDedup`, `AdminReports`, `Modal`, `MobileMenu` etc. are functional status marks, not pictographic emoji — a materially different (and weaker) instance of the "emoji as iconography" tell than what #197 killed in `EmptyState`/`PersonaCard`. Out of scope here; not silently dropped, just not this ticket's problem to solve.
- **`--font-mono` usage.** Unchanged — already correctly scoped to numeric/status data across the 7 files the audit found (`AdminDashboard`, `AdminDedup`, `AdminEventDetail`, `AdminLogin`, `AdminPipeline`, `PipelineRunBreakdown`, `AdminShell`'s badge).
- **`cardEditorial`, the display type scale, any hero token** (`--poster-frame`, `--grain`, `--scrim-vertical`, `--font-size-display-*`). None of these are adopted by admin, per the shared-layer plan's own "consumed by" note.

## Consumed by

The per-surface admin migration issue(s), built outside this map per #193's "Not yet specified" — `AdminShell`, `AdminQueueSplitView`, `AdminQueueActionPanel`, and all six admin route screens apply this spec's font-family/token changes and adopt the sharp-corner shared variants.
