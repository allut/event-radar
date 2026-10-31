# Security

What's in here: the middleware stack, rate limiting and its client key, URL and HTML sanitization, outbound SSRF guards, claim and webhook guards, the three auth tracks, and known gaps.

## Middleware Stack

`app/main.py` wires the stack. The backend is a pure JSON API with no first-party HTML or script surface, which shapes most of the choices below.

- **`ProxyHeadersMiddleware(trusted_hosts="*")` is registered last, so it runs outermost.** It rewrites `request.client` from `X-Forwarded-For` before anything logs or rate-limits. Without it, Render's proxy collapses every client into one bucket.
- **`trusted_hosts="*"` is an accepted ops dependency, not a code guarantee.** It's safe only while the process is reachable solely through Render's proxy, and Render's edge overwrites inbound `X-Forwarded-For`. Render publishes no stable egress CIDR to pin to. Re-derive this if a CDN, another proxy or a public port is ever added. The invariant comment in `main.py` says the same.
- **The `HOP-COUNT ASSUMPTION` comment next to `ProxyHeadersMiddleware` explains the two-hop topology.** See Client Key below.

### Security Headers

- **`add_security_headers` sets the `SECURITY_HEADERS` dict (`app/constants/security.py`) on every response.** That's CSP `default-src 'none'`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and `Cache-Control: no-store`.
- **`no-store` matters most for `POST /auth/verify`**, whose body carries a session token. Nothing a JSON API returns should sit in an intermediary cache.
- **HSTS (`HSTS_HEADER_*`) is added only outside development**, since it's safe only over HTTPS.
- **`/docs`, `/redoc` and `/openapi.json` exist only when `APP_ENV == "development"`.** The strict CSP would block their CDN assets in production anyway.

### Host Check

- **`HostCheckMiddleware` rejects an unexpected `Host` header outside development.** It wraps `TrustedHostMiddleware`. Nothing builds an absolute URL from `Host` today, so this is one-line hardening against cache poisoning.
- **`resolve_allowed_hosts()` (in `app/middleware.py`) builds the allowlist** from `settings.RENDER_EXTERNAL_HOSTNAME` (Render injects it; never set it by hand) plus `settings.BACKEND_URL`'s hostname. Local hostnames (`DEV_DB_LOCAL_HOSTS`) are dropped from both.
- **It fails open on purpose.** If both sources are empty or local, it logs an `ERROR` and the middleware isn't installed at all. An allowlist that rejects all public traffic would be a site-wide outage, which happened once when `BACKEND_URL` was left at its `localhost` default.
- **Every reject logs `LOG_EVENT_HOST_REJECTED`** with the offending `Host` and path. It wraps inside `ProxyHeadersMiddleware`, so the log carries the real client IP.
- **`/health` is exempt (`HOST_CHECK_EXEMPT_PATHS`).** Render's probe reaches the process over the private network with a rotating internal `Host`, and Starlette's `allowed_hosts` has no CIDR support.

### Request Body Ceiling

- **`MaxBodySizeMiddleware` rejects any body over `MAX_REQUEST_BODY_BYTES` with 413**, before a handler reads it. A `Content-Length` request fails up front; a chunked one fails mid-stream through a wrapped `receive`.
- **It sends the 413 response itself rather than raising `HTTPException`.** Starlette puts every `add_middleware` entry outside its `ExceptionMiddleware`, so a raised `HTTPException` would surface as a 500.
- **`IMAGE_UPLOAD_MAX_BYTES` is not a body ceiling.** It only bounds what the upload handler reads after Starlette has spooled the whole body.

### CORS and CSRF

- **`CORSMiddleware` keeps `allow_credentials=False`, even with cookie sessions.** The session cookie only travels through the SPA's same-origin `/api` proxy (`frontend/functions/api/[[path]].ts`), never a cross-origin fetch. Credentialed CORS would widen the attack surface for no gain.
- **`CsrfOriginCheckMiddleware` is the second CSRF layer, behind `SameSite=Strict`.** It rejects a mutating request (`CSRF_UNSAFE_METHODS`) whose `Origin` is present and not in `settings.CORS_ORIGINS` or `settings.FRONTEND_URL`.
- **A request with no `Origin` passes.** Browsers omit it on some simple navigations, and the legitimate server-to-server callers (the inbound-mail webhook, RFC 8058 one-click unsubscribe) never send one.
- **Widening `CORS_ORIGINS` silently widens CSRF trust too**, because the same setting seeds both allowlists.
- **Google sign-in's callback needs no CSRF exemption.** It's a `GET`, since the authorization code arrives on a 302's query string.

## Rate Limiting

- **Every endpoint carries `@limiter.limit(...)` with a `RATE_LIMIT_*` constant from `app/constants/rate_limits.py`**, authenticated ones included. Add both to any new endpoint, public or not.
- **`backend/tests/test_route_guards.py` enforces this and the auth rule on the live app.** A route with no track dependency must be listed in its `PUBLIC_ROUTES`, which makes going public a reviewed choice.
- **The limiter lives in `app/rate_limit.py`** so `main.py` and the routers can both import it without a cycle.
- **All other `/admin/*` routes in `app/routers/admin_*.py` share one bucket** through `limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")`. Per-route limits would let an attacker cycling every admin route multiply the nominal cap.
- **Admin queue list GETs and `GET /admin/counts` share a second bucket at `RATE_LIMIT_BROWSE`**, scope `RATE_LIMIT_SCOPE_ADMIN_READ`. Numbered paging plus a refetch after each action costs several reads per action, which the 10/minute action bucket can't absorb. Admin writes stay on `RATE_LIMIT_ADMIN`.
- **`admin_auth.py`'s three routes have their own buckets**, separate from the shared admin one. Login uses `RATE_LIMIT_ADMIN_LOGIN`. What admin login shares is the lockout counter; see Admin Console Auth.
- **Each claim-edit GET/PATCH pair shares a `shared_limit(RATE_LIMIT_SUBMIT, …)` bucket** (`claim_event_get`, `claim_event_patch`).
- **`GET /health` has no rate limit, by design.** Throttling Render's health probe risks the platform marking the service unhealthy.

### Client Key

`app/rate_limit.py::client_key()` keys every limit and every `client=` audit-log field. It ignores `request.client` because `ProxyHeadersMiddleware` takes the leftmost `X-Forwarded-For` entry, which any client can forge. With that key, every limit would be a no-op.

1. **Edge-forwarded IP (OWASP audit G-1).** Production is two hops: browser → Cloudflare Pages Function proxy → Render. The proxy strips inbound `X-Forwarded-For`/`X-Client-IP`, then sends `CF-Connecting-IP` as `X-Client-IP` with `X-Edge-Auth: <EDGE_SHARED_SECRET>`. `client_key()` trusts `X-Client-IP` only when that secret is set and matches (`secrets.compare_digest`).
2. **Fallback: the rightmost `X-Forwarded-For` entry**, appended by Render's proxy. That's right for a direct `onrender.com` caller. Behind Cloudflare without the secret, it collapses every visitor into Cloudflare's egress buckets.

- **The secret check is required because `onrender.com` is directly reachable.** An unauthenticated `X-Client-IP` would be forgeable.
- **`EDGE_SHARED_SECRET` lives in two places:** `render.yaml` (`sync: false`) and the Cloudflare Pages secrets. They must match.
- **IPv6 clients are bucketed by `/64` (`RATE_LIMIT_IPV6_PREFIX_LEN`).** Audit logs therefore show the prefix, not the full address.

## Secret Gates

- **`app/auth/utils.py::require_configured_secret()` guards every secret-gated surface:** the admin console login and session, and the inbound webhook's signature check.
- **With the secret unset, it fails open only when `APP_ENV == "development"` and `settings.ALLOW_INSECURE_DEV` are both true.** A dev-shaped `APP_ENV` alone never suffices, so a stray env var on a real deployment fails closed with 503.
- **The lifespan logs an `ERROR` when `APP_ENV` is development but `DATABASE_URL` points off-box** (`DEV_DB_LOCAL_HOSTS`). That is exactly the misconfiguration the double gate defends against.

## External URLs

The guard on a URL field depends on whether our server ever fetches it, not on which field it is. Apply the matching guard to any new URL field. Pipeline and organizer-portal docs link here for this rule.

### Rendered-Only URLs

- **`app/ingestion/http_client.py::safe_external_url()` is the scheme check** (`SAFE_URL_SCHEMES`). It stops stored XSS through `javascript:` or `data:` URLs. Scraped `image_url` uses it.
- **`safe_render_url()` guards every user-supplied URL that is only rendered:** organizer and claim-edit `url`, and organizer `image_url` before `check_image_host()` narrows it. It rejects backslashes, controls, whitespace, userinfo, explicit ports, non-http(s) schemes, and `%` or non-ASCII in the authority.
- **Callers store `safe_render_url()`'s re-serialized form, never the raw input.** Python's `urlsplit` and browsers disagree on `https://evil.com\@fienta.com/`, so a host pin checked on one parser must hold for the stored string.
- **A `user_submission` source's `event.url` is render-only.** Organizers edit their row through PATCH, so `refetch.py::_select_candidates` skips organizer rows. `adapter.py::insert_normalized_event()` picks `safe_external_url()` for that `source.kind`, since an organizer's ticketing domain is never on `ALLOWED_SOURCE_HOSTS`.

### Organizer Images

- **`app/routers/utils.py::check_image_host()` pins organizer and claim-edit `image_url` to our own Cloudinary account.** It calls `app/ingestion/http_client.py::own_cloudinary_url()`: the host must be in `ALLOWED_IMAGE_HOSTS` and the path under `/{CLOUDINARY_CLOUD_NAME}/image/upload/`. It fails closed when the cloud name is unset.
- **The path pin matters because `res.cloudinary.com` serves every account.** The daily digest embeds `image_url` as an `<img>`, so an arbitrary host would be an unconsented tracking pixel leaking each recipient's IP and open time.
- **The digest embeds an image only from our Cloudinary account or an `ALLOWED_SOURCE_HOSTS` host** (`app/email/digest.py::_embeddable_image_url`). Any other `image_url` gets the branded band instead.
- **Organizer and claim-edit images go through the signed `POST /organizer/events/image` upload.** The claim edit checks `image_url` only when the client sends it, so saving other fields never fails on an untouched scraped URL. Scraped sources are unaffected by the pin. `backend/scripts/clear_foreign_claim_images.py` clears the non-Cloudinary values claimants pinned before the host check existed, and leaves a pinned empty value alone.

### Fetched URLs

- **`safe_fetchable_url()` guards any URL our server fetches**, such as an adapter source's `event.url`, which the refetch job fetches daily. It adds an `ALLOWED_SOURCE_HOSTS` allowlist and `resolves_to_private_ip()` on top of the scheme check.
- **`resolves_to_private_ip()` requires every DNS answer to be globally routable.** It also handles IPv4-mapped IPv6 and `fec0::/10`.
- **Request-path fetches of a stored `Event.url` go through `http_get_stored_url()`.** That covers claim target resolution, claim verification, the claim-edit price check and the Piletilevi promoter fetch. It refuses anything but https on the default port to an allowlisted public host, and never follows redirects.
- **The guard sits on the fetch, not the edit.** A claimant may set `Event.url` to any host under their verified domain.
- **A guard `ValueError` in `fetch_locale_variants` skips that locale** rather than failing the whole event.

### Redirects

- **`http_get()` streams the body and raises `ResponseTooLargeError` past `HTTP_MAX_RESPONSE_BYTES` (16 MiB).** The cap counts decoded bytes, so a false or missing `Content-Length` and a compressed bomb both hit it. The error is an `httpx.HTTPError` that `_is_retryable` skips. The largest real page is Fienta's events API at about 4 MiB.
- **A client that follows redirects must pin every hop with `host_guard_hook`** (`http_client.py`). httpx's `follow_redirects=True` has no same-origin rule, and a pre-fetch check only sees the first URL.
- **The hook runs on each redirect hop**, checking `(scheme, hostname, port)` and re-running `resolves_to_private_ip()`. `fienta.py`, `html_base.py`, `refetch.py` and the publisher backfill client use it. Add it to any new adapter that follows redirects.

### Paginated Next URLs

- **A next-page URL from a response body is checked against the configured base host before it is fetched.** `FientaAdapter.fetch_organizer()` does this for `links.next`, and `organizer_sync.py::_fetch_city_scan()` for `pagination.next_page_url`. Both stop on a mismatch and keep what they have read. Copy the check into any new paginated adapter.

### Frontend URL Checks

- **`frontend/src/utils/html.ts::safeUrl()` repeats the scheme check as defense in depth.** Route every untrusted URL through it before an `href` or `src`.
- **Route-param ids go through `numericRouteId()`, and `API.*` builders `encodeURIComponent` every path segment.**

## Stored HTML

- **Every scraped rich-text field the frontend renders as HTML goes through `app/ingestion/sanitize.py::sanitize_html()` at ingest.** That's the localized `description` and `important_info`; `title` renders as escaped text. It's a strict `nh3` allowlist plus block-to-`<br>`, whitespace and Cloudflare email-decode passes.
- **`html_to_text()` (same module) is the plain-text form for every non-HTML consumer:** LLM prompts, keyword filters and fuzzy dedup. A new HTML-rendered field uses `sanitize_html()`; one that feeds an LLM or matcher uses `html_to_text()`.
- **`HtmlListingAdapter` subclasses are covered by default.** `html_base.py::extract_localized_text()` sanitizes its JSON-LD description before returning it.
- **Organizer-authored HTML gets a narrower allowlist.** `routers/utils.py::organizer_sanitize()` passes `ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS`/`_ATTRS` to `sanitize_html()`: only what the `RichTextEditor` toolbar can produce. Submit, edit and claim edits all call it.
- **An `attribute_filter` makes that allowlist the true ceiling.** nh3 otherwise keeps generic attributes like `title` and `lang`. `rel` is exempt because it's nh3's own injected `noopener noreferrer`.
- **The frontend's `sanitizeHtml()` (`frontend/src/utils/html.ts`) is defense in depth** at both `dangerouslySetInnerHTML` sites in `EventDetail.tsx`. The server-side pass is the real boundary.

## Untrusted Values

Scraped pages and LLM output are both untrusted input. These guards stop one bad value from poisoning a row or a batch.

- **Regex runs in linear time on untrusted text.** Edge-`<br>` trimming is the loop-based `_strip_edge_brs()`. `CURRENCY_AMOUNT_RE` bounds digit runs, and `price_context_digest` truncates input to `PRICE_CONTEXT_INPUT_MAX_CHARS`. Both have timing regression tests.
- **Numbers from LLMs and JSON-LD are bounded.** `parse_bounded_price()` accepts finite `0 <= x < PRICE_MAX_VALUE`, `normalize_currency()` enforces `VALID_CURRENCY_CODES`, non-finite quality is dropped, and refetched coordinates are bbox-gated.
- **Request-body prices share the same ceiling.** Every `price_*` field on an organizer, claim-edit or venue body is `app/routers/utils.py::PriceField`, which also refuses `Infinity`. A bare float would overflow `Numeric(10,2)` into a 500.
- **Validation replaces per-event savepoints.** Classify and refetch share one `AsyncSession` across concurrent workers, so a nested transaction there is unsafe.
- **LLM booleans go through `app/llm/router.py::strict_bool()`** with fail-safe defaults.
- **Why-go bullets are length-capped, stripped of URLs and emails, and explicit-filtered.** Venue-extract output may only reuse words from its input.
- **Moderation scans every localized value.** `content_flags()` takes `extra_explicit_texts`, and ingest, `apply_moderation_flags()`, venue-linked submit and the refetch backfill pass every `*_localized` value through `localized_text_values()`.

## Public Reads

- **Public event endpoints filter visibility in the query, not the serializer.** `app/events/queries.py::public_event_filter()` admits only published rows that are neither explicit nor a non-event. A hidden row's existence can't leak through a 200-versus-404 oracle.
- **Responses never expose internal metadata** such as `dedup_group_id`.

## Claims

[organizer-portal.md](organizer-portal.md)'s Event Claiming section has the claim flow. These are the guards on it.

- **A Series claim resolves only ingested, dedup-canonical, non-cancelled events** (`app/claims/pinning.py::series_claim_event_filter()`). Its path and body `event_id` must equal the resolved representative.
- **Pending claims resolve through one guarded UPDATE.** `app/claims/lifecycle.py::transition_pending_claim()` runs `WHERE status='pending' ... RETURNING` for admin grant, admin decline and `recheck_claim`. The loser of a race gets 409 and sends no email.

## Promotions

[organizer-portal.md](organizer-portal.md)'s Promotions section has the flows. These are the guards on the endpoints.

- **`/organizer/promotions/*` sits on the organizer track** (`get_current_organizer`) and returns 404 while `PROMOTIONS_OFFER_ENABLED` is off. Reads use `RATE_LIMIT_BROWSE`; request create and withdraw use `RATE_LIMIT_SUBMIT`.
- **Ownership is checked on every event and report read.** Another Organizer's event, request or Promotion is a 404, so ids cannot be probed.
- **Sold-out days leave the server as dates only.** Counts and other Organizers' figures never appear, and the per-day report carries no viewer identifiers.
- **`/admin/promotion-requests*` shares the admin buckets** (`RATE_LIMIT_ADMIN` for grant and decline, `RATE_LIMIT_BROWSE` for the list). The decline reason is stored and emailed as plain text, HTML-escaped in the email.

## Inbound Mail Webhook

- **`routers/webhooks.py::inbound_mail()` verifies Resend's Svix HMAC-SHA256** over `"{svix-id}.{svix-timestamp}.{raw body}"` with `settings.RESEND_WEBHOOK_SECRET`. The `SVIX_*` header constants live in `app/constants/email.py`.
- **Timestamps outside `WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS` (300s) are rejected.** Outside development, a missing secret fails closed through `require_configured_secret()`.
- **A replayed `svix-id` inside that window gets 401.** `_seen_webhook_ids` is a bounded in-memory LRU (`WEBHOOK_SEEN_IDS_MAX_ENTRIES`), the same pattern as the admin lockout.
- **The sender-domain check runs before the `RawInboundEmail` insert**, so a rejected sender's content is never stored.
- **`_sender_domain_allowed()` trusts the forgeable `From` header.** It's dormant while `NEWSLETTER_SENDER_ALLOWED_DOMAINS` is empty. Never add a domain without also requiring an SPF/DKIM/DMARC pass for it.

## Stripe Webhook

- **`POST /webhooks/stripe` (public `/api/webhooks/stripe`) sits outside all three auth tracks.** The `Stripe-Signature` over the raw body is the only credential. `routers/stripe_webhook.py` verifies it through `PaymentGateway.construct_event()` with a 300-second tolerance, and answers 400 for a bad, missing or stale one before any work.
- **An unset `STRIPE_WEBHOOK_SECRET` also answers 400.** The route never fails open, even in development.
- **It has its own `RATE_LIMIT_WEBHOOK_STRIPE` bucket,** generous because Stripe retries and bursts. There is no `Origin` header, so the CSRF check lets it through.
- **Replays are no-ops.** `app/promotions/stripe_events.py` inserts each event id into `processed_stripe_events` in the handler's transaction. A replay returns 200 with `duplicate`, and a failing handler rolls the id back so Stripe retries.
- **Handlers read current state and never assume order.** An `expired` after a `completed` changes nothing. A `completed` after the hold was voided is refunded in full and stays void.
- **A refund failure answers 500 on purpose.** The refund carries an idempotency key per Promotion, so Stripe's retry can't refund twice.

## Frontend CSP

`frontend/public/_headers` holds the SPA document's headers. [backend-ops.md](backend-ops.md)'s SPA Security Headers section describes the file's layout and the full policy. This section covers the parts that fail silently.

- **The inline pre-paint theme script in `index.html` runs under a `sha256-…` hash in `script-src`.** A static build can't mint per-request nonces, so a hash of the exact bytes is the only option without `'unsafe-inline'`.
- **Any edit to an inline `<script>` needs a new hash, or the browser silently refuses to run it.** Users see no console error.
- **`frontend/src/lib/csp.test.ts` is the drift guard.** It hashes every inline script in the real `index.html` and asserts each hash is in `public/_headers`' `script-src`.
- **The test also asserts `'unsafe-inline'` never sits beside a hash.** Browsers ignore hash sources once `'unsafe-inline'` is present, silently reopening the hole.
- **Cloudflare Pages reads `_headers` only from the build output**, so the test reads `frontend/public/_headers`, not a repo-root copy.
- **The dev server sends no CSP.** Verify a CSP change against the built `dist/index.html` and `dist/_headers` before shipping.

### Analytics and device access

- **The app loads no analytics or advertising script.** GA4 was removed because "cookieless" doesn't answer ePrivacy Art. 5(3), which covers any access to the device, not only cookies. The Estonian DPA (AKI) applies the consent rule directly and lists analytics among the trackers that need prior consent.
- **A new third-party measurement tool needs a consent prompt first.** Add it to the CSP and the privacy notice's section 4 only together with that prompt.
- **`click_external` and `view` are the one passive-signal exception.** `utils/eventActions.ts::trackExternalClick()` posts to our own `/feedback` endpoint, which needs the consumer session, so only a signed-in user's activity is recorded. It feeds their personalised feed, the function they asked for, so it is strictly necessary for it. Keep it out of any aggregate-reporting use.

## Dependency Audit

- **`.github/workflows/dependency-audit.yml` runs `pip-audit` and `npm audit --audit-level=moderate`** on every push and PR to `master` and weekly, to catch newly disclosed CVEs in pinned dependencies.

## Auth

There are three auth tracks: consumer, organizer and admin. `CONTEXT.md` defines them. Magic-link email is the base method, using `itsdangerous` tokens with no third-party auth provider.

### Track Separation

- **The three tracks never mix.** Each signs with its own salt and sets its own cookie, so one track's token can't verify on another. Consumer and organizer accounts live in separate tables.
- **The organizer track mirrors the consumer one.** [organizer-portal.md](organizer-portal.md)'s Auth section has its salts, tables and cookie path.

### Tokens

- **Tokens are signed, not encrypted.** Every token in `app/auth/tokens.py` is an `itsdangerous.URLSafeTimedSerializer` payload, so anyone holding the cookie can read its claims. No current claim is secret. Never put a secret in a token payload; store it server-side instead.
- **Magic-link generation and checks live in `app/auth/tokens.py`; delivery is `app/auth/email.py`** through Resend.
- **The session token is the credential and isn't stored server-side.** There's no per-token row to delete; revocation works through the version claim below.

### Magic Links

- **The email link carries the token as `?token=`, but the frontend strips it before verifying.** `AuthVerify.tsx` calls `history.replaceState`, then sends `POST /auth/verify` with the token in the body (`VerifyTokenBody`). The token never lands in a request line, an access log or browser history.
- **What's left is the first click itself**, which a mail client may keep in history or a `Referer`. A landing-page redirect to close it wasn't worth the extra click.
- **Each magic link is single-use and short-lived.** It's consumed with an atomic `UPDATE ... WHERE used_at IS NULL ... RETURNING`, and expires after `MAGIC_LINK_TTL_MINUTES`.
- **`POST /auth/request-link` and its organizer twin have a per-email cooldown.** Within `MAGIC_LINK_RESEND_COOLDOWN_SECONDS` of an unused link, they return the same 200 body but create and send nothing. It's computed from `expires_at`.
- **The cooldown guards the Resend quota per account; the rate limit guards it per IP.**

### Sessions

- **The session is an httpOnly, Secure, `SameSite=Strict` cookie** (`SESSION_COOKIE_NAME`, `Path=/api`), read by `app/auth/dependencies.py::get_current_user`. TTL is `SESSION_TTL_DAYS`; both TTLs default from `shared/app-config.json`.
- **The cookie keeps the credential away from any XSS payload.** A narrow first-party script surface was only a probability argument; a compromised frontend dependency still runs under `script-src 'self'`. [ADR 0001](adr/0001-session-tokens-in-httponly-cookies.md) has the full trade-off.
- **The cookie opens a CSRF surface, closed by `SameSite=Strict` plus the Origin check.** `Strict` costs nothing here because the SPA has no server-rendered flow needing the cookie on a cross-site navigation.
- **The client sees only a boolean signed-in hint in `localStorage`** (`frontend/src/lib/auth.ts`). It grants nothing, and its `storage` event propagates sign-out across tabs.
- **Sign-out is a server call.** JavaScript can't clear an httpOnly cookie, so `POST /auth/logout` clears it for the current device.

### Session Revocation

- **Each session token embeds a `v` claim equal to `users.session_token_version` at issue time.** `get_current_user` rejects any token whose `v` no longer matches.
- **`POST /auth/logout-all` bumps that counter** with an atomic `UPDATE ... RETURNING`, invalidating every session, the caller's included. This counter is the only server-side state in the auth flow.

### Email Verification Gate

- **`users.email_verified` is false until someone proves the address.** `routers/auth.py::_get_or_create_user` inserts a `User` row on an unauthenticated `POST /auth/request-link`, before the address is shown to be reachable.
- **Two writers set it, each in the same transaction as session issuance:** `verify_magic_link` on a consumed link, and Google sign-in's authoritative branch in `_apply_google_linking_gate`. A false row is provably one nobody has signed into.
- **That guarantee holds from migration `0024_users_email_verified.py` on.** It backfilled every older row to true, because the purged magic-link history made real status underivable.
- **`build_daily_feeds` (`app/ranking/daily_feed.py::_verified_user_ids`) and `send_daily_digests` (`app/email/digest.py`) both filter on it.** An anonymous request with someone else's address can't enroll them in the digest.

### Digest Unsubscribe

- **`app/routers/unsubscribe.py` flips `email_digest_opt_in` without a login.** Each digest carries a per-recipient `itsdangerous` token with its own salt (`AUTH_UNSUBSCRIBE_SALT`), valid for `UNSUBSCRIBE_TOKEN_TTL_DAYS` so old emails keep working.
- **The visible link opens the frontend `/unsubscribe?token=` page**, which strips the token from the address bar, POSTs on mount and offers Undo.
- **`send_digest_email` also emits RFC 8058 `List-Unsubscribe` and `List-Unsubscribe-Post` headers.** They use an absolute `settings.BACKEND_URL` URL, since mail providers call it server-side.

Accepted residual risks, all bounded because the token only toggles a reversible preference:

- **The token can't be revoked.** It carries no version claim, so a leaked one stays valid for its full TTL.
- **The token is a query parameter on both POST routes.** It can appear in edge logs, though never in Axiom: `app/logging_config.py::_AccessPathStripFilter` strips access-log query strings. The magic-link token moved into a body because it grants a session; this one doesn't.
- **The same token authorizes `POST /email/resubscribe`**, so a leaked token can re-opt-in someone who unsubscribed.

### Email Ad Consent Withdrawal

- **`POST /email/ads-off?token=` withdraws Email ad consent without a login.** The digest keeps coming. The token has its own salt (`AUTH_ADS_OFF_SALT`) and `UNSUBSCRIBE_TOKEN_TTL_DAYS`, so it can't unsubscribe the digest or be replayed the other way. Errors match `/email/unsubscribe`.
- **`POST /email/ads-on?token=` is the undo.** It grants again at the current wording version only for a user whose latest consent-log row is an `email_link` withdrawal; anyone else gets the invalid-link 400. It returns 409 while the digest or `PROMOTIONS_SLOTS_ENABLED` is off.
- **The email link opens the frontend `/email-consent-off?token=` page**, which strips the token, POSTs `ads-off` on mount and offers Undo (`ads-on`). The path avoids "ad" so filter lists don't hide it.
- **Both routes use `RATE_LIMIT_UNSUBSCRIBE` and the normal Origin check.** The token stays a query parameter, like unsubscribe's.

### Google Sign-In

Both tracks offer Google sign-in alongside magic links, through a server-side OAuth 2.0 authorization-code flow with PKCE (S256). There's no Google JavaScript or widget, only a top-level redirect. [ADR 0002](adr/0002-google-sign-in-oauth-pkce.md) has the rationale and rejected alternatives.

- **Each track has its own flag**: `GOOGLE_SIGNIN_CONSUMER_ENABLED` and `GOOGLE_SIGNIN_ORGANIZER_ENABLED`. With a flag off, that track's start and callback routes return 404.
- **`GET …/google/start` signs `{state, code_verifier, track}` into a state cookie** (`tokens.py::generate_oauth_state_token`, salt `AUTH_OAUTH_STATE_SALT`). The TTL is `OAUTH_STATE_TTL_MINUTES`.
- **`verify_oauth_state_token(..., track=…)` binds the state to its track.** A consumer state token never verifies on the organizer callback, and a dedicated test proves it.

#### Callback

1. Verify and delete the single-use state cookie.
2. Exchange the code server-to-server with `http_post`.
3. Verify the ID token's `iss`, `aud` and RS256 signature with PyJWT's `PyJWKClient` against Google's JWKS.
4. Hand the verified `{sub, email, email_verified, hd}` to the track's linking gate.
5. Mint a normal session cookie, as `POST /auth/verify` does.

- **Every failure redirects to the login page with an error code, never a 500.** That covers bad state, denied consent, and exchange or verification failures.
- **A callback that loses the identity-link race rolls back and uses the winner's identity.** A double-click or two tabs on the same Google account must not surface an `IntegrityError` as a 500.
- **`sub` is the only match key.** `Organizer.email` is never written from the token.
- **`PyJWKClient` bypasses `http_get`'s retry wrapper.** [conventions.md](conventions.md) lists that bypass and its reason.

#### State Cookies

- **The state cookies are the app's only `SameSite=Lax` cookies:** `oauth_state` (consumer) and `organizer_oauth_state`. The cross-site redirect back from Google doesn't carry a `Strict` cookie. Check `SameSite` per cookie, never app-wide.
- **Each state cookie's `Path` is its track's callback route**, so it's read on exactly one route.

#### Linking Gate

`_apply_google_linking_gate` in `app/routers/auth.py` and `app/routers/organizer_auth.py` decides which account, if any, a verified identity attaches to.

- **An existing identity row signs in directly.**
- **A new identity auto-links only where Google is authoritative for the address:** `@gmail.com`, `@googlemail.com` or an `hd` claim, each with `email_verified: true`. Google's own guidance says `email_verified` isn't authoritative elsewhere; the mailbox may have changed hands since.
- **Every other address goes through one confirmation magic link** (`pending_google_sub` on the link row) before any identity row exists.
- **A non-authoritative address with `email_verified: false` is dropped** as `GOOGLE_SIGNIN_OUTCOME_UNVERIFIED_EMAIL`. No row, no email, just a `google_error=verification_failed` redirect.
- **An unverified `User` row is no exception.** Its email address is the thing being claimed, so a non-authoritative identity can't absorb it.
- **Only the consumer track also flips `User.email_verified`** on auto-link. `Organizer` has no such column.

#### Confirmation Link

The confirmation link must not attach an attacker's Google account to a victim who clicks it.

- **It has its own email.** `send_google_link_confirmation()` (`app/auth/email.py`, builders in `app/email/identity_link.py`) says a Google account is about to be linked and to ignore the message if that wasn't them.
- **It's bound to the browser that started the flow.** The callback sets a `SameSite=Strict` binding cookie (`google_link_binding` / `organizer_google_link_binding`) carrying `{sub, track}`, its own salt, and the verify route as `Path`.
- **The binding cookie must match.** `verify_magic_link` and `verify_organizer_magic_link` attach `pending_google_sub` only when the cookie's `sub` matches. Elsewhere the link is a plain sign-in that links nothing. Every pending-link verify clears the cookie.
- **`send_identity_linked_notice()` emails the owner whenever Google links to an existing account.** That covers a confirmation link or an authoritative auto-link. It's best-effort, and a brand-new Google-created account gets none.
- **Residual trade-off:** someone who starts on one device and opens the email on another is signed in without the link. They can retry on one device.

#### Unlinking

- **`DELETE /users/me/identities/{provider}` and `DELETE /organizer/profile/identities/{provider}` hard-delete the identity.** There's no last-factor guard, since magic links always remain.
- **Unlinking bumps `session_token_version` and re-issues the caller's cookie.** It signs out every other device, like `logout-all`.

### Admin Console Auth

- **`app/routers/admin_auth.py` is a third track: password plus a required TOTP code (RFC 6238)** against `ADMIN_USERNAME`/`ADMIN_PASSWORD`. It's the only admin credential surface. HTTP Basic was removed because it never checked TOTP, so the password alone bypassed the second factor.
- **Every `/admin/*` route requires the session cookie (`get_current_admin`)**, including counts and stats. A password-only route would be an oracle that the per-IP lockout can't slow across many IPs.
- **The default `ADMIN_USERNAME` (`"admin"`) is refused outside development** (`admin_lockout.py::admin_username_disabled`). A well-known username halves the pair an attacker has to guess.
- **`app/auth/totp.py::check_totp_code` rejects any time step at or before the last accepted one.** `record_totp_step()` records a step only after the whole login succeeds. An observed code can't mint a second session inside its `ADMIN_TOTP_VALID_WINDOW` drift window.
- **The cookie is httpOnly, Secure, `SameSite=Strict`** (`ADMIN_SESSION_COOKIE_NAME`, `Path=/api/admin`), minted by `tokens.py::generate_admin_session_token` with its own salt `AUTH_ADMIN_SESSION_SALT`.
- **It carries no id or version claim, because there's no admins table.** So there's no per-session revocation, and `ADMIN_SESSION_TTL_SECONDS` (12h) is shorter than the consumer TTL to compensate.
- **The token's `e` (epoch) claim is an HMAC-SHA256 under `SECRET_KEY` of `ADMIN_SESSION_EPOCH`, `ADMIN_PASSWORD` and `ADMIN_TOTP_SECRET`** (`tokens.py::_admin_session_epoch`). Rotating any of them invalidates every admin session, with no separate step. The key matters because the payload is signed, not encrypted: a bare hash would let anyone holding the cookie guess the password offline.
- **TOTP enrollment is a local script, `backend/scripts/admin_totp_enroll.py`.** There are no backup codes, so a lost authenticator means rotating `ADMIN_TOTP_SECRET`.

#### Lockout

- **`app/auth/admin_lockout.py` locks a `client_key()` out (429) for `ADMIN_AUTH_LOCKOUT_SECONDS` after `ADMIN_AUTH_MAX_FAILURES` consecutive failed logins.** A wrong password or a wrong or reused TOTP code both count.
- **The lockout is in-memory and resets on deploy.** That matches the single-process design, and it supplements a strong `ADMIN_PASSWORD` rather than replacing it.
- **Failed logins log `username_ok`, never the attempted username.**
- **[backend-ops.md](backend-ops.md)'s Admin Endpoints section covers the console's routes.**

## Known Gaps

- **Open gaps live in [security-audit.md](security-audit.md)'s Open Findings**, each with its recommended fix. The audit ledger is their one home, so a fix updates one file.
