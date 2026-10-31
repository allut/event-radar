import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app._generated.shared_constants import APP_VERSION
from app.constants.core import APP_ENV_DEVELOPMENT
from app.constants.ops import DEV_DB_LOCAL_HOSTS
from app.constants.security import (
    CORS_ALLOWED_HEADERS,
    CORS_ALLOWED_METHODS,
    DEV_CORS_ORIGINS_DEFAULT,
    HOST_CHECK_EXEMPT_PATHS,
    MAX_REQUEST_BODY_BYTES,
)
from app.db import AsyncSessionLocal, assert_schema_at_head, engine
from app.logging_config import configure_logging, shutdown_log_shipping
from app.rate_limit import limiter, rate_limit_exceeded_handler
from app.routers.admin_auth import router as admin_auth_router
from app.routers.admin_claims import router as admin_claims_router
from app.routers.admin_events import router as admin_events_router
from app.routers.admin_jobs import router as admin_jobs_router
from app.routers.admin_overview import router as admin_overview_router
from app.routers.admin_promotion_requests import router as admin_promotion_requests_router
from app.routers.admin_promotions import router as admin_promotions_router
from app.routers.admin_reports import router as admin_reports_router
from app.routers.admin_submissions import router as admin_submissions_router
from app.routers.auth import router as auth_router
from app.routers.browse import router as browse_router
from app.routers.contact import router as contact_router
from app.routers.events import router as events_router
from app.routers.feed import router as feed_router
from app.routers.feedback import router as feedback_router
from app.routers.onboarding import router as onboarding_router
from app.routers.organizer_auth import router as organizer_auth_router
from app.routers.organizer_claim_edits import router as organizer_claim_edits_router
from app.routers.organizer_claim_search import router as organizer_claim_search_router
from app.routers.organizer_claims import router as organizer_claims_router
from app.routers.organizer_contact import router as organizer_contact_router
from app.routers.organizer_events import router as organizer_events_router
from app.routers.organizer_profile import router as organizer_profile_router
from app.routers.organizer_promotions import router as organizer_promotions_router
from app.routers.organizer_venues import router as organizer_venues_router
from app.routers.public import router as public_router
from app.routers.reports import router as reports_router
from app.routers.settings import router as settings_router
from app.email.consent import reset_consent_for_wording_change
from app.routers.unsubscribe import router as unsubscribe_router
from app.db import run_in_session
from app.promotions.counters import flush as flush_promotion_counters
from app.routers.organizer_promotion_checkout import router as organizer_promotion_checkout_router
from app.routers.stripe_webhook import router as stripe_webhook_router
from app.routers.webhooks import router as webhooks_router
from app.middleware import (
    CsrfOriginCheckMiddleware,
    HostCheckMiddleware,
    MaxBodySizeMiddleware,
    add_security_headers,
    resolve_allowed_hosts,
)
from app.scheduler import start_scheduler
from app.seeds import seed_personas, seed_publishers, seed_sources

# uvicorn configures its own logging during Config.load(), before importing this
# module — calling configure_logging() here runs last and wins, so every logger
# (app, uvicorn, SQL echo) shares one timestamped format.
configure_logging()

log = logging.getLogger(__name__)


def _check_dev_database_host() -> None:
    """Log an ERROR if APP_ENV=development but DATABASE_URL points at a
    non-local host — likely a stray/never-overridden env var pointed at a
    real (staging/prod) database, which combined with ALLOW_INSECURE_DEV
    would leave that real database's admin surface unprotected (see M1,
    require_configured_secret)."""
    if settings.APP_ENV != APP_ENV_DEVELOPMENT:
        return
    host = urlsplit(settings.DATABASE_URL).hostname
    if host and host not in DEV_DB_LOCAL_HOSTS:
        log.error(
            "APP_ENV=development but DATABASE_URL host=%r is not local — "
            "this looks like a misconfigured environment pointed at a real database",
            host,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _check_dev_database_host()
    await assert_schema_at_head()
    async with AsyncSessionLocal() as db:
        await seed_sources(db)
        await seed_personas(db)
        await seed_publishers(db)
        # A material consent-wording bump resets stale consenters to off.
        await reset_consent_for_wording_change(db)
        await db.commit()

    scheduler = start_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        try:
            await run_in_session(flush_promotion_counters, commit=True)
        except Exception:
            log.exception("promotion counter flush on shutdown failed")
        await engine.dispose()
        shutdown_log_shipping()


# Swagger UI / ReDoc load their JS/CSS from a CDN, which the restrictive
# default-src 'none' CSP (SECURITY_HEADERS, set on every response below) blocks —
# rather than carve out CDN exceptions in the policy, disable the docs routes
# outside development. docs/security.md already frames this as "a pure JSON API with no
# first-party HTML/script surface"; this makes that statement true everywhere.
_docs_enabled = settings.APP_ENV == APP_ENV_DEVELOPMENT
app = FastAPI(
    title="Event Radar API",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
    # Swagger is served from :8000 but the session cookie is Path=/api and
    # belongs to the Vite dev server's origin (localhost:5173) — pointing
    # "Try it out" at this relative /api path instead of the bare backend
    # origin routes its requests through the Vite proxy (see vite.config.ts),
    # so the browser attaches the cookie automatically. See #28.
    servers=[{"url": "/api"}] if _docs_enabled else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    # Auth is now a Set-Cookie session (see #26 / docs/adr/0001), but
    # allow_credentials stays False deliberately: the cookie is scoped to this
    # API's own origin and only ever travels through the same-origin `/api`
    # proxy the SPA is served behind, never via a cross-origin
    # browser fetch/XHR — so credentialed CORS would only widen the attack
    # surface for no functional gain, regardless of what CORS_ORIGINS lists.
    allow_credentials=False,
    allow_methods=CORS_ALLOWED_METHODS,
    allow_headers=CORS_ALLOWED_HEADERS,
)

# CORS_ORIGINS now serves double duty — CORS (above) and CSRF trust (below).
# Widening it for one purpose widens the other too; a value added here to let a
# new frontend deployment through CORS also becomes a trusted CSRF origin.
#
# CORS_ORIGINS is sync: false in render.yaml, so an operator who forgets to set
# it in the Render dashboard silently keeps its dev default
# (settings.CORS_ORIGINS' literal default below) — SameSite=Strict means that
# default can't actually carry the session cookie cross-origin, but a
# permanently-trusted localhost CSRF origin in production is still the wrong
# shape for a config mistake to take. Dropped outside development so a
# forgotten CORS_ORIGINS degrades to "no CSRF-trusted origins" (fail closed)
# rather than "trust two hardcoded localhost ports" (fail open).
_csrf_trusted_origins = frozenset(settings.CORS_ORIGINS) | {settings.FRONTEND_URL}
if settings.APP_ENV != APP_ENV_DEVELOPMENT:
    _csrf_trusted_origins -= DEV_CORS_ORIGINS_DEFAULT
app.add_middleware(
    CsrfOriginCheckMiddleware,
    trusted_origins=_csrf_trusted_origins,
)


app.middleware("http")(add_security_headers)


# Starlette's add_middleware() prepends to user_middleware, so the LAST middleware
# registered ends up OUTERMOST (run first on the way in). This must be outermost —
# added after every other add_middleware()/@app.middleware() call above — so that
# scope["client"] is rewritten from the trusted X-Forwarded-For header *before*
# SlowAPIMiddleware (and the @limiter.limit decorators' get_remote_address calls)
# ever see request.client. Render terminates TLS and proxies every request through
# its routing layer, so request.client.host would otherwise be the proxy's address
# for every inbound connection, collapsing all clients into a single rate-limit
# bucket. trusted_hosts="*" is safe here: Render's web services are reachable only
# through its proxy, so any connection reaching this process is by definition from
# that trusted hop.
#
# DEPLOYMENT INVARIANT this depends on: trusted_hosts="*" means ANY peer that can
# open a TCP connection to this process gets its X-Forwarded-For header trusted
# verbatim (rate-limit bucketing and logged client IPs become spoofable by that
# peer). Render doesn't publish a stable proxy egress CIDR to pin trusted_hosts to
# instead, so this is safe only as long as the process is never reachable off of
# Render's proxy — e.g. it would break silently if the service were ever exposed
# directly (a public port, a misconfigured internal network, a non-Render host),
# or fronted by another CDN/proxy in addition to Render's. Re-derive this trade-off
# if the deployment topology changes.
#
# Registered before (i.e. wraps *inside*) ProxyHeadersMiddleware so a rejected
# oversized request still gets logged/rate-limited against its real client
# address rather than the raw proxy connection.
app.add_middleware(MaxBodySizeMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)

# Host header validation — nothing today builds an absolute URL from the
# request Host (FRONTEND_URL/BACKEND_URL are config, not derived from it), so
# impact is limited to intermediary cache-poisoning scenarios, but rejecting
# an unexpected Host outright is a one-line hardening. Skipped in development
# (no fixed BACKEND_URL host, e.g. localhost with a changing port in tests).
# /health is exempted (HOST_CHECK_EXEMPT_PATHS) — Render's health probe hits
# this process over the private network with the instance's internal address
# as Host, not BACKEND_URL's hostname. See resolve_allowed_hosts() for the
# fail-open reasoning: an unresolvable allowlist skips this middleware
# entirely rather than 400ing all public traffic (the 0.1.6 outage).
#
# Registered before (i.e. wraps *inside*) ProxyHeadersMiddleware below so a
# rejected request still gets its real client IP resolved for the
# LOG_EVENT_HOST_REJECTED log line in HostCheckMiddleware.
_allowed_hosts = (
    resolve_allowed_hosts() if settings.APP_ENV != APP_ENV_DEVELOPMENT else []
)
if _allowed_hosts:
    app.add_middleware(
        HostCheckMiddleware,
        allowed_hosts=_allowed_hosts,
        exempt_paths=HOST_CHECK_EXEMPT_PATHS,
    )
#
# HOP-COUNT ASSUMPTION: ProxyHeadersMiddleware itself trusts the *leftmost* XFF
# hop (attacker-controlled if forwarded verbatim), so app.rate_limit.client_key
# never trusts request.client. Production is a two-hop path — browser ->
# Cloudflare Pages Function proxy -> Render -> uvicorn — so the rightmost XFF
# entry Render's own proxy appends is always Cloudflare's egress address, not
# the visitor. client_key() instead prefers an edge-authenticated X-Client-IP
# (proven via X-Edge-Auth against settings.EDGE_SHARED_SECRET, set by the
# Cloudflare Function), falling back to rightmost-XFF only when that pair is
# absent or invalid — correct for a direct-to-Render caller with exactly one
# trusted hop. See docs/security.md and OWASP audit finding G-1.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.include_router(admin_auth_router)
app.include_router(admin_claims_router)
app.include_router(admin_events_router)
app.include_router(admin_jobs_router)
app.include_router(admin_overview_router)
app.include_router(admin_promotion_requests_router)
app.include_router(admin_promotions_router)
app.include_router(admin_reports_router)
app.include_router(admin_submissions_router)
app.include_router(auth_router)
app.include_router(browse_router)
app.include_router(contact_router)
app.include_router(events_router)
app.include_router(feed_router)
app.include_router(feedback_router)
app.include_router(onboarding_router)
app.include_router(organizer_auth_router)
app.include_router(organizer_claim_edits_router)
# Must stay before organizer_claims_router: its GET /{claim_id} would shadow /search
# and /suggestions (tests/test_route_guards.py guards the order).
app.include_router(organizer_claim_search_router)
app.include_router(organizer_claims_router)
app.include_router(organizer_contact_router)
app.include_router(organizer_events_router)
app.include_router(organizer_profile_router)
app.include_router(organizer_promotions_router)
app.include_router(organizer_venues_router)
app.include_router(public_router)
app.include_router(reports_router)
app.include_router(settings_router)
app.include_router(unsubscribe_router)
app.include_router(webhooks_router)
app.include_router(stripe_webhook_router)
app.include_router(organizer_promotion_checkout_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}
