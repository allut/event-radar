"""Drift guards for docs/security.md's per-route rules, checked on the real app.

Every route carries a rate limit, and every route either depends on its track's
auth dependency or is listed in PUBLIC_ROUTES. A new unauthenticated endpoint
fails here until someone adds it to PUBLIC_ROUTES on purpose. Needs no database.
"""

from collections.abc import Iterator

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.main import app
from app.rate_limit import limiter

# Reachable without a session, by design. Each entry is (method, path).
PUBLIC_ROUTES = frozenset(
    {
        ("POST", "/admin/auth/login"),
        ("POST", "/admin/auth/logout"),
        ("POST", "/auth/request-link"),
        ("POST", "/auth/verify"),
        ("POST", "/auth/logout"),
        ("GET", "/auth/google/start"),
        ("GET", "/auth/google/callback"),
        ("POST", "/organizer/auth/request-link"),
        ("POST", "/organizer/auth/verify"),
        ("POST", "/organizer/auth/logout"),
        ("GET", "/organizer/auth/google/start"),
        ("GET", "/organizer/auth/google/callback"),
        ("POST", "/organizer/claims/request-link"),
        ("POST", "/organizer/claims/verify-link"),
        ("POST", "/contact"),
        ("GET", "/public/showcase"),
        ("GET", "/public/counts"),
        ("GET", "/public/prerender-events"),
        ("POST", "/email/unsubscribe"),
        ("POST", "/email/resubscribe"),
        ("POST", "/email/ads-off"),
        ("POST", "/email/ads-on"),
        ("POST", "/webhooks/inbound-mail"),
        ("POST", "/webhooks/stripe"),
        ("GET", "/health"),
    }
)

# Rate-limit exempt, by design: throttling Render's health probe risks the
# platform marking the service unhealthy.
UNLIMITED_ROUTES = frozenset({("GET", "/health")})

# Path prefix -> the only auth dependency a non-public route under it may use.
TRACK_DEPENDENCY = {
    "/admin/": "get_current_admin",
    "/organizer/": "get_current_organizer",
}
AUTH_DEPENDENCIES = frozenset(
    {"get_current_user", "get_optional_user", "get_current_organizer", "get_current_admin"}
)


def _routes() -> Iterator[tuple[tuple[str, str], APIRoute]]:
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods):
                yield (method, route.path), route


def _dependency_names(dependant: Dependant) -> set[str]:
    names: set[str] = set()
    for sub in dependant.dependencies:
        names.add(getattr(sub.call, "__name__", ""))
        names |= _dependency_names(sub)
    return names


def _auth_dependencies(route: APIRoute) -> set[str]:
    return _dependency_names(route.dependant) & AUTH_DEPENDENCIES


def test_every_route_is_rate_limited() -> None:
    """`@limiter.limit` or `@limiter.shared_limit` on every endpoint (docs/security.md
    "Rate Limiting")."""
    registered = limiter._route_limits.keys() | limiter._dynamic_route_limits.keys()
    missing = [
        f"{method} {path}"
        for (method, path), route in _routes()
        if (method, path) not in UNLIMITED_ROUTES
        and f"{route.endpoint.__module__}.{route.endpoint.__name__}" not in registered
    ]
    assert missing == []


def test_every_non_public_route_requires_auth() -> None:
    unguarded = [
        f"{method} {path}"
        for (method, path), route in _routes()
        if (method, path) not in PUBLIC_ROUTES and not _auth_dependencies(route)
    ]
    assert unguarded == []


def test_track_prefixes_use_their_own_auth_dependency() -> None:
    """The three auth tracks never mix: an /admin/* route uses only the admin
    session, an /organizer/* route only the organizer session."""
    wrong = [
        f"{method} {path}: {sorted(deps)}"
        for (method, path), route in _routes()
        if (method, path) not in PUBLIC_ROUTES
        for prefix, required in TRACK_DEPENDENCY.items()
        if path.startswith(prefix) and (deps := _auth_dependencies(route)) != {required}
    ]
    assert wrong == []


def test_public_routes_exist_and_carry_no_auth() -> None:
    """A stale PUBLIC_ROUTES entry would silently widen the allowlist for a
    future route reusing that path, so every entry must match a live, unguarded route."""
    live = {key: route for key, route in _routes()}
    stale = sorted(f"{m} {p}" for m, p in PUBLIC_ROUTES if (m, p) not in live)
    guarded = sorted(
        f"{m} {p}" for m, p in PUBLIC_ROUTES if (m, p) in live and _auth_dependencies(live[(m, p)])
    )
    assert stale == []
    assert guarded == []
