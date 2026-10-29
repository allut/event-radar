# Organizer Portal

What's in here: organizer auth, event submission, trust gating and review, rich-text authoring, the organizer contact form, Organizer Settings, Event Claiming, and Promotions.

An `Organizer` (`app/models/models.py`) is a portal account: a venue or promoter that submits events directly. It is not the Fienta organizer in [pipeline.md](pipeline.md), which is a ticketing-source id being polled. Saved Venues live in [data-model.md](data-model.md)'s Saved Venues section.

## Auth

- **The organizer track mirrors the consumer magic-link and session stack**, under `app/routers/organizer_auth.py` (prefix `/organizer/auth`). It has its own tables (`organizers`, `organizer_magic_links`) and the TTLs default to the consumer values.
- **Its own salts keep the tracks apart.** `AUTH_ORGANIZER_MAGIC_SALT` and `AUTH_ORGANIZER_SESSION_SALT` (`app/constants/auth.py`) mean an organizer token never verifies as a consumer token, though both use the same `SECRET_KEY` serializer.
- **`organizers.session_token_version` backs logout-all**, the same revocation pattern as the consumer track. See [security.md](security.md)'s Session Revocation section.
- **The session cookie is scoped to `Path=/api/organizer`** (`ORGANIZER_SESSION_COOKIE_PATH`), not `/api`. Every organizer endpoint must stay under `/organizer/*`, or the browser never sends the cookie and the endpoint silently 401s.
- **Google sign-in shipped on the organizer track first.** [ADR 0002](adr/0002-google-sign-in-oauth-pkce.md) picked it as the safe live-test surface while there were no real organizers. Magic link stays on both tracks. [security.md](security.md)'s Google Sign-In section has the flow.
- **`GOOGLE_SIGNIN_ORGANIZER_ENABLED` is the authoritative gate.** `VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED` only hides the button.

## Event Submission

`app/routers/organizer_events.py` (prefix `/organizer/events`) lets an organizer create, edit, cancel and list their own events.

- **A submission is inserted on the adapter-less `user_submission` source** through `app/ingestion/adapter.py::insert_normalized_event()`. It is then classified and published inside the request, not on the next scheduled pass.
- **`DELETE` is a soft delete:** it cancels the event. Cancelled events stay listed in Your events, so a delete never shrinks the list.
- **`GET /organizer/events` pages Your events at `ORGANIZER_EVENTS_PAGE_SIZE` (24) with the numbered pager.** It returns `total`, `limit`, `offset` and `has_more` on every page, sorted `created_at desc, id desc`. It runs at `RATE_LIMIT_BROWSE`, so quick paging and edit round-trips don't 429.
- **`GET /organizer/events/{id}` returns one of the caller's own events, with the list's row shape.** A foreign event is a 404. It feeds the edit form's prefill, so events past the list's first page stay editable.

### Image Upload

- **`POST /organizer/events/image` returns a signed Cloudinary upload**, so the API secret never reaches the SPA. It needs all three `CLOUDINARY_*` settings (`app/config.py`); with any unset it logs and returns 501.
- **Uploads are gated by `IMAGE_UPLOAD_ALLOWED_MIME` (415) and `IMAGE_UPLOAD_MAX_BYTES` (413).**
- **Never send `signature_algorithm` as an upload param.** It is an SDK-config knob. Cloudinary verifies against the params it receives, so sending it makes the check 401. `_cloudinary_signature` signs with SHA-256, which the account accepts by default.
- **`image_url` is pinned to our own Cloudinary account, on submit, edit and claim edit.** The claim edit form offers the same `FileField` upload. See [security.md](security.md)'s Organizer Images section.

### Daily Caps

- **`ORGANIZER_DAILY_SUBMISSION_CAP` and `ORGANIZER_DAILY_IMAGE_UPLOAD_CAP` are per-account, DB-backed ceilings.** The IP-keyed rate limiter can't enforce a per-account cap, since one organizer can spread requests across IPs.
- **Image uploads are counted in `organizer_image_uploads`**, because an upload can happen before any submission exists.
- **Both caps are soft.** Each is a count-then-insert with no row lock, so concurrent requests from one organizer can overshoot slightly.

### Localized Text

- **`title`, `description` and `important_info` each take optional `_en`/`_ru` siblings.** `_localized()` folds them into the `*_localized` JSONB columns, with Estonian as the base field, and drops blank locales.

### Organizer Categories

- **An optional `categories` list replaces the LLM's categories** on an organizer's own submission, on create and edit, through `replace_organizer_categories()` after inline classification. Merging would inflate persona affinity, which sums weights over every category.
- **`app/routers/utils.py::validate_categories()` checks the list.** Each slug must be in `VALID_CATEGORIES`; duplicates drop in order, and more than `ORGANIZER_MAX_CATEGORIES` (`shared/app-config.json`) is a 422.
- **An empty list on `PATCH` is a no-op.** The overwritten LLM set can't be restored, so an edit can never leave an event uncategorized.
- **A bare classification row is created if the LLM call failed**, so the organizer's categories still land.
- **`app/llm/classifier.py::_persist_classification` keeps an organizer's categories on a later retry.** Vibes, quality and the other fields still refresh.
- **The single `category` key is a deprecated alias**, folded in by `fold_legacy_category()`. It exists because Cloudflare and Render deploy separately. Remove it in a follow-up.
- **Claim edits only prepend** (`prepend_organizer_categories()`). The event's total is capped at `ORGANIZER_MAX_CATEGORIES`; going over is a 422 that changes nothing.
- **The frontend control is `CategoryPicker`.** Existing claim categories render as locked tags.

### Submission URLs

- **`url` and `image_url` go through `safe_render_url()`, and the stored value is its re-serialized form.** These URLs are only rendered, never fetched. See [security.md](security.md)'s Rendered-Only URLs section.

## Trust Gating and Review

- **A submission goes live at once only if its organizer is `verified`** and it clears the normal publish gate (see [pipeline.md](pipeline.md)'s Publish Gate section). Every submitted or edited event is also flagged `Event.needs_review`.
- **A new organizer starts `verified=false`.** Their first submission waits in `classified` until an admin approves it. Otherwise anyone who can receive one magic-link email could push an event with an arbitrary link into every feed and digest.
- **`submitted_by_organizer_id` (indexed) ties an event to its organizer.**
- **`app/publish.py::publish_pending()` enforces the gate itself**, not only the inline call in `submit_event`. An unapproved submission can't slip through on the next scheduled pass.

| Admin endpoint | Effect |
|---|---|
| `GET /admin/submissions` | Paginated queue, cancelled excluded |
| `POST /admin/submissions/{event_id}/approve` | Clears `needs_review`, sets the organizer `verified`, runs the publish gate |
| `POST /admin/submissions/{event_id}/retract` | Pulls a submission back out of `published` |

- **Approval is per organizer, not per event.** After the first approval, every later submission from that organizer auto-publishes.

## Rich-Text Authoring

`description` and `important_info`, with their locale siblings, are authored as HTML in `RichTextEditor`, a Tiptap toolbar in `EventSubmit`. It offers bold, italic, underline, lists, links, headings 3–4 and blockquote.

- **The sanitize allowlist tracks the toolbar.** `ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS`/`_ATTRS` (`app/constants/security.py`) are exactly the tags those extensions emit. Adding a Tiptap extension means adding its tag there in the same commit.
- **The allowlist is backend-only**, deliberately kept out of `shared/` so the frontend carries no second copy.
- **[security.md](security.md)'s Stored HTML section owns the sanitize boundary**: `organizer_sanitize()`, its callers and the frontend's defense-in-depth pass.
- **Length limits are per field, separate from ingestion:** `ORGANIZER_TITLE_MAX_LEN`, `ORGANIZER_DESCRIPTION_MAX_LEN` and `ORGANIZER_IMPORTANT_INFO_MAX_LEN`. They were raised with rich text because markup counts against the budget.

## Organizer Contact Form

- **`app/routers/organizer_contact.py` is the signed-in twin of the public contact form.** The body is only a `message`; name and email come from the session, so there is no honeypot and no spoofable identity.
- **It reuses `app/email/contact.py::send_contact_message()`** and swallows send errors as the public form does. It is rate-limited by `RATE_LIMIT_ORGANIZER_CONTACT`.
- **The frontend route is `/organizer/contact`**, reached from `OrganizerTopBar`'s account menu (`ORGANIZER_ACCOUNT_MENU_ITEMS`) and its mobile menu.

## Organizer Settings

A dedicated `/organizer/settings` route (`frontend/src/routes/OrganizerSettings/`), laid out like the consumer Settings page and reached from the account menu.

- **The profile is a display name only.** `Organizer.name` is nullable; `PATCH /organizer/profile` (`app/routers/organizer_profile.py`) strips whitespace and stores a blank name as `NULL`. Nothing on the profile prefills a submission.
- **There is no theme field.** Theme is a per-browser override, never stored on an account. See [design-system.md](design-system.md)'s Theme Resolution section.
- **"Log out everywhere" calls `POST /organizer/auth/logout-all`.**

### Sign-In Methods

- **`GET /organizer/profile` returns `google_linked`**, from `app/routers/utils.py::is_identity_linked()`. The page shows linked or not-linked copy from it.
- **Unlink calls `DELETE /organizer/profile/identities/google`.** It is unconditional, with no last-factor guard. It bumps `session_token_version` and re-issues the caller's own cookie, per [ADR 0002](adr/0002-google-sign-in-oauth-pkce.md).
- **Google's name and photo are never stored**, so nothing prefills from them.

### Profile Nudge

- **`OrganizerProfileNudge` shows on the dashboard and submit form while `name` is `null`.** It never blocks submission.
- **Dismissal lives only in `localStorage`** (`ORGANIZER_PROFILE_NUDGE_DISMISSED_KEY`). There is no backend field, so a cleared browser shows the nudge once more.

## Event Claiming

An organizer can claim an event Event Radar ingested from Fienta, KUMU, Estonia Concert Hall or Piletilevi. They prove ownership through a source-specific Proof channel, then edit the claimed content directly with no per-edit review.

- **`app/claims/` is the service; `app/routers/organizer_claims.py` and `organizer_claim_edits.py` are the router boundary.**
- **`CONTEXT.md`'s Event Claiming glossary defines the vocabulary:** Publisher, Proof channel, Publisher claim, Series claim, Claim justification, Dormant claim.
- **[ADR 0004](adr/0004-claim-eligibility-tightening.md) explains the eligibility rules below.** [security.md](security.md)'s Claims section has the guards on this flow.

### Claim Creation

- **The target must be `published` and dedup-canonical**, the same bar `public_event_filter()` and `canonical_event_filter()` apply (`app/claims/lifecycle.py::create_claim()`).
- **An organizer's own submission can't be claimed.** It has no ingested `EventSource` to claim against, and stays on the `Organizer.verified` trust track instead.
- **Both rejections return the same 404/422 as a nonexistent event**, so an id probe can't tell "missing" from "not claimable".
- **An ended event stays claimable.** The claim also covers future re-matched events of the same Publisher or Series. Discovery and search keep their own stricter filters.
- **Each organizer has a daily claim cap** (`ORGANIZER_DAILY_CLAIM_CAP`).

### Target Resolution

`app/claims/target_resolution.py::resolve_claim_target_live()` resolves the target live per source. Claim creation, recheck and verification all reuse it rather than trusting a possibly unstamped `EventSource.publisher_id`.

- **Fienta resolves the organizer id from the freshest matching `raw_events` payload.** It falls back to re-querying every configured organizer's listings, active and retired, through `FientaAdapter.fetch_organizer`. It always yields a Publisher claim and stamps the `EventSource` row.
- **KUMU and Estonia Concert Hall resolve to the source's single seeded Publisher** (`external_id IS NULL`), stamped or not.
- **Piletilevi resolves the promoter from the live event page's schema.org `Event.organizer`.** Any promoter that resolves yields a Publisher claim, get-or-created on that promoter id, whether or not it has a verifiable domain.
- **Only an unresolvable Piletilevi promoter falls back to a Series claim**, keyed on `event_series_key` (normalized title plus lowercased venue).
- **Any other case with no Publisher raises `ClaimTargetError`**, a 422 `ERROR_CLAIM_NOT_CLAIMABLE`. It is rejected outright, never downgraded to a Series or admin-review claim.

### Verification

`app/claims/verification.py` runs once per claim at creation and picks `auto_grant` or `admin_review`.

| Target | Proof channel |
|---|---|
| Fienta | Token round-trip through Fienta's organizer-facing surface |
| KUMU, Estonia Concert Hall | DNS-TXT on the institution's hardcoded domain |
| Piletilevi, domain-provable promoter | DNS-TXT on the promoter's contact domain |
| Piletilevi, mailbox-provable promoter | Exact, case-insensitive match of promoter contact email to the claimant's account email |
| Series claim | Admin review only |

- **A mailbox mismatch, or no contact info at all, falls to admin review.** Both emails are shown to the admin as evidence (`Claim.verification_contact`).
- **A Series claim requires a non-blank `justification`.** It carries no verifiable identity to auto-check, so the justification is what the admin reviews.

### Preemption and Expiry

- **Only `approved` claims are unique per target.** The partial unique indexes on `publisher_id` and `event_series_key` ignore `pending` rows, so rival pending claims coexist with their own proof tokens.
- **A claim against an already-approved target still gets 409** (`ERROR_CLAIM_TARGET_ALREADY_APPROVED`) with a support-facing message.
- **Proof preempts assertion.** When one pending claim passes automated verification, `auto_decline_other_pending_claims()` (`app/claims/lifecycle.py`) revokes every other pending claim on that target and emails each claimant the decline. Arrival order decides nothing.
- **`CLAIM_EXPIRY_DAYS` expires a fixable pending claim after inactivity.** That covers Fienta token, DNS-TXT and Piletilevi domain claims. The self-service recheck button resets the window.
- **`CLAIM_ADMIN_REVIEW_EXPIRY_DAYS` is the longer window, never reset**, for admin-review claims and mailbox claims that fell to review. The organizer can't act to fix those, so they get no recheck button.
- **The `expire_stale_claims` job runs both windows daily** and sends the expiry email. [backend-ops.md](backend-ops.md)'s Scheduled Jobs section has its time.

### Dormant Claims

- **An approved claim goes dormant when its event loses a claimed-vs-claimed dedup collision** to a better-quality duplicate. Its pins stop applying, but the row is never deleted.
- **It reactivates automatically** once its target is canonical again.

### Claim Resolution

- **Admin grant and decline send the claim-resolution email** (`app/email/claim_resolution.py`). Both go through `transition_pending_claim()`, so the loser of a race sends none.
- **Admin revoke deletes the claim row and sends no email.**

### Claim Surfaces

- **The organizer dashboard's `ClaimEventPicker`** searches events and suggests ones whose domain matches the organizer's email.
- **`/organizer/claims` (`OrganizerClaims/`) is Your claims, paged at `ORGANIZER_OWN_CLAIMS_PAGE_SIZE` (20) with the numbered pager.** `GET /organizer/claims` returns `total`, `limit`, `offset` and `has_more` on every page, sorted `created_at desc, id desc`. It has its own top-bar nav item.
- **The dashboard keeps only a summary line, "You have N claims (M pending) → View".** It reads `total` and `pending_count` from a one-row `GET /organizer/claims` request, and hides when the organizer has no claims. A new pending claim still shows where the organizer lands after signing in.
- **`/organizer/claims/:id/pending` (`ClaimPending/`)** shows the proof instructions and the recheck button.
- **`/organizer/claims/:id/edit` and `/organizer/claims/:id/events`** (`ClaimEventEdit/`, `ClaimEvents/`) are the claim-editing surface over `organizer_claim_edits.py`. Edits write `Event.pinned_fields` and count against `claim_edit_attempts`.
- **Claim events pages at `CLAIM_EVENTS_PAGE_SIZE` (20) with the numbered pager.** `GET /organizer/claims/{claim_id}/events` returns `total`, `limit`, `offset` and `has_more` on every page, sorted `starts_at desc, id desc`. A page change focuses the page's h1.
- **`/organizer/claims/verify` (`OrganizerClaimVerify/`) lands `POST /organizer/claims/request-link`'s sign-in link.** The token carries the `event_id`, so the claim intent survives a device switch.
- **The public `EventDetail` shows `ClaimPanel` and `ClaimPill`** (`components/ClaimStrip/`).
- **Admins resolve claims at `/admin/claims`** (`AdminClaims/`), over `GET /admin/claims` plus grant, decline and revoke.

### Claim Status Visibility

- **`ClaimPanel`, the "is this your event?" call to action, shows for unclaimed and pending-only targets.** A rival claimant must still be able to start proving ownership. It hides once a target is `claimed` or `not_claimable`.
- **The public payload never shows `pending`.** `GET /events/{id}` (`app/routers/events.py`) collapses it to `unclaimed` before serialization, for every caller.
- **Organizer auth alone was never a real boundary.** Organizer accounts are free to create, and the organizer cookie never reaches `/api/events` anyway.
- **The pending pill (`ClaimPill`) is claimant-only.** A signed-in organizer's `EventDetail` calls `GET /organizer/claims/for-event/{event_id}` (`own_claim_for_event()`), which returns the caller's own active claim or `null`, and shows the pill only on `pending`.
- **`claimed` stays public.** It backs the "Organizer-verified" and "Listed by X" labels for every viewer.

## Promotions

The Organizer offer and request path (`app/routers/organizer_promotions.py`, `app/promotions/requests.py`, `app/promotions/organizer_view.py`). A Promotion is defined in [data-model.md](data-model.md)'s Promotions section.

### Offer Flag

- **`PROMOTIONS_OFFER_ENABLED` (default off) gates every `/organizer/promotions/*` route.** While off they return 404, and event rows carry no `promotion` key. Admin direct grants are unaffected.
- **The offer never appears in submit or edit forms, modals, banners, settings or emails.** It lives on the Promotions page and as a quiet row action.

### Event Row Flags

- **`GET /organizer/events` and `GET /organizer/claims/{id}/events` add `promotion: {promotable, badge}` per row** while the offer is on, from one bulk read (`promotion_flags_for()`).
- **`promotable` needs current ownership, a public, canonical, not-ended event, room for a 3-day window and nothing open on it.** A dormant claim is not ownership.
- **`badge` replaces the action** with `requested`, `awaiting_payment`, `awaiting_checkout`, `scheduled`, `live` or `paused`.

### Requests

- **`POST /organizer/promotions/requests` creates a pending request** with dates, legal name, registry code, optional billing email (default: the account email) and note, plus `terms_accepted` and `business_attested`. It records `ORGANIZER_TERMS_VERSION` and both times, and emails the admin a deep link.
- **The registry code must be 8 digits with a valid check digit** (`app/promotions/registry.py`). Window, overlap and sold-out rules reuse the grant validation.
- **Limits are one pending request per event, no overlap with an `unpaid` or `paid` Promotion, and `ORGANIZER_DAILY_PROMOTION_REQUEST_CAP` per Tallinn day.** Refusals carry `detail.errors`: 409 for state, 429 for the daily cap, 422 for input.
- **An event the Organizer does not currently own is a 404,** whoever owns it.
- **`POST /organizer/promotions/requests/{id}/withdraw` withdraws a pending request.** Another Organizer's request is a 404.

### Form Helpers

- **`GET /organizer/promotions/context?event_id=` feeds the form:** window rules, price, terms version, default billing email, `checkout_available`, `review_required` and `unavailable_dates`. The dates are sold-out days only; counts never leave the server.
- **`GET /organizer/promotions/validate?event_id=&start_date=&end_date=` validates live** and returns the errors, the day count and the price. It writes nothing.

### The List

- **`GET /organizer/promotions` returns requests and Promotions newest first.** Status is `requested`, `declined`, `awaiting_payment`, `awaiting_checkout` (an open card checkout), `scheduled`, `live`, `paused`, `finished`, `ended_early` or `cancelled`. Items carry `billing_email` and, once card-paid, `invoice_url`. Withdrawn and expired requests and abandoned card checkouts drop off, and a granted request is replaced by its Promotion.
- **A `paused` item carries `paused_reason`,** the fill gate's not-showing code. The frontend turns it into plain words. The admin list and detail carry the same `paused_reason`, computed by the one `views.paused_reasons()` (one `evaluate_gate` call per page).

### Per-Day Report

- **`GET /organizer/promotions/{id}/report` serves the purchasing Organizer only** and does not check current ownership. It stays after a claim goes dormant or is revoked. Another Organizer gets 404.
- **It returns complete days only,** each with shown or paused (and the reason), Explore shown, Daily 5 placed, digest sent and opens, plus one `daily5_reach`. There is no viewer data and no slot dislikes.

### Portal Screens

- **`/organizer/promotions` (`OrganizerPromotions/`) is the explainer and the list.** An item is a request or a Promotion with a status badge and a one-line reason. Withdraw (with a confirm line), the `Invoice` link and the daily-report toggle sit under it.
- **The nav item and row actions hide while the offer is off.** `lib/organizerPromotionsOffer.ts` keeps a hint learned from the `promotion` key on event rows and from the list's 404, so the top bar needs no request. The page itself redirects to Your events on a 404.
- **A row's `Promote` link or badge comes from `PromotionRowAction`, after `Edit`.** The badge opens `/organizer/promotions?event=<id>`, which scrolls to that event's open item. Claim event rows keep their stretched title link, and the action sits above it.
- **The request form (`OrganizerPromotionRequest/`, `/organizer/promotions/new?event_id=`) validates dates through `GET /validate`.** Sold-out days arrive as dates from `/context` and grey out in `DatePicker`. A real `EventCard` previews the ad with the typed or registry name.
- **Card payment is the default action, with the request as fallback.** The form starts on Pay only when `/context` says `checkout_available` and not `review_required`; otherwise it starts on the request with the review copy. A 409 `event_needs_review`, a 404 or a registry outage still fall back.
- **Both paths make the Organizer confirm the business is its own.** Without it the server refuses `business_attestation_required`; with it, `business_attested_at` is recorded. The claim is trusted; see [ADR 0005](adr/0005-card-only-stripe-checkout-for-promotions.md).
- **The registry lookup runs once the 8-digit check digit passes.** A found name locks the field. Deleted and not-found codes block the form, and an outage opens a typed name and the request path.
- **The terms and content-policy links open `/organizer-terms` and its `#content-policy` section** (`ROUTES.organizerTerms`, `ROUTES.organizerContentPolicy`). That page carries a DRAFT notice; see [frontend.md](frontend.md)'s i18n section.
- **`OrganizerPromotionSuccess/` never trusts the redirect.** It polls the list until the Promotion is `scheduled` or later, because the Stripe webhook can land after the return. A late payment still gets the automatic refund the page describes.
- **The per-day table sums `web_opens` and `digest_opens` into one Opens column.** A paused day shows the gate reason in short words; the long sentence appears under the row's badge. Copy lives in `promo_*` keys, with `promo_why_<code>` per gate code.

### Expiry

- **A pending request expires inside `sweep_promotions` with no email.** It expires when its event is cancelled, when its Organizer loses the event (claim revoked), or when its start date arrives.
- **A dormant claim or dates that stop fitting leave it pending.**
