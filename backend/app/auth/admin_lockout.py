"""Admin auth lockout + credential checks for the form login
(``routers/admin_auth.py``) — the only place admin credentials are accepted
since HTTP Basic was removed (OWASP audit #4).
"""

import logging
import secrets
import time
from collections import OrderedDict

from fastapi import HTTPException, status

from app.config import settings
from app.constants import (
    ADMIN_AUTH_FAILURES_MAX_ENTRIES,
    ADMIN_AUTH_LOCKOUT_SECONDS,
    ADMIN_AUTH_MAX_FAILURES,
    ADMIN_USERNAME_DEFAULT,
    APP_ENV_DEVELOPMENT,
    ERROR_ADMIN_LOCKOUT,
    LOG_EVENT_AUTH_FAILED,
)

log = logging.getLogger(__name__)

# (client_key -> (consecutive_failure_count, locked_until_monotonic)). In-memory,
# single-process — see ADMIN_AUTH_MAX_FAILURES in constants.py for the trade-off.
# Bounded LRU (ADMIN_AUTH_FAILURES_MAX_ENTRIES) — mirrors browse.py's _score_cache
# pattern — so sustained scanning/brute-force traffic can't grow this unboundedly.
_admin_auth_failures: OrderedDict[str, tuple[int, float]] = OrderedDict()


def _evict_one_admin_auth_failure(now: float) -> None:
    """Evict the oldest entry whose lockout has already expired (or was never
    locked), falling back to the oldest entry overall only if every entry is
    currently under an active lockout. A blind oldest-first eviction would let
    a high-cardinality distributed brute-force (>ADMIN_AUTH_FAILURES_MAX_ENTRIES
    distinct client_keys) evict — and thereby prematurely lift — another
    client's still-active lockout, undermining the lockout this dict exists
    to enforce."""
    for key, (_count, locked_until) in _admin_auth_failures.items():
        if locked_until <= now:
            del _admin_auth_failures[key]
            return
    _admin_auth_failures.popitem(last=False)


def check_admin_lockout(key: str) -> float:
    """Raise 429 if `key` is currently locked out; otherwise return
    time.monotonic() for the caller to reuse (avoids a second clock read).
    Used by routers/admin_auth.py's form login.

    Opportunistically drops `key`'s entry once its lockout has expired
    (locked_until > 0.0 and now >= locked_until) — otherwise nothing ever
    removes an expired entry, so once the LRU (ADMIN_AUTH_FAILURES_MAX_ENTRIES)
    saturates it stays saturated and every subsequent failure pays the
    eviction scan. A never-locked entry (locked_until == 0.0, still under
    ADMIN_AUTH_MAX_FAILURES) is left alone — dropping it would reset the
    consecutive-failure count this dict exists to track."""
    now = time.monotonic()
    _count, locked_until = _admin_auth_failures.get(key, (0, 0.0))
    if now < locked_until:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=ERROR_ADMIN_LOCKOUT,
        )
    if locked_until > 0.0:
        _admin_auth_failures.pop(key, None)
    return now


def record_admin_auth_failure(key: str, now: float, username: str) -> None:
    """Bump the consecutive-failure count for `key`, locking it out once
    ADMIN_AUTH_MAX_FAILURES is reached. Shared with routers/admin_auth.py —
    see check_admin_lockout."""
    count, _locked = _admin_auth_failures.get(key, (0, 0.0))
    failures = count + 1
    locked_until = (
        now + ADMIN_AUTH_LOCKOUT_SECONDS
        if failures >= ADMIN_AUTH_MAX_FAILURES
        else 0.0
    )
    _admin_auth_failures[key] = (failures, locked_until)
    _admin_auth_failures.move_to_end(key)
    while len(_admin_auth_failures) > ADMIN_AUTH_FAILURES_MAX_ENTRIES:
        _evict_one_admin_auth_failure(now)
    # Log only whether the attempted username matched — never the value: a
    # password mistyped into the username field would otherwise be shipped
    # verbatim to the third-party log sink (OWASP audit L-12).
    username_ok = secrets.compare_digest(
        username.encode(), settings.ADMIN_USERNAME.encode()
    )
    log.warning(
        "admin auth failed: username_ok=%s failures=%d",
        username_ok,
        failures,
        extra={"event": LOG_EVENT_AUTH_FAILED},
    )


def clear_admin_auth_failure(key: str) -> None:
    """Reset `key`'s failure count on a successful login. Shared with
    routers/admin_auth.py — see check_admin_lockout."""
    _admin_auth_failures.pop(key, None)


def admin_username_disabled() -> bool:
    """True when ADMIN_USERNAME was never overridden from its well-known
    default outside development — fail closed like the password check,
    since a well-known username halves the credential pair an attacker
    needs to brute-force. Shared with routers/admin_auth.py."""
    return (
        settings.ADMIN_USERNAME == ADMIN_USERNAME_DEFAULT
        and settings.APP_ENV != APP_ENV_DEVELOPMENT
    )


def admin_credentials_ok(username: str, password: str) -> bool:
    """Constant-time check of a username/password attempt against the
    configured ADMIN_USERNAME/ADMIN_PASSWORD. Shared with
    routers/admin_auth.py — caller is responsible for the
    require_configured_secret/admin_username_disabled gates around this."""
    username_ok = secrets.compare_digest(
        username.encode(), settings.ADMIN_USERNAME.encode()
    )
    password_ok = secrets.compare_digest(
        password.encode(), settings.ADMIN_PASSWORD.encode()
    )
    return username_ok and password_ok
