"""Every slowapi rate-limit string, kept side by side so they are tuned together."""

# Per-IP rate limits (slowapi / limits syntax: "<count>/<period>"). These guard
# auth + webhook endpoints against enumeration, quota-exhaustion, and email-bombing
# attacks that the per-email cooldown (request-link) doesn't cover — see main.py::limiter.
RATE_LIMIT_AUTH_REQUEST_LINK = "10/minute"
RATE_LIMIT_AUTH_VERIFY = "30/minute"
RATE_LIMIT_WEBHOOK_INBOUND_MAIL = "60/minute"
# Stripe webhook (routers/stripe_webhook.py): its own bucket, generous because Stripe
# retries and bursts, and every request is signature-verified before any work.
RATE_LIMIT_WEBHOOK_STRIPE = "300/minute"
# Organizer Promotion checkout start and Äriregister lookup
# (routers/organizer_promotion_checkout.py): session-gated; a checkout start
# writes a row and calls Stripe, a lookup calls the register (cached 24 h).
RATE_LIMIT_PROMOTION_CHECKOUT = "10/minute"
RATE_LIMIT_PROMOTION_REGISTRY_LOOKUP = "20/minute"
# Public digest unsubscribe/resubscribe (routers/unsubscribe.py) — no auth, token-verified.
RATE_LIMIT_UNSUBSCRIBE = "30/minute"
# Public contact form (routers/contact.py) — no auth; tight cap since each hit sends an email.
RATE_LIMIT_CONTACT = "3/minute"
# Organizer event submission/edit/image-upload (routers/organizer_events.py) —
# modeled on RATE_LIMIT_CONTACT: authenticated, but each hit runs a full
# inline classify+publish pass, so keep it tight per-IP; the DB-backed
# ORGANIZER_DAILY_SUBMISSION_CAP is the per-organizer ceiling.
RATE_LIMIT_SUBMIT = "10/minute"
# Authenticated organizer contact form (routers/organizer_contact.py) —
# modeled on RATE_LIMIT_CONTACT: session-gated, but each hit still sends an
# email, so keep the same tight per-IP cap.
RATE_LIMIT_ORGANIZER_CONTACT = "3/minute"
# Organizer event-claiming endpoints (routers/organizer_claims.py) — modeled
# on RATE_LIMIT_SUBMIT: a claim create/recheck hit runs live verification
# I/O (Fienta/DNS-TXT/Piletilevi fetch), so keep it tight per-IP; the
# DB-backed ORGANIZER_DAILY_CLAIM_CAP is the per-organizer ceiling.
RATE_LIMIT_CLAIM = "10/minute"

# Public read endpoint — generous enough for normal browsing while throttling
# ID-enumeration / scraping abuse (GET /events/{id} takes no auth).
RATE_LIMIT_EVENTS_DETAIL = "120/minute"
# Admin Basic-auth surface — applied via limiter.shared_limit(..., scope="admin")
# so every /admin/* action route shares ONE bucket per client, not one each
# (a per-route @limiter.limit would let an attacker cycling all admin routes
# attempt far more than this per minute). Pair with a strong ADMIN_PASSWORD.
RATE_LIMIT_ADMIN = "10/minute"
# Shared-limit scope for the admin queue list GETs and GET /admin/counts
# (spec #551), which run at RATE_LIMIT_BROWSE instead: a numbered pager plus
# refetch-after-action costs several reads per admin action, more than the
# 10/minute action bucket allows. Still ONE bucket per client across every admin read, for the same
# route-cycling reason as RATE_LIMIT_ADMIN's scope.
RATE_LIMIT_SCOPE_ADMIN_READ = "admin_read"

# Authenticated feedback writes — generous cap on a per-signal DB write.
RATE_LIMIT_FEEDBACK = "60/minute"
# POST /reports — content-moderation write, tighter than RATE_LIMIT_FEEDBACK
# since it creates a row an admin must triage (see LOG_EVENT_REPORT_SUBMITTED).
RATE_LIMIT_REPORT = "10/minute"
# Authenticated state-changing writes (onboarding persona, settings GET/PATCH) —
# damps self-inflicted DB write spam from a valid session token.
RATE_LIMIT_AUTHENTICATED_WRITE = "30/minute"
# Tighter cap for logout-all: bumps session_token_version, revoking every
# issued session token (including the caller's own) — a higher-value target
# than ordinary writes.
RATE_LIMIT_LOGOUT_ALL = "10/minute"
# Plain "sign out" (clears only the caller's own cookie, no session_token_version
# bump) — lower stakes than logout-all, so a more generous cap; shared by both
# the consumer and organizer logout endpoints, mirroring RATE_LIMIT_LOGOUT_ALL.
RATE_LIMIT_LOGOUT = "20/minute"
# POST /admin/auth/login — a password+TOTP brute-force surface distinct from
# RATE_LIMIT_ADMIN (which only gates already-authenticated /admin/* routes);
# ADMIN_AUTH_MAX_FAILURES lockout is the consecutive-failure damper on top.
RATE_LIMIT_ADMIN_LOGIN = "10/minute"
# Authenticated /explore browsing — mirrors RATE_LIMIT_EVENTS_DETAIL; live filter
# changes can fire a request per keystroke/chip-toggle, so this stays generous.
RATE_LIMIT_BROWSE = "120/minute"
# Public, unauthenticated landing-page showcase (GET /public/showcase). No auth,
# so throttle scraping abuse; generous enough for real visitors loading the page.
RATE_LIMIT_PUBLIC = "60/minute"

RATE_LIMIT_GOOGLE_SIGNIN_START = "20/minute"
RATE_LIMIT_GOOGLE_SIGNIN_CALLBACK = "30/minute"

# Rate-limit bucket width for IPv6 clients (one subscriber is typically a /64).
RATE_LIMIT_IPV6_PREFIX_LEN = 64
