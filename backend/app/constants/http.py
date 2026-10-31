"""HTTP plumbing: headers, MIME types, ASGI message types, and http_client retry/timeout tuning."""

import http

# ASGI scope/message "type" values (app/middleware.py's raw ASGI middleware classes —
# HostCheckMiddleware, MaxBodySizeMiddleware, CsrfOriginCheckMiddleware). Fixed by
# the ASGI spec, not application data, but still named here rather than repeated
# as bare string literals in conditionals.
ASGI_SCOPE_TYPE_HTTP = "http"
ASGI_MESSAGE_TYPE_REQUEST = "http.request"
ASGI_MESSAGE_TYPE_RESPONSE_START = "http.response.start"
ASGI_MESSAGE_TYPE_RESPONSE_BODY = "http.response.body"

# ingestion/http_client.py::host_guard_hook pins redirects to this port (in
# addition to hostname + scheme) — every ingestion source is fetched over
# https, so a redirect to a non-standard port on an otherwise-allowlisted
# host is rejected rather than silently followed (OWASP audit F14).
HTTPS_DEFAULT_PORT = 443

HTTP_TIMEOUT_SECONDS: float = 30.0
HTTP_USER_AGENT = "EventRadarBot/1.0 (+https://eventradar.ee)"
HTTP_RETRY_MAX_ATTEMPTS = 5  # bumped from 3 so backoff can outlast a short 429 penalty window
HTTP_RETRY_WAIT_MULTIPLIER = 1
HTTP_RETRY_WAIT_MIN = 2
HTTP_RETRY_WAIT_MAX = 30
HTTP_RETRY_AFTER_MAX_SECONDS: float = 60.0  # cap on an honored Retry-After header
HTTP_RETRY_JITTER_MAX: float = 1.0  # max random jitter added to the non-429 backoff wait
# Cap on a streamed http_get() response body. The largest real source page is
# Fienta's events API at ~4 MiB (the HTML pages are under 1 MiB), so this leaves
# 4x headroom while keeping a hostile or broken source from exhausting memory.
HTTP_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
HTTP_RESPONSE_CHUNK_BYTES = 64 * 1024
HTTP_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset(
    {
        http.HTTPStatus.TOO_MANY_REQUESTS,  # 429
        http.HTTPStatus.BAD_GATEWAY,  # 502
        http.HTTPStatus.SERVICE_UNAVAILABLE,  # 503
        http.HTTPStatus.GATEWAY_TIMEOUT,  # 504
    }
)

# Bearer-token auth headers used by outbound email/LLM API clients.
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "
# Other HTTP header names referenced by name across routers/middleware/ingestion —
# named here rather than as bare string literals so a typo at any call site
# fails loudly (constant not found) instead of silently missing the header.
HEADER_ORIGIN = "origin"
HEADER_HOST = "host"
HEADER_X_FORWARDED_FOR = "x-forwarded-for"
# Edge-authenticated real-client-IP handoff across the Cloudflare Pages proxy
# hop — see app.rate_limit.client_key() and settings.EDGE_SHARED_SECRET.
HEADER_X_CLIENT_IP = "x-client-ip"
HEADER_X_EDGE_AUTH = "x-edge-auth"
HEADER_RETRY_AFTER = "Retry-After"
HEADER_ACCEPT_LANGUAGE = "Accept-Language"

HEADER_CONTENT_TYPE = "Content-Type"
MIME_APPLICATION_JSON = "application/json"
MIME_APPLICATION_NDJSON = "application/x-ndjson"

# HTTP verbs used as literal method tags outside the httpx client calls
# themselves (e.g. ListingRequest.method) — the retrying http_get/http_post
# wrappers already encode the verb in their function name.
HTTP_METHOD_GET = "GET"
HTTP_METHOD_POST = "POST"

URL_SCHEME_HTTPS = "https"
HOST_WWW_PREFIX = "www."

# JSON endpoints scraped by the Piletilevi / Estonia Concert Hall adapters
HTTP_ACCEPT_JSON_HEADERS = {"accept": "application/json"}
