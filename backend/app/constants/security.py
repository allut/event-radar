"""Security gates: secret checks, host/SSRF allowlists, CORS/CSRF, security headers, HTML sanitization, feature/setting names."""

# require_configured_secret() call-site literals for the ADMIN_PASSWORD gate —
# duplicated across get_current_admin (auth/dependencies.py) and
# admin_login (routers/admin_auth.py); named so both stay in sync.
SETTING_NAME_ADMIN_PASSWORD = "ADMIN_PASSWORD"
FEATURE_ADMIN_ENDPOINTS = "Admin endpoints"

# Minimum SECRET_KEY length Settings will accept (OWASP audit F7) — 32 bytes
# is what `python -c "import secrets; print(secrets.token_hex(32))"` (the
# documented generation command) produces as a hex string. render.yaml's
# generateValue:true already clears this bar; the floor exists so a hand-set
# dev/self-hosted key can't start the app with something trivially guessable.
SECRET_KEY_MIN_LEN = 32
# The literal placeholder shipped in .env.example — rejected outright so a
# copy-paste-without-editing mistake fails at startup instead of signing
# every token with a value visible in the public repo.
SECRET_KEY_PLACEHOLDER_PREFIX = "change-me-"

# Paths exempt from HostCheckMiddleware's Host-header validation (app/middleware.py).
# Render's health probe reaches this process over the private network, so its
# Host header is the instance's rotating internal address, not BACKEND_URL's
# hostname — allowlisting it isn't viable since Starlette's allowed_hosts has
# no CIDR support.
HOST_CHECK_EXEMPT_PATHS: frozenset[str] = frozenset({"/health"})

# Starlette TrustedHostMiddleware's fixed rejection body — app/middleware.py's
# HostCheckMiddleware matches this to tell an actual Host-header reject apart
# from an ordinary downstream 400 (bad token, malformed body, ...) passing
# through the same wrapped `send`. A future Starlette wording change would
# just silently stop logging rejects, never start false-logging normal 400s
# — an acceptable degrade.
TRUSTED_HOST_REJECT_BODY = b"Invalid host header"

# SSRF guard (backend-only, not needed by the frontend): hostnames a source's
# event.url is allowed to carry. event.url is untrusted — it comes from
# parsed third-party page/API content — and is later fetched server-side by
# both the per-source detail-page crawl and the daily refetch job
# (app/ingestion/refetch.py), so it must be pinned to known-good hosts rather
# than trusted at face value. Suffix-matched (see host_is_allowed) so a
# legitimate subdomain (e.g. "en.fienta.com") still passes.
# TTL for resolves_to_private_ip()'s host->verdict cache (http_client.py). One
# ingest run fetches many events from the same 1-4 hostnames — each uncached
# call is a thread hand-off plus a real DNS round trip. Short enough that a
# DNS-rebinding attack against an allowlisted host is still caught well within
# one scheduled run's lifetime; the check was already documented as
# TOCTOU-racy against httpx's own re-resolution (see resolves_to_private_ip's
# docstring), so this doesn't weaken that existing trade-off.
DNS_RESOLVE_CACHE_TTL_SECONDS: float = 300.0
# Distinct hostnames whose verdict stays cached; the oldest goes first. An
# allowlisted domain's subdomains are scraped input, so the key space is open.
DNS_RESOLVE_CACHE_MAX_ENTRIES = 256

ALLOWED_SOURCE_HOSTS: frozenset[str] = frozenset(
    {
        "fienta.com",
        "www.piletilevi.ee",
        "kumu.ekm.ee",
        "concert.ee",
        "tallinn.fotografiska.com",
        "kultuurikatel.ee",
        "nominatim.openstreetmap.org",
    }
)

# SAFE_URL_SCHEMES, HTML_SANITIZE_ALLOWED_TAGS, HTML_SANITIZE_ALLOWED_ATTRS imported
# from app._generated.shared_constants (shared/app-config.json → generate_shared.py).
# Schemes accepted for ingested event url/image_url — anything else (javascript:,
# data:, vbscript:, etc.) is dropped at ingest time to prevent stored XSS via
# untrusted source content rendered into <a href>/<img src>.
# HTML allowlist for description / important_info fields; nh3 passes plain text safely.
# Block-level wrappers that carry no allowlisted tag of their own. Some sources
# (e.g. Piletilevi) encode every line as a bare <div>; nh3 strips disallowed tags
# without inserting any separator, collapsing block boundaries into run-on text.
# sanitize_html converts these to <br> before sanitizing so line structure survives.
HTML_BLOCK_TAGS_TO_BREAK: frozenset[str] = frozenset({"div"})
# Cap runs of consecutive <br> (from nested/empty wrapper divs) at this many.
HTML_SANITIZE_MAX_CONSECUTIVE_BR = 2

# Line/block-boundary tags within HTML_SANITIZE_ALLOWED_TAGS. A text node
# touching one of these on a side has its whitespace stripped on that side
# (post-collapse) so lines don't visibly start/end with a stray space under
# the frontend's white-space: pre-wrap. Excludes inline tags (a, b, em, i,
# span, strong, u) — a word-boundary space like "text <a>link</a> more" must
# survive.
HTML_BLOCK_BOUNDARY_TAGS: frozenset[str] = frozenset(
    {"br", "p", "h3", "h4", "li", "ul", "ol", "blockquote"}
)

# Organizer-submission boundary allowlist (routers/organizer_events.py) — narrower
# than the shared ingestion allowlist above, and backend-only (not generated into
# shared/): it tracks the Tiptap toolbar's exact extension list (bold/italic/
# underline/bulletList/orderedList/link/heading 3-4/blockquote, no color/span), so
# the frontend never needs this set independently.
ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS: frozenset[str] = frozenset(
    {"p", "br", "strong", "em", "u", "ul", "ol", "li", "a", "h3", "h4", "blockquote"}
)
ORGANIZER_HTML_SANITIZE_ALLOWED_ATTRS: dict[str, set[str]] = {"a": {"href"}}

# Hosts an organizer-submission event.image_url is allowed to point at — the
# signed Cloudinary upload endpoint (POST /organizer/events/image) always
# returns a res.cloudinary.com secure_url. Without this, an organizer could
# set image_url to an arbitrary https host; the digest embeds it as an <img>,
# turning it into a tracking pixel that leaks each recipient's IP/open-time to
# a third party the recipient never consented to. Scraped (non-organizer)
# sources are unaffected — this only gates SOURCE_KIND_USER_SUBMISSION.
# The host is necessary but not sufficient: _check_image_host also requires
# CLOUDINARY_DELIVERY_PATH_TEMPLATE for the configured account.
ALLOWED_IMAGE_HOSTS = frozenset({"res.cloudinary.com"})

# Whole-request body ceiling (app.middleware.MaxBodySizeMiddleware) — above
# IMAGE_UPLOAD_MAX_BYTES (the largest legitimate body today) since multipart
# form overhead adds a little on top of the raw file. Nothing else in the
# stack caps request size: Starlette receives and spools the full body before
# any handler-level check (e.g. IMAGE_UPLOAD_MAX_BYTES) ever runs.
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MiB

# Deprecated IPv6 site-local range; ipaddress.is_global still reports it global.
SITE_LOCAL_IPV6_CIDR = "fec0::/10"

ERROR_CSRF_ORIGIN_MISMATCH = "Origin header does not match a trusted origin."

# CORS — restricted to the methods/headers the SPA actually sends (see
# frontend/src/api/client.ts and routers/*.py route decorators). allow_credentials
# stays False regardless (see main.py's CORSMiddleware call site) — the session
# cookie only ever travels same-origin through the `/api` proxy, never
# via a credentialed cross-origin request.
CORS_ALLOWED_METHODS: list[str] = ["GET", "POST", "PATCH", "DELETE"]
CORS_ALLOWED_HEADERS: list[str] = ["Authorization", "Content-Type"]

# Single source for the dev-only origins in both config.CORS_ORIGINS' literal
# default and main.py's non-development CSRF-trust subtraction — the two must
# never drift, or a value dropped from one but not the other either breaks
# local dev or leaves a hardcoded localhost origin CSRF-trusted in production.
DEV_CORS_ORIGINS_DEFAULT: frozenset[str] = frozenset(
    {"http://localhost:5173", "http://localhost:4173"}
)

# CSRF — methods CsrfOriginCheckMiddleware (app/middleware.py) enforces the Origin
# check against. Deliberately includes PUT even though the API never routes
# it today (CORS_ALLOWED_METHODS above omits it) — this is a defense-in-depth
# check ahead of #24's cookie migration, not a mirror of what's currently wired up.
CSRF_UNSAFE_METHODS: frozenset[str] = frozenset({"POST", "PATCH", "DELETE", "PUT"})

# Security response headers — applied to every response by SecurityHeadersMiddleware
# (app.middleware.add_security_headers). This is a pure JSON API with no first-party HTML/script surface, so the
# CSP can be maximally restrictive; frame-ancestors/X-Frame-Options block clickjacking.
SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Pure JSON API, nothing should ever be cached by an intermediary — most
    # importantly, POST /auth/verify sets the session cookie via Set-Cookie.
    "Cache-Control": "no-store",
    # Denies browser-feature access outright rather than leaving it at
    # browser defaults — this API never needs camera/mic/geolocation/payment,
    # and interest-cohort opts out of FLoC-style tracking.
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), interest-cohort=()"
    ),
}
# HSTS is only safe to send over HTTPS — Render terminates TLS in front of the app,
# so this is gated to production (see app.middleware) to avoid breaking local http://localhost.
HSTS_HEADER_NAME = "Strict-Transport-Security"
HSTS_MAX_AGE_SECONDS = 31536000  # 1 year, matches HSTS preload-list minimum
HSTS_HEADER_VALUE = f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains"

# app/ingestion/sanitize.py — HTML post-processing regexes.
# _MULTI_BR_RE: collapses a run of more than HTML_SANITIZE_MAX_CONSECUTIVE_BR
# <br> tags; %d is filled in with HTML_SANITIZE_MAX_CONSECUTIVE_BR + 1.
HTML_MULTI_BR_TEMPLATE_RE = r"(?:<br\s*/?>\s*){%d,}"
# _BR_TAG_RE: one whole <br> tag. _strip_edge_brs peels leading/trailing runs
# with it iteratively — a single alternation regex over the runs backtracked
# cubically on "<br>" + long whitespace + "<br>" (OWASP audit H-1).
HTML_BR_TAG_RE = r"<br\s*/?>"
# _WHITESPACE_RUN_RE: collapses ASCII whitespace runs within text nodes
# (deliberately excludes U+00A0/nbsp — see sanitize.py's docstring).
HTML_WHITESPACE_RUN_RE = r"[ \t\n\r\f\v]+"
# Normalizes BeautifulSoup's self-closed "<br/>" serialization back to "<br>".
HTML_SELF_CLOSING_BR_RE = r"<br\s*/>"

# URL render-safety (http_client.safe_render_url, OWASP audit M-1): characters
# Python's urlsplit/httpx and the WHATWG URL parser disagree about ("\\" is a
# path separator to browsers, a userinfo char to urlsplit), plus controls and
# whitespace that parsers silently strip. Non-ASCII is rejected in the
# authority only (unicode paths are legitimate; IDN hosts are not accepted).
URL_RENDER_FORBIDDEN_RE = r"[\\\x00-\x20\x7f]"
# Hard cap on organizer/claimant-supplied URLs (L-6) — also bounds every
# /explore, /public/showcase and digest payload that carries them.
URL_MAX_LEN = 2048

ERROR_FEATURE_DISABLED = "{feature} disabled: {setting_name} not configured"

# Feature/setting labels for require_configured_secret's 503 detail.
FEATURE_ADMIN_LOGIN = "Admin login"
FEATURE_ADMIN_TOTP = "Admin TOTP"
FEATURE_INBOUND_WEBHOOK = "Webhook"
SETTING_NAME_ADMIN_TOTP_SECRET = "ADMIN_TOTP_SECRET"
SETTING_NAME_RESEND_WEBHOOK_SECRET = "RESEND_WEBHOOK_SECRET"
