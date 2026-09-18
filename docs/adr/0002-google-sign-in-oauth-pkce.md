# Google sign-in via server-side OAuth 2.0 authorization code + PKCE

Status: accepted

Relationship to ADR 0001: **extends**, does not supersede. Every ADR 0001
decision — httpOnly/Secure/`SameSite=Strict` session cookies, the
`CsrfOriginCheckMiddleware` Origin check, uncredentialed `CORS_ORIGINS` — is
unchanged and still in force. This ADR adds one thing ADR 0001 never
anticipated: a cookie kind that is *not* `SameSite=Strict`.

## Context

`docs/security.md` records two mirror magic-link auth tracks (consumer,
organizer), separate salts and tables, `SameSite=Strict` session cookies
minted only on a same-origin `POST /auth/verify` (and its organizer
equivalent). The magic-link inbox round-trip is the worst step in the
onboarding funnel; Google sign-in is a conversion play, added as a second
sign-in method that **coexists permanently** with magic link — email stays
the identity anchor because the product is a daily email digest, so a
deliverable address is required regardless of sign-in method.

Full charting and decision trail: [Map: Google sign-in on the consumer and
organizer tracks](https://github.com/allut/event-radar/issues/274) and its
closed child tickets (#275–#284, #286–#291). This ADR records the
architecturally load-bearing decisions; the implementation spec (filed
separately, linked from #285) carries the endpoint-level detail.

## Decision

**Server-side OAuth 2.0 authorization code flow with PKCE (S256), on both
tracks. No Google Identity Services (GIS) JavaScript library is ever
loaded; no rendered Google widget or iframe.**

The button is a plain first-party link/form. Clicking it top-level-navigates
the browser to `accounts.google.com/o/oauth2/v2/auth` with a PKCE
`code_challenge` attached. Google redirects back to a first-party callback
route on our own origin (through the `/api` proxy). The authorization
code is exchanged for tokens entirely server-to-server (with a client
secret), the ID token is verified, and only then is our normal session
cookie minted — exactly like `POST /auth/verify` mints it today.

### Why this flow, against each thing it had to be justified against

- **ADR 0001's session-cookie reasoning.** Untouched: the session cookie is
  still httpOnly/Secure/`SameSite=Strict`, still minted only after a
  same-origin server-side act completes (the callback response). What *does*
  reopen ADR 0001 is a new, narrow artifact — a short-lived, single-use
  state+PKCE-verifier cookie, needed only to survive the top-level
  cross-site navigation back from `accounts.google.com`. `SameSite=Strict` is
  not sent on that leg (rfc6265bis §5.6.7.1), so this cookie must be
  `SameSite=Lax` — the first non-`Strict` cookie in the app.
- **`CsrfOriginCheckMiddleware`.** No exemption needed — this is a fact
  about the existing middleware, not a carve-out. The callback Google calls
  is a **GET** (the code arrives via a 302's query string); the middleware
  only inspects mutating methods (`CSRF_UNSAFE_METHODS`). This is also the
  deciding fact *against* GIS's `ux_mode: "redirect"`, which is a cross-site
  **POST** the middleware would reject outright — and redirect mode is
  mandatory for GIS on iOS, so "GIS button, popup mode" was never a complete
  mobile answer.
- **`script-src 'self'` / CSP posture.** Zero change. No GIS library, no
  `accounts.google.com/gsi/*` script/frame/connect/style host is added.
  Every CSP host this app has ever added is a decision with a paper trail
  (the GA4 precedent); this flow adds none.
- **The cookieless/consent-banner privacy claim.** Survives. The new state
  cookie is first-party, httpOnly, single-use, ~10-minute TTL, and exists
  solely to complete the sign-in the user just initiated — the same
  strictly-necessary category (ePrivacy Art. 5(3)) as the existing session
  cookie. No Google-set cookie ever touches our origin.

### Mechanical consequences of the flow choice

- **Client secret is required.** Google's token endpoint does not advertise
  `none` as a supported `token_endpoint_auth_method` for a Web application
  client — the "Optional" label in Google's docs is native-client
  boilerplate.
- **PKCE: S256 only, never `plain`** — RFC 9700 (BCP 240) §2.1.1 recommends
  PKCE for confidential clients generally, not just native apps.
- **State cookie doubles as the anti-CSRF `state` parameter** — signed,
  single-use, compared on return.
- **ID-token verification**: `iss` ∈ {`accounts.google.com`,
  `https://accounts.google.com`}, `aud` == our client ID, `exp` not passed,
  RS256 signature against Google's published JWKS. `nonce` is **not** in
  Google's required-checks list and no library checks it for us — PKCE is
  the flow's replay defence, so no separate nonce is added.
- **Library: PyJWT + `PyJWKClient`**, not `google-auth`. `google-auth`
  re-fetches JWKS on every verification (uncached by default), is
  synchronous, and pulls `requests` into an all-`httpx`/async backend.
  `PyJWKClient` caches the JWKS (`cache_jwk_set=True`, 300s lifespan) with no
  new sync dependency; `iss`/`aud` checks are written by hand either way
  since neither library checks them exhaustively for this use.

## Considered options

- **Google Identity Services (GIS) / One Tap, ID token POSTed to the
  backend** — rejected. One Tap is FedCM-only as of the current GIS release
  (`use_fedcm_for_prompt` is deprecated and ignored), and FedCM is
  Chromium-only (no Firefox, no Safari, no Android WebView) — as a
  conversion play aimed partly at mobile, that is a large hole. The GIS
  button's `ux_mode: "redirect"` is a cross-site POST that
  `CsrfOriginCheckMiddleware` would reject outright, yet redirect mode is
  *mandatory* on iOS due to Safari ITP — so "GIS button, popup mode" is not
  a complete mobile answer without a middleware exemption. GIS also needs
  four new CSP directives, including a `frame-src` this app does not have at
  all today (falls back to `default-src 'self'`, blocking the iframe).
  Contrary to an initial assumption, no deadline forces a FedCM migration —
  Chrome cancelled the third-party-cookie deprecation (2024-07-22) and
  withdrew the replacement prompt (2025-04-22) — so there was no
  time-pressure argument for GIS either.
- **Hybrid — Google's rendered button as a launcher for the redirect
  flow** — rejected as unnecessary. The rendered GIS button is never
  mandatory (confirmed three ways: the server-side OAuth guide needs no
  Google JS at all, the GIS code model's own example uses a plain
  `<button onclick>`, and FedCM is explicitly optional). A custom-styled
  button driving the chosen server-side flow gets the same result with none
  of GIS's CSP or CSRF cost.
- **Shared cross-track `auth_identities` table** (schema-adjacent, decided
  alongside this ADR) — rejected in favour of two parallel tables,
  `user_identities`/`organizer_identities`, mirroring the existing
  `auth_magic_links`/`organizer_magic_links` split. A shared table would
  breach the "consumer and organizer tracks share no tables" separation
  `CONTEXT.md` and `docs/security.md` already treat as load-bearing.
- **Auto-link any Google identity whose token carries `email_verified:
  true`** — rejected as a live account-takeover path. Google's own
  verification guide states that for a non-Gmail, non-Workspace address
  *"Google is not authoritative"* — `email_verified` can be `true` merely
  because the address was verified at Google-account creation, while
  "ownership of the third party email account may have since changed."
  Since consumer accounts here are magic-linked to arbitrary addresses, an
  attacker who acquires an abandoned third-party address could otherwise
  walk straight into an existing account. Superseded by the authoritative-
  only gate below.
- **Opaque, server-stored state token** (a table row instead of a signed
  cookie) — rejected. The signed, single-use `itsdangerous` cookie mirrors
  `generate_magic_token`'s existing pattern exactly and needs no new table,
  no cleanup job, and no extra query on the hot callback path.

## Identity and linking model

Terminology (added to `CONTEXT.md`'s Authentication glossary): **provider
identity** (the external account, named by its stable `sub`), **identity
link** (the durable binding of one provider identity to one account on one
track), **confirmation magic link** (a magic link sent to prove control
*before* an identity link is created — not to start a session).

- **The gate is authoritative-only, with no exceptions.** Auto-link a
  provider identity into an existing account only where Google is
  authoritative for the address: `@gmail.com`/`@googlemail.com`, or an `hd`
  (hosted-domain) claim, in both cases with `email_verified: true`. Every
  other address goes through one confirmation magic link before the
  identity link is created — **including** when an existing `User` row is
  unverified. An earlier revision of this ADR carved out an exception here:
  a row with `email_verified = false` (a placeholder any unauthenticated
  caller could have created via `/auth/request-link`, holding no personas,
  feedback, or bookmarks) was absorbed unconditionally, on the reasoning
  that "there is nothing to take over." That reasoning missed that the
  row's *email address* — not its contents — is the thing a non-authoritative
  Google identity would be claiming, and Google's `email_verified` claim
  proves nothing about ownership of a non-authoritative address (OWASP audit
  M-1: an attacker could pre-create the placeholder via `/auth/request-link`
  for a victim's third-party address, then absorb it with a Google account
  that merely *claims* that email). The exception was removed; an unverified
  row now only auto-links when the identity is also authoritative.
- **Google becomes the second writer of `User.email_verified`**, on the
  authoritative path only. This retires the single-writer invariant
  `auth.py` currently asserts in comment form; the flag's meaning restates
  as "a party we trust has proven control of this address." The organizer
  track has no such column, so it needs no equivalent rule.
- **`User.email` is never written from a Google token.** `sub` is the match
  key. This makes "the email changes at Google and collides with a
  different existing account" structurally impossible rather than handled —
  there is no code path that writes email from the token, so there is
  nothing to collide.
- **Magic link never goes away.** Anyone with an identity link can still
  sign in by magic link, forever, on both tracks — this is what lets
  unlinking be unconditional (no last-factor guard) and lets a revoked or
  deleted Google account be safely ignored (no refresh token is ever
  requested or stored, so there is nothing on our side to revoke; a stale
  identity link is simply inert, since Google never reuses a `sub`).
- **`session_token_version` bumps on unlink, not on link** — unlinking
  removes a way in (sign-out-everywhere shape) and re-issues the caller's
  own cookie at the new version so only *other* devices drop; linking adds a
  way in and must not affect any existing session.
- **Cross-track separation stays silent.** The same Google account signing
  in on both tracks produces two independent, never-merged rows — exactly
  how email already works.
- **Scopes: `openid email` only.** No `profile` — neither `name` nor
  `picture` is ever requested or stored.
- **No organizer-track divergence.** `Organizer.verified` still defaults
  `false` and is earned only through the existing admin content-review
  queue, regardless of sign-in method — identity strength is orthogonal to
  promoter-content trust, and a real Google account is trivial for a
  spammer to hold.

## Schema

Two parallel tables, `user_identities` and `organizer_identities` — never a
shared cross-track table, never columns on `users`/`organizers`. Columns:
`id` (BigInteger PK), `user_id`/`organizer_id` (FK, `ondelete="CASCADE"`),
`provider` (String — a data value, not hardcoded to Google, so a second
provider is a data row, not a migration), `provider_sub` (String),
`created_at` (`DateTime(timezone=True), server_default=func.now()` — doubles
as `linked_at`, since insertion *is* the link event and unlink is a hard
`DELETE`, never an update).

`UniqueConstraint("provider", "provider_sub")` **per track** (one on each
table, not a global constraint) — required by the settled rule that the same
Google account may hold both a `User` and an `Organizer` row that never
merge. That constraint's backing index also serves the sign-in lookup; a
plain index on `user_id`/`organizer_id` serves the reverse "which providers
does this account have linked" query for the settings page. No backfill —
only new rows ever get `email_verified` written from this path.

## Cookies, CSRF, CSP — the full delta

- **Session cookie: unchanged**, `SameSite=Strict`, never set or read during
  the Google leg — only minted on the final same-origin callback response.
- **Two new cookies**, one per track: `oauth_state`
  (`Path=/api/auth/google/callback`) and `organizer_oauth_state`
  (`Path=/api/organizer/auth/google/callback`). Each: `SameSite=Lax`,
  httpOnly, Secure, 10-minute TTL, `itsdangerous`-signed payload `{state,
  code_verifier, track, exp}` with its own salt (never verifies as a
  magic-link or session token), stateless (no server-side table). These are
  the first non-`Strict` cookies in the app.
- **`CsrfOriginCheckMiddleware`: no exemption** — the callback is a GET,
  structurally outside `CSRF_UNSAFE_METHODS`.
- **`CORS_ORIGINS`: unchanged**, gains no third job — the code-for-token
  exchange is server-to-server (`httpx` from our backend to Google), never a
  browser CORS request.
- **CSP (`frontend/public/_headers`): zero change.** The redirect to
  `accounts.google.com` and the return are both top-level navigations,
  ungoverned by `script-src`/`connect-src`/`frame-src`.
- **Concurrent-login race** (two tabs, both starting Google sign-in): the
  second overwrites the first tab's state cookie; the first tab's callback
  then fails closed on state mismatch. Accepted as-is — fails safe, user
  retries.
- **Success redirect carries a `google_signin=<track>` marker** — the
  callback is a server-side redirect with no app JS running between the
  session cookie being set and the browser landing on the SPA, so the
  frontend's localStorage signed-in hint (otherwise only written in-page by
  the magic-link verify routes) would never get set and the route guard
  would bounce back to login. `main.tsx` consumes the marker synchronously,
  before the router's first render, then strips it from the URL.

## Design-system exception

The full-colour Google "G" mark is pictographic iconography, which C1 §1/§9
forbid, and per Google's branding guidelines it may not be made monochrome,
redrawn, or dropped. Recorded in `docs/design-system.md`'s Settled table as
a **class** exception — third-party identity-provider brand marks, mandated
by that provider's published branding terms, rendered as a local inline SVG
(never `<img>` — one fewer request, no `img-src` CSP surface, and the test
asserts it), scoped to the sign-in surface only. The mark is the flat
four-colour G (legacy icon-only asset), chosen over Google's current
gradient "super G" on legibility grounds at the 20px render size. This does
not reopen §9's general no-iconography rule elsewhere. The button itself
ships
`border-radius: 0` (composed from the shared `Button` module, unmodified) —
Google's written guidelines state no minimum size and no corner radius, so
this is a defensible reading against the prose, not a violation, even though
it visibly departs from Google's own shipped assets.

## Privacy / GDPR

No consent banner: the new state cookies are first-party, strictly
necessary, single-use — same ePrivacy Art. 5(3) category as the existing
session cookie. Google is an **independent controller** for the
token-issuance step (it decides its own purposes/means for verifying the
identity assertion); we become sole controller once `sub`/`email`/
`email_verified` is stored. Terms of Service need no change — it never
names a sign-in method today. Unlinking and account deletion hard-`DELETE`
the identity row; no soft-delete, no tombstone, no new deletion mechanism.

## Rollout

Organizer ships first (no real organizer users yet — the safe live-test
surface), consumer follows once proven; both use the same underlying
implementation, so this is a sequencing decision, not a divergent build.
Two independent flag pairs, `GOOGLE_SIGNIN_ORGANIZER_ENABLED`/
`GOOGLE_SIGNIN_CONSUMER_ENABLED` (backend) mirrored by
`VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED`/`VITE_GOOGLE_SIGNIN_CONSUMER_ENABLED`
(frontend), both defaulting off; the backend enforces its own flag
(endpoints 404 when off), not just a hidden button. No retroactive prompt
for existing users. Preview/dev environments never register with Google —
there is no staging backend, previews already proxy to the single
production API, and both flags default off, so previews simply never
exercise the flow.

## Consequences

- **A second cookie `SameSite` value now exists in the app.** Every future
  reader of `docs/security.md`'s cookie inventory must check `SameSite`
  per-cookie rather than assuming `Strict` app-wide.
- **`User.email_verified` gains a second writer.** The `auth.py` comment
  asserting single-writer status is stale and must be rewritten; any future
  code relying on "only a consumed magic link sets this" is now wrong.
- **A stable non-null `sub` becomes a second, independent lookup key** on
  both tracks, alongside the existing email-keyed lookup — two paths into
  the same row that must be kept consistent by any future auth change.
  Google's guarantee that `sub` is never reused makes this safe long-term.
- **Google's own new-user authorization rate limit** (undisclosed threshold,
  documented appeal at 5-business-day SLA) is an external dependency this
  app cannot see or control, on top of the app's own
  `RATE_LIMIT_GOOGLE_SIGNIN_*` buckets.
- **A fourth identity provider class is now precedented.** Apple, Microsoft,
  or Estonian Smart-ID/Mobile-ID can each add a `provider` value to the same
  two tables without a schema change — the `provider` column was
  deliberately not hardcoded to `"google"` for this reason, though no other
  provider is specced by this effort.
