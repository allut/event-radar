# Consumer portal design spec: apply C1 to app screens, auth, static/legal

What's in here: the locked applied spec for wayfinder #197, under the C1-migration map #193. This is the document the per-surface migration issues get written from, and the one Explore's implementation ticket (#200) builds against. Read `docs/design/landing-spec.md` for what C1 is, `docs/research/app-surface-audit.md` for the composition/tell baseline this spec answers, and `docs/design/shared-layer-plan.md` for the tokens/variants this spec consumes.

"Consumer portal" here means three clusters, all resolved below:

- **App screens** — Feed, Explore (built under #200, not repeated here), EventDetail, SavedEvents, Settings.
- **Auth** — Login, AuthVerify, Onboarding, Unsubscribe, and the `AuthCard`/`MagicLinkForm` chrome.
- **Static/legal** — Privacy, Terms, Contact, NotFound, and the `LegalPage`/`StaticPage` shells.

## The five things this spec had to resolve

### 1. EventCard's shape

**Superseded.** This spec originally called for a third `EventCard` variant, `editorial` — a split-row plate (fixed-height image panel filled with `object-fit: cover`, text column beside it, `.hair` rule between eyebrow/meta and title), ratio-proof by construction per the map's own #185 lesson. It was built twice against this spec (#200 for Explore, #204 for SavedEvents) and reverted both times on product review after seeing it live — "looks bad" against the standard card grid, no structural fix attempted. Neither surface has an `editorial` consumer left; the variant and its shared plate CSS (`cardEditorial` family in `shared/Card.module.css`, `riseEditorial`/`fadeInEditorial` in `shared/Animations.module.css`) don't exist in the codebase. `EventCard` stays two variants, `standard`/`featured`, everywhere.

The five shared `--plate-*`/`--font-size-display-card` custom properties stay defined regardless — `Landing.module.css`'s own `.plate` showcase rows still consume them independently of this now-dead `EventCard` variant.

### 2. Where display type (Cormorant) is allowed

- **Masthead + card/list titles.** Cormorant stays on page headings (Feed's date heading, Explore's masthead, EventDetail's `h1`, Settings' page title) **and** on every card/event title — `EventCard`'s current title treatment (Cormorant at `--heading-sm`) carries forward unchanged in kind.
- **Static/legal gets it further** — section headings (`LegalPage`'s `.h2`) move to Cormorant too, see §Static/legal below.
- Everywhere else — body copy, labels, buttons, meta rows, form chrome — stays Manrope. No new surface introduces Cormorant into a control or a data value.

### 3. Sharp corners: universal

`buttonSharp`/`fieldSharp`/`menuSharp` (shared-layer plan, `border-radius: 0` + `appearance: none` on real inputs) apply to **every** button, field and menu across all three clusters — Feed, EventDetail, Settings, auth, static/legal, not just plate-structured surfaces. This was prototype #195's own finding: sharp corners is the one treatment that survived all three review rounds as a universal on-brand marker, not a plate-specific trait. `--radius` itself is untouched (cards, images, chips keep their current rounding) — only interactive-control corners go sharp.

### 4. Empty / loading / error states

**`EmptyState`** (icon + title/message/hint, ~10 consumers) drops its `icon` prop entirely — no more raw emoji (🔍 etc., the audit's tell (c) hit). New shape: a thin `--rule` hairline above an eyebrow-style label, Cormorant title, Manrope message — **left-aligned**, matching the flat-proof-section rhythm from Landing, not the current centered block. This is a breaking prop change (`icon` removed); every call site updates when its route migrates, or gets a one-time pass in the migration issue that first touches a route using it — whichever comes first for that route.

```
EmptyState (new shape)
──────────────────────
<eyebrow small-caps>          ← existing i18n string, no new copy required
────────────────────────────  ← --rule hairline
No events match your filters  ← Cormorant title
Try widening your date range  ← Manrope message
```

**`PageState`** (spinner/error, transient full-page loading state) is **unchanged** — its centering is functional (a viewport-centered spinner is the conventional pattern, not the audit's "centered-everything" tell, which named specific content-bearing routes, not this component). No consumer of `PageState` changes under this spec.

### 5. EventDetail and the prerender gate

Reskinned in place — full-width hero kept, **not** restructured into a plate split. Sharp-corner meta chips/buttons, Cormorant title (already the case). Motion stays on the existing `rise` + 400ms mount-fallback pattern (#186's prerender-safe vocabulary); it does **not** adopt `.riseEditorial` under this spec, since EventDetail isn't building now and its own migration issue is the point where that choice gets made against the shared layer as it exists then. EventDetail is the app's most-linked, SEO-critical, prerender-gated page and is not visually QA'd under this map (only Explore is) — the lowest-risk move is the smallest structural diff.

## Per-cluster IA

### App screens

| Surface | Card shape | Type | Notes |
|---|---|---|---|
| Feed | `standard`/`featured` (unchanged), reskinned | Cormorant heading + card titles (current) | Lead+list structure kept — 5 curated cards is a different problem from an unbounded browse list; converging shape with Explore was considered and rejected (flattens the curated-vs-browse distinction #193's charting drew). Sharp corners on any control (locale switcher, promo CTA). |
| Explore | `standard` grid, reskinned | — | Built `editorial` under #200, reverted post-close to the card grid with only the sharp-corner treatment kept (`EventCard`'s `sharp` prop, later itself reverted — see §1). |
| EventDetail | n/a (no card, single event) | current | See §5 above — reskin only. |
| SavedEvents | `standard` grid, reskinned | Cormorant card titles (current) | Built `editorial` under #204 to converge on Explore's plate structure, reverted post-build on product review — see §1. `loadMoreBtn` keeps `buttonSharp`; `EmptyState` keeps its eyebrow. |
| Settings | n/a (form/list, no cards) | Cormorant page title + `.sectionTitle` eyebrows (current, unchanged) | Light touch: sharp corners on every control, structure unchanged. Persona-summary display (`Settings.tsx:98`, `.personaEmoji`) drops the emoji glyph — falls back to persona name text only, consistent with the PersonaCard decision below. |

### Auth cluster (Login, AuthVerify, Onboarding, Unsubscribe — `AuthCard`/`MagicLinkForm`)

Light touch: `AuthCard`'s centered-card shell is unchanged structurally (the audit didn't flag it as a tell, and there's no artboard precedent from #195 for a restructured auth shell). What changes:

- `.brand` heading and `.radar` glyph keep Cormorant/current treatment.
- `MagicLinkForm`'s `.input` and `.submit` take `fieldSharp`/`buttonSharp`.
- `AuthCard`'s `cardAccentTop` stays — the accent-top treatment is not part of the plate family and isn't superseded.

This cluster's treatment is shared with the organizer portal's `/organizer/login`/`/organizer/verify` (both run on the same `AuthCard`/`MagicLinkForm`), so #198 inherits this section verbatim rather than re-deciding it.

**Onboarding** gets the same light-touch pass: `.heading`/`.sub` on the intro block keep Cormorant/Manrope as today, `.cta` button takes `buttonSharp`. `PersonaCard` itself is resolved below (not left as fog, superseding the map's earlier "no reference design" note).

#### PersonaCard

Drops the full-color pictographic emoji (`shared/personas.json`'s `emoji` field stays in the data — other consumers may still exist outside this spec's scope — but `PersonaCard.tsx` stops rendering `.emoji`). Becomes typography-forward:

- `.name` becomes the card's visual anchor — steps up to `--heading-sm` (from `--heading-xs`), Cormorant, unchanged color/selected-state logic.
- A `.hair` rule (reusing the plate family's hairline treatment, not a new token) separates `.name` from `.vibe`.
- `.vibe` stays Manrope, unchanged size/color.
- `.badge` (rank number) is unaffected — it's already typography, not an icon.
- Card shell keeps `composes: card` and its hover/selected treatment; only sharp corners are new (universal per §3).

No numeral/rank-glyph scheme replaces the emoji — an invented numbering tied to `PERSONAS` array order would carry meaning it doesn't have. Rank badges already do the only numbering this component needs.

### Static/legal cluster (Privacy, Terms, Contact, NotFound — `LegalPage`/`StaticPage`)

Full editorial, per the map's own framing of long-form text as "the cheapest possible surface for an editorial language":

- `LegalPage`'s `.h2` (section headings) move to Cormorant at `--font-size-display-section` sizing intent (not literally the token — `.h2` is a smaller in-page heading than a flat-section masthead; the point is the family, sized down to fit a legal document's heading hierarchy, tuned by eye at implementation time same as every other `clamp()` value in this system).
- A `--rule` hairline is added above each `.section`, echoing Landing's flat-proof-section rhythm (steps/figures/organizer-band/footer already use this exact pattern) — legal sections read as a sequence of editorial blocks, not a single scrolling text wall.
- `.body`/`.list` stay Manrope, unchanged — this is about heading rhythm, not a font swap on the reading text itself.
- `Contact`'s form fields/buttons take `fieldSharp`/`buttonSharp` (universal, §3); its structure is otherwise unchanged.
- `NotFound`'s `.code`/`.title` stay Cormorant (current); its `.card` (`cardPage`) is unaffected structurally, but gains sharp corners on `.backLink` if it renders as a button — it currently renders as a link, so no control-corner change applies there.

## What this spec does not change

- No copy rewrite beyond what §4's `EmptyState` prop removal forces (existing i18n strings are reused; no new keys required for the layout change itself, though a route's own migration issue may add strings where its layout genuinely needs them, per the map's "copy moves only where layout forces it" rule).
- `shared/personas.json`'s `emoji` field is not deleted — only `PersonaCard`'s render stops consuming it. Deleting the field outright is a data-shape decision outside this spec's scope (other consumers may exist, e.g. transactional email, which is out of scope on the map itself).
- `PageState` is untouched (§4).
- Feed and EventDetail's structures are unchanged (§1, §5) — this spec locks their reskin, not a rebuild.

## Open items carried to other tickets

- **#198** (organizer portal spec) inherits the auth-cluster section above verbatim for `/organizer/login`/`/organizer/verify`, and locks `fieldSharp`/`buttonSharp` for the submit/edit form per its own remaining questions (chrome convergence, dashboard density).
- **#199** (admin sub-language spec) adopts only the sharp-corner primitives from this spec (§3) — no Cormorant, no plate card variant (moot now anyway — see §1), no hairline-section treatment.
- **The terminal cleanup ticket** (carried on #193's map) is where Feed and EventDetail actually pick up `buttonSharp`/`fieldSharp` if their eventual migration issues choose to adopt what's specced here — this document specs their target state; building it is explicitly out of scope for this ticket per the map's Notes. `.riseEditorial` is moot: it was deleted along with the `editorial` variant (§1) and never had a Feed/EventDetail consumer.
- **Real event photography for imagery-bearing cards** — moot for now: it was carried as fog from #181/#193 against the `editorial` variant's image panel, which no longer exists (§1). Revisit if a plate-style card is proposed again.
