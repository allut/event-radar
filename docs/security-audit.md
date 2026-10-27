# Security Audit Ledger

What's in here: the commit the last OWASP audit covered, the guards that already enforce mechanical rules, the risks accepted by design, and the open findings.

## Baseline

- **The last audit swept every source file at commit `dd99bf12`.** The next one audits `git diff dd99bf12..HEAD` plus the callers of changed code, unless a full sweep is asked for.
- **The `security-audit` skill runs the audit and rewrites this file at the end.** It moves the baseline, drops fixed findings and adds new ones.
- **[security.md](security.md) describes the controls themselves.** This file tracks only audit state.

## Guards

These rules fail a check, so an audit skips hunting them where the guard reaches.

- **`backend/tests/test_route_guards.py` fails a route with no rate limit, no auth dependency, or the wrong track's dependency.** A route meant to be public goes in its `PUBLIC_ROUTES` on purpose.
- **`backend/tests/routers/test_price_fields.py` fails a request-body `price_*` field that isn't `backend/app/routers/utils.py::PriceField`.** Bare floats overflow `Numeric(10,2)` into a 500.
- **`backend/tests/test_csrf_middleware.py` and `backend/tests/test_security_headers.py` pin the Origin check and the API's response headers.**
- **`frontend/src/lib/csp.test.ts` fails when an inline script's hash is missing from `frontend/public/_headers`.**
- **`.github/workflows/dependency-audit.yml` runs `pip-audit` and `npm audit` on every push and weekly.** Both run locally too, since `pip-audit` is in `backend/requirements-dev.txt`.

## Accepted by Design

An audit leaves these out of its report.

- **Every residual risk [security.md](security.md) calls accepted stays out.** That covers the `trusted_hosts="*"` proxy assumption, Origin-less requests passing CSRF, stateless sessions, unsubscribe-token reuse and in-memory lockouts.
- **A verified Organizer's submission publishes before admin review.** Only an unverified Organizer's events wait; `backend/app/publish.py::publish_pending` holds them.
- **`backend/app/routers/utils.py::organizer_sanitize()` runs inline in the async handler**, not in a threadpool. Field `max_length` bounds the work.
- **Scraped LLM input is untrusted by design.** Outputs are validated field by field instead; see [security.md](security.md)'s Untrusted Values section.

## Open Findings

Ranked by severity. Each carries the fix the audit recommended.

### Medium

- **A claimant's `image_url` can be any https host, and the digest embeds it as `<img>`.** That is a tracking pixel leaking each recipient's IP and open time. Fix: in `backend/app/email/digest.py`, embed only our Cloudinary path or an `ALLOWED_SOURCE_HOSTS` host.
- **The claim edit itself still takes a free-text `image_url`.** Pinning it to Cloudinary waits on an approved upload control in the claim edit UI.

### Low

- **`GET /events/{id}?ref=ad` bumps Promotion open counters on every hit.** It is anonymous, skips `is_bot_user_agent()`, and the counts reach paying advertisers. Fix: count once per `client_key()`, Promotion, day and column, and skip bots.
- **Outbound `backend/app/ingestion/http_client.py::http_get()` has no streaming byte cap on response bodies.** Every test mocks `client.get`, so the cap needs its own change.
- **The admin session's `e` claim is a truncated SHA-256 over the admin password and TOTP secret.** The payload is signed, not encrypted. Fix: derive it as an HMAC under `SECRET_KEY` in `backend/app/auth/tokens.py::_admin_session_epoch()`.

### Info

- **Checkout binds neither the registry code nor the billing email to the Organizer.** Any Organizer can name any active company on a Stripe invoice and send it anywhere. This needs a product decision.
- **`PROMOTION_REGISTRY_CODE_RE` accepts Unicode digits**, since `\d` isn't ASCII-only. Fix: `[0-9]{8}` with `fullmatch`.
