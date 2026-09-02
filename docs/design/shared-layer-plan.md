# Shared-layer extraction plan: C1 tokens, component variants, motion

What's in here: the extraction plan for wayfinder #196 (under the app-surface design map, #193) — exactly what moves from Landing into `components/shared/`, in what form, and what stays local. This is a plan, not an implementation: it unblocks #200 (Explore, the reference implementation) and gives #197/#198/#199 (the remaining portal specs) a shared vocabulary to build their applied specs against. Read `docs/design/landing-spec.md` for what C1 is; read `docs/research/app-surface-audit.md` for the composition/token-drift facts this plan is built on.

## Token diff

All twelve of C1's additive tokens (`frontend/src/index.css`) are used only by `Landing.module.css` today — this is a green-field naming decision, not a rename under live consumers.

**Generalize as-is (no rename):**

| Token | Why it generalizes |
|---|---|
| `--hair-width` | Names a treatment (hairline width), not a location. Explore B's plate rows reuse the exact `.hair` structure. |
| `--plate-media-min-height` / `--plate-media-min-height-compact` | Plate is the Explore B reference structure — literally the shape being extracted. |
| `--plate-text-min` | Same — the plate text-column grid minimum. |
| `--plate-image-filter` | Same — the saturate/contrast pull that keeps photos legible against navy is not hero-specific. |
| `--font-size-display-plate` | Already scoped to the plate context by name. |
| `--font-size-display-section` | Already scoped to flat-section headings, which recur (Explore's masthead heading is one). |
| `--font-size-display-card` | Already scoped to the split-panel showcase card title — same shape as a plate title. |

**Stay hero-only, documented not renamed:**

| Token | Why it stays local |
|---|---|
| `--poster-frame` | Only meaningful against a full-bleed poster background — nothing in the locked Explore B or admin specs has one. |
| `--grain` | Cinematic texture, no consumer outside the hero. |
| `--scrim-vertical` | Hero legibility scrim over poster imagery — no other locked surface has background imagery to scrim. |
| `--font-size-display-hero` | The giant hero numeral; name says so. |

No functional rename: nothing outside Landing references these four today, so a rename buys nothing and costs a diff. This plan documents the scope instead — if a future surface genuinely needs one of these four, that's a new decision made against a real consumer, not a speculative rename now.

**New token, closing an audit-flagged gap:**

- `--bp-narrow: 640px` — promotes the hardcoded `640px` mobile breakpoint (currently duplicated raw in 15+ files, including `Page.module.css`'s `.cardGrid`) to sit alongside the existing `--bp-wide: 1680px`. Genuinely recurs; Explore's reference implementation needs a mobile breakpoint regardless. This is a **value-preserving token promotion** — replacing `@media (max-width: 640px)` literals with `@media (max-width: var(--bp-narrow))` wherever they already appear is in scope for whichever ticket touches each file next (not a mass find-replace under this planning ticket).

## Component variants

Pattern: base class + composable modifier, matching the existing convention (`Card.module.css`'s `.card` / `.cardAccentTop` / `.cardPage`) — never restyle a base class in place.

| Shared module | New variant | Source | Notes |
|---|---|---|---|
| `Card.module.css` | `.cardEditorial` (+ `.cardEditorialFlip` for the alternating layout) | `Landing.module.css`'s `.plate` / `.plateFlip` family (`.plate`, `.plateMedia`, `.plateImg`/`.platePlaceholder`, `.plateText`, `.plateEyebrow`, `.plateH2`, `.plateBody`, `.hair`) | This is Explore B's split-row plate, verbatim. Extract the whole family, not just `.plate`. |
| `Button.module.css` | `.buttonSharp` | Prototype #195's universal carryover — `border-radius: 0` | The one treatment that survived all three prototype review rounds; applies wherever a C1-migrated surface has a button. |
| `Field.module.css` | `.fieldSharp` | Same — `border-radius: 0` + `appearance: none` on real `<input>`/`<textarea>` so the browser can't round them back | Needed by Explore's filter inputs; also pre-answers the sharp-corner requirement #197/#198 will lock for the organizer form. |
| `Menu.module.css` | `.menuSharp` | Same sharp-corner treatment, for Explore's facet menus | |
| `Page.module.css` | reuse `.gridMain` / `.gridMasthead` / `.gridHeading` / `.cardGrid` as-is | — | Explore already targets this shell (it's Explore/SavedEvents' existing grid-page shell per the audit) — no new variant needed, just a consumer of what exists. |

Not building now (no locked spec yet): an admin-table variant (#199 still open), an organizer-form variant beyond `.fieldSharp`/`.buttonSharp` (#198 still open). Building ahead of a locked spec risks a variant shaped by a guess instead of a decision.

**Deletion trigger:** the terminal cleanup ticket (carried in #193's "Not yet specified") deletes every superseded variant once all consumers have migrated. Until then, each old variant this plan supersedes gets an interim marker comment:

```css
/* deprecated once Explore migrates off it — see wayfinder #200 */
.card { ... }
```

No lint tooling — the migration is fully torn down by the terminal cleanup ticket regardless, so a comment is the whole enforcement mechanism.

## What stays local (unchanged from the map's charting decision)

Confirmed, not re-litigated: hero-specific Landing CSS (`.eyebrow`'s hero-scale use, the hero poster/ticker/organizer-CTA/footer sections, `--poster-frame`/`--grain`/`--scrim-vertical`/`--font-size-display-hero`) stays in `Landing.module.css`. Only the plate family, sharp-corner primitives, and the already-generic display sizes move.

## Motion

- **New scoped variants, not a global repoint.** `Animations.module.css`'s `.rise`/`.fadeIn` stay on `--easing` — repointing them to `--easing-landing` now would change motion feel on ~20+ surfaces that haven't visually migrated yet, which cuts against this map's own "new alongside old" sequencing. Instead: `.riseEditorial` / `.fadeInEditorial`, identical keyframes, `animation-timing-function: var(--easing-landing)`. C1-migrated surfaces (Explore) consume the new classes; everything else keeps `.rise`/`.fadeIn` on `--easing` until the terminal cleanup repoints (or deletes) them.
- **`heroRise` / `hairlineDraw` / `posterDrift` / `tickerSlide`** stay physically in `Animations.module.css` (already there) with their existing "Landing-only, do not reuse" framing preserved — no consumer outside `Landing.tsx` exists or is specified. A comment, not a file move: the components are already isolated by name and by the fact nothing else imports them.

## Landing's retrofit

**Deferred to the terminal cleanup ticket, not this map.** Landing already ships and looks right (#181/#185's shipped C1). Retrofitting it onto the new shared variants mid-map risks regressing a shipped surface for a payoff — removing the ~635 locally-re-rolled lines the audit found — that's identical whether it happens now or after every other surface has migrated and the shared layer's final shape is proven out by real consumers. Landing keeps composing the 5 shared modules it already does; its plate/hairline/sharp-corner CSS stays local until the terminal cleanup pulls it onto `cardEditorial`/`buttonSharp`/`.riseEditorial` alongside every other superseded-variant deletion.

## Blast-radius table

Per component, per current consumer, whether this plan touches it:

**`Card.module.css`** (22 consumers) — unaffected: all 22 existing consumers keep using `.card`/`.cardAccentTop`/`.cardDangerTop`/`.cardPage`/`.authCard` unchanged. `.cardEditorial` is new, additive, zero current consumers (Explore adopts it in #200).

**`Button.module.css`** (28 consumers) — unaffected: existing button variants untouched. `.buttonSharp` is new and additive.

**`Field.module.css`** (consumers: organizer submit/edit forms, Explore filters, Settings, auth) — unaffected: `.fieldSharp` is new and additive; no existing `<Field>` consumer's markup or class list changes under this plan.

**`Menu.module.css`** (9 consumers) — unaffected: `.menuSharp` is new and additive.

**`Page.module.css`** (23 consumers) — unaffected: `.gridMain`/`.gridMasthead`/`.gridHeading`/`.cardGrid` are reused as-is by Explore, no new declarations. The `--bp-narrow` token promotion touches `.cardGrid`'s media query when that file is next edited (by #200), but is value-preserving (`640px` in, `640px` out via the token).

**`Animations.module.css`** — unaffected for existing `.rise`/`.fadeIn`/`.breathe`/`.fadeInScale` consumers (still `--easing`). `.riseEditorial`/`.fadeInEditorial` are new and additive. `heroRise`/`hairlineDraw`/`posterDrift`/`tickerSlide` unchanged (still Landing-exclusive).

**`Landing.module.css`** — unaffected by this plan directly; its retrofit is out of scope here (see above). It remains the one place `--poster-frame`/`--grain`/`--scrim-vertical`/`--font-size-display-hero` are used.

**Admin console insulation** — holds, and is now deliberate rather than incidental: none of the variants this plan adds (`cardEditorial`, `buttonSharp`, `fieldSharp`, `menuSharp`, `riseEditorial`/`fadeInEditorial`) are Cormorant-gated or imagery-dependent by construction — sharp corners and plate geometry are typeface- and image-agnostic. Admin's own sub-language spec (#199) can adopt `buttonSharp`/`fieldSharp`/`menuSharp` (it already wants sharp corners per #195's admin-table artboard) without pulling in Cormorant or `--font-size-display-*`, since those live in separate token/class groups this plan never merges.

## Consumed by

- #200 (Explore, reference implementation) — builds `cardEditorial`, `buttonSharp`, `fieldSharp`, `menuSharp`, `riseEditorial`/`fadeInEditorial`, and the `--bp-narrow` promotion against `Page.module.css`'s existing grid shell.
- #197/#198 (consumer/organizer portal specs) — lock `buttonSharp`/`fieldSharp` for their form chrome, consistent with #195's prototype finding.
- #199 (admin sub-language spec) — adopts the sharp-corner primitives only; explicitly does not adopt `cardEditorial`, the display type scale, or any hero token.
