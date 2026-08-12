# Session tokens move from localStorage to httpOnly cookies

Status: accepted

Session tokens for both the consumer and organizer tracks were stored in
`localStorage`, which `docs/security.md` recorded as a *knowingly accepted*
residual risk — the XSS surface is narrow (CSP `script-src 'self'`, DOMPurify,
`nh3` at ingest), so the exposure was judged tolerable. We reopened that
decision and moved the session token into an httpOnly + Secure +
`SameSite=Strict` cookie, because the mitigation was a probability argument
against a total consequence (a single XSS is a silent, full account takeover
for the token's 2-day life), and because a supply-chain compromise of any
frontend dependency executes happily under `script-src 'self'`. Being
pre-soft-launch made the migration free: no live sessions to strand.

## Considered options

- **Hybrid refresh cookie + in-memory access token** — rejected. It exists to
  solve revocation, which the `session_token_version` (`"v"`) claim already
  solves instantly; it would add a whole token lifecycle for nothing.
- **In-memory token only** — rejected. Every reload signs the user out, which
  defeats the point of magic-link auth.
- **Keep `localStorage` and shorten the TTL** — rejected. Shrinks the window
  without closing the gap.
- **Double-submit CSRF token** — rejected in favour of `SameSite=Strict` plus a
  server-side Origin check, which is ~15 lines and needs no client plumbing for
  a same-origin SPA behind the Vercel `/api` rewrite.
- **Dual-accepting `Authorization: Bearer` during a transition** — rejected.
  There is nothing to transition from, and it would leave two auth paths in
  every dependency permanently.
- **A dev-only Bearer bypass for Swagger** — rejected. A dev-only auth bypass
  reachable through one misconfigured env var is the classic catastrophe;
  Swagger is instead proxied to be same-origin so the cookie applies.

## Consequences

- **CSRF became a real surface** where a Bearer header made it structurally
  impossible. Mitigated in two layers: `SameSite=Strict` (free here — the SPA
  has no SSR, so no flow needs the cookie on a cross-site navigation) and a
  middleware rejecting mutating requests whose `Origin` is present and not
  trusted. Absent `Origin` is allowed, because browsers always send it on
  cross-site POSTs while the legitimate server-to-server callers
  (`/webhooks/inbound-mail`, the RFC 8058 one-click unsubscribe) never do.
- **Sign-out became a server concept.** JS cannot clear an httpOnly cookie, so
  `POST /auth/logout` (and its organizer mirror) now exist alongside
  `logout-all`, making "sign out" and "sign out everywhere" two explicit
  operations rather than one client-side and one server-side.
- **The client can no longer see whether it is signed in.** A boolean
  *signed-in hint* in `localStorage` carries that fact — it grants nothing, and
  because it lives in `localStorage` the existing cross-tab `storage` event
  propagation keeps working unchanged.
- **`CORS_ORIGINS` now has two jobs**: CORS, and the Origin check's trusted
  list. Widening it for a CORS reason silently widens CSRF trust.
- **The organizer cookie is scoped to `Path=/api/organizer`.** An organizer
  endpoint added outside `/organizer/*` will silently 401.
- **`Secure` is unconditional**, so real-device testing over a plain-HTTP LAN
  address no longer works; use an HTTPS tunnel and add its origin to
  `CORS_ORIGINS`.
