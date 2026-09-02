# Organizer portal design spec: apply C1 to the self-service portal

What's in here: the locked applied spec for wayfinder #198, under the C1-migration map #193. Covers `/organizer/login`, `/organizer/verify`, `/organizer/dashboard`, `/organizer/settings`, `/organizer/submit`, `/organizer/events/:id/edit`, plus `OrganizerTopBar`, `OrganizerProfileNudge` and `VenuePicker`. Read `docs/organizer-portal.md` for what these screens do, `docs/design/consumer-spec.md` for the auth-cluster treatment this inherits, and `docs/design/shared-layer-plan.md` for the tokens/variants this spec consumes.

The organizer portal sits between the map's two poles: a self-service product surface (not the admin sub-language) but a working tool for a repeat user, not a page anyone is being sold to. Every decision below leans toward the "working tool" pole — light touch on structure, universal on the sharp-corner primitives, full inheritance where the consumer spec already answered the question.

## 1. Chrome convergence: `OrganizerTopBar` stays a distinct sibling

`OrganizerTopBar` does **not** converge on `TopBar`. It keeps its own component, its own `.module.css`, and the rationale already written into its source comment: `TopBar`'s nav/auth links are hardcoded to consumer routes (`/login`, `/explore`, `/saved`, `/settings`), and the organizer portal deliberately has no mobile hamburger menu — three nav links (`organizer_dashboard_title`, `organizer_new_event`, `organizer_settings_nav`) fit inline at all viewport widths that matter for a small operator audience, unlike the consumer nav's four items plus locale switcher plus auth button.

What changes under C1 is styling only, inheriting the same primitives as the rest of this spec:

- Sharp corners (`buttonSharp`) on the sign-out button (`.authBtn`) — the only button-shaped control in the bar.
- `LocaleSelector` and nav-link treatment are unaffected — neither is a bordered control the sharp-corner rule targets.
- Brand glyph/wordmark (`.radar`/`.brand`) keep their current Cormorant-adjacent treatment, unchanged — identical markup to `TopBar`'s, so nothing here is new.

No shared abstraction is extracted for the two top bars. They already share only a brand lockup and a `LocaleSelector`, both trivial; forcing a shared base component to save ~15 lines of near-identical JSX would cost more in indirection (prop-driven nav lists, conditional mobile-menu rendering) than it returns, and it isn't what either the map's "extraction is selective" principle or #196's plan called for.

## 2. Shared auth chrome: inherited verbatim from the consumer spec

`/organizer/login` and `/organizer/verify` run on the same `AuthCard`/`MagicLinkForm` components as the consumer auth cluster (Login/AuthVerify/Onboarding/Unsubscribe). The consumer spec (#197 §"Auth cluster") already settled this treatment and explicitly hands it to this ticket:

- `AuthCard`'s centered-card shell stays structurally unchanged — no plate/row restructure, no artboard precedent for one.
- `.brand` heading and `.radar` glyph keep their current Cormorant/current treatment.
- `MagicLinkForm`'s `.input` and `.submit` take `fieldSharp`/`buttonSharp`.
- `AuthCard`'s `cardAccentTop` stays — not superseded by the plate family.

Nothing organizer-specific diverges here. `OrganizerLogin`/`OrganizerVerify` route components consume the same shared `AuthCard`/`MagicLinkForm` markup the consumer routes do; only the copy strings differ (already the case today).

## 3. The submit/edit form: original structure kept, sharp corners only

Prototype #195 tried rebuilding the form around the split-row plate anatomy (numbered plates, eyebrow labels, hairline-separated field rows) and that rebuild was **reviewed and rejected** — reverted to the form's original structure. This spec carries that rejection forward as the decision: `EventSubmit`'s current layout (content-language segmented control, stacked labeled fields, two-column date/price rows, `VenuePicker`, `SelectField`, `FileField`) is unchanged.

What does change, per the shared-layer plan and universal per consumer-spec §3:

- Every real `<input>`/`<textarea>` (`.input`, `.textarea`) and the submit button (`.submit`) take `fieldSharp`/`buttonSharp`.
- `SegmentedControl` (the language-tab dial), `SelectField`, `VenuePicker`'s own input/menu chrome, and `FileField`'s choose/replace controls take `menuSharp`/`fieldSharp`/`buttonSharp` wherever they render a bordered control — each of these is a shared component already, so the sharp-corner treatment is inherited automatically once those shared modules pick it up; nothing organizer-local needs a bespoke override.
- `.contentEyebrow` (the "Event details" `h2` above the language tabs) and `.title` (the page `h1`) keep their current Cormorant treatment — consistent with the consumer spec's rule that display type is allowed on page headings and section eyebrows, not on form controls or data values. This is the same "Cormorant-over-form" pairing prototype #195's form artboard deliberately stress-tested, and it survived: the heading being Cormorant while every field beneath it is Manrope-with-sharp-corners is the intended contrast, not an inconsistency to resolve.
- `OrganizerProfileNudge` is unaffected structurally; if it renders a dismiss control, that control takes `buttonSharp`.

No new component, no new variant. This section is a direct instruction to whichever migration issue builds it: apply the shared sharp-corner classes to the existing markup and stop.

## 4. Dashboard density: light touch on the existing row-list

`OrganizerDashboard` is already a row-list, not a card grid — each row `composes: card` from `Card.module.css` and lays out title/meta/status-badges/edit/delete inline, with a Cormorant `h1` masthead above it. It is closer in shape to the admin queue's dense rows than to Explore's plate grid, but it keeps consumer-register typography (Cormorant heading, Manrope body) rather than converging on admin's no-Cormorant sub-language — the map draws that line specifically to keep the organizer portal a self-service *product* surface, not an admin panel, and blurring it here would undercut that.

Locked treatment: keep the row-list structure exactly as built. Changes are additive only:

- `.newBtn`, `.editBtn`, `.deleteBtn` take `buttonSharp`.
- `.row` itself is unaffected — `Card`'s base `--radius` is untouched per the map's own rule (only interactive-control corners go sharp, not card/image rounding).
- `.statusBadge`/`.reviewBadge` are unaffected — they're chip-shaped meta, not interactive controls, matching how the consumer spec left comparable badge/chip treatments alone elsewhere.
- `.heading` (Cormorant `h1`) is unchanged.

No `cardEditorial` adoption here — the rows are functional (status, review flag, edit/delete actions) rather than browsable imagery-led content, and most submissions won't carry the kind of curated image the plate family is built to showcase.

## What this spec does not change

- No copy changes — every string above already exists; this is a pure styling pass.
- `VenuePicker` gets no new structural variant beyond the sharp-corner primitives already flowing through from `Field.module.css`/`Menu.module.css` — it's a consumer of those shared modules, not a bespoke component to relitigate here.
- `OrganizerProfileNudge`'s dismissal/copy behavior is unchanged (§3).
- Nothing here reopens the admin boundary (#199) — this spec confirms the organizer portal stays on the consumer typographic register, which is the fact #199 can build its own sub-language contrast against.

## Open items carried to other tickets

- **The terminal cleanup ticket** (carried on #193's map) is where the interim `buttonSharp`/`fieldSharp`/`menuSharp` markers on the shared modules eventually get collapsed once every consumer — including this portal — has migrated. Building the organizer migration issue itself is out of scope for this spec, per the map's Notes.
