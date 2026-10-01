"""Token utilities for magic-link auth and session management.

Magic-link token: URLSafeTimedSerializer signed payload {user_id}, 15-min TTL.
Session token: same serializer with a different salt, SESSION_TTL_DAYS TTL
(2 days as of shared/app-config.json — see CLAUDE.md Auth).
The magic-link token hash (SHA-256 hex) is stored in auth_magic_links.token_hash
so a compromised DB row cannot be turned back into a valid token.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import settings
from app.constants import (
    ADMIN_SESSION_EPOCH_HASH_LEN,
    ADMIN_SESSION_TTL_SECONDS,
    AUTH_ADMIN_SESSION_SALT,
    AUTH_GOOGLE_LINK_BINDING_SALT,
    AUTH_MAGIC_SALT,
    AUTH_OAUTH_STATE_SALT,
    AUTH_ORGANIZER_MAGIC_SALT,
    AUTH_ORGANIZER_SESSION_SALT,
    AUTH_SESSION_SALT,
    AUTH_UNSUBSCRIBE_SALT,
    DEFAULT_SESSION_TOKEN_VERSION,
    OAUTH_STATE_TTL_MINUTES,
    ORGANIZER_MAGIC_LINK_TTL_MINUTES,
    ORGANIZER_SESSION_TTL_DAYS,
    SECONDS_PER_DAY,
    SECONDS_PER_MINUTE,
    UNSUBSCRIBE_TOKEN_TTL_DAYS,
)


def magic_ttl_seconds() -> int:
    return settings.MAGIC_LINK_TTL_MINUTES * SECONDS_PER_MINUTE


def organizer_magic_ttl_seconds() -> int:
    return ORGANIZER_MAGIC_LINK_TTL_MINUTES * SECONDS_PER_MINUTE


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY)


def generate_magic_token(user_id: int) -> tuple[str, str, datetime]:
    """Return (signed_token, sha256_hex_hash, expires_at)."""
    token = _serializer().dumps({"uid": user_id}, salt=AUTH_MAGIC_SALT)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=magic_ttl_seconds())
    return token, token_hash, expires_at


def verify_magic_token(token: str) -> int:
    """Decode and return user_id. Raises SignatureExpired or BadSignature on failure."""
    payload = _serializer().loads(
        token, salt=AUTH_MAGIC_SALT, max_age=magic_ttl_seconds()
    )
    return int(payload["uid"])


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_session_token(user_id: int, version: int) -> str:
    """Embed the user's current session_token_version ("v") in the signed
    payload — /auth/logout-all bumps the stored version, which immediately
    invalidates every token minted with an older value (see verify_session_token
    and get_current_user)."""
    return _serializer().dumps(
        {"uid": user_id, "v": version},
        salt=AUTH_SESSION_SALT,
    )


def verify_session_token(token: str) -> tuple[int, int]:
    """Return (user_id, version). Raises BadSignature / SignatureExpired on failure.

    Tokens minted before the "v" claim existed lack it — default to 1 so they
    degrade gracefully to the new column's server_default rather than being
    rejected outright on the day of the migration."""
    payload = _serializer().loads(
        token,
        salt=AUTH_SESSION_SALT,
        max_age=settings.SESSION_TTL_DAYS * SECONDS_PER_DAY,
    )
    return int(payload["uid"]), int(payload.get("v", DEFAULT_SESSION_TOKEN_VERSION))


def generate_organizer_magic_token(organizer_id: int) -> tuple[str, str, datetime]:
    """Return (signed_token, sha256_hex_hash, expires_at) for an organizer
    magic-link — same shape as generate_magic_token, distinct salt (see
    AUTH_ORGANIZER_MAGIC_SALT) so a user token can never verify as one."""
    token = _serializer().dumps({"oid": organizer_id}, salt=AUTH_ORGANIZER_MAGIC_SALT)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=organizer_magic_ttl_seconds()
    )
    return token, token_hash, expires_at


def verify_organizer_magic_token(token: str) -> int:
    """Decode and return organizer_id. Raises SignatureExpired or BadSignature."""
    payload = _serializer().loads(
        token, salt=AUTH_ORGANIZER_MAGIC_SALT, max_age=organizer_magic_ttl_seconds()
    )
    return int(payload["oid"])


def generate_organizer_session_token(organizer_id: int, version: int) -> str:
    """Embed the organizer's current session_token_version ("v") in the signed
    payload — mirrors generate_session_token for the organizer auth track."""
    return _serializer().dumps(
        {"oid": organizer_id, "v": version},
        salt=AUTH_ORGANIZER_SESSION_SALT,
    )


def verify_organizer_session_token(token: str) -> tuple[int, int]:
    """Return (organizer_id, version). Raises BadSignature / SignatureExpired."""
    payload = _serializer().loads(
        token,
        salt=AUTH_ORGANIZER_SESSION_SALT,
        max_age=ORGANIZER_SESSION_TTL_DAYS * SECONDS_PER_DAY,
    )
    return int(payload["oid"]), int(payload.get("v", DEFAULT_SESSION_TOKEN_VERSION))


def generate_organizer_claim_link_token(organizer_id: int, event_id: int) -> tuple[str, str, datetime]:
    """Sign-in link that also carries claim intent (#413): the Publisher/
    Series-claim key round-trips inside the token itself — never
    sessionStorage or a query param — so it survives being opened on a
    different device/session than the one that requested it. Same salt as
    generate_organizer_magic_token (identical trust boundary: proof of
    control over the organizer's email); verify_organizer_claim_link_token
    is the only thing that reads the extra "eid" claim back out."""
    token = _serializer().dumps(
        {"oid": organizer_id, "eid": event_id}, salt=AUTH_ORGANIZER_MAGIC_SALT
    )
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=organizer_magic_ttl_seconds()
    )
    return token, token_hash, expires_at


def verify_organizer_claim_link_token(token: str) -> tuple[int, int]:
    """Return (organizer_id, event_id). Raises SignatureExpired or BadSignature."""
    payload = _serializer().loads(
        token, salt=AUTH_ORGANIZER_MAGIC_SALT, max_age=organizer_magic_ttl_seconds()
    )
    return int(payload["oid"]), int(payload["eid"])


def oauth_state_ttl_seconds() -> int:
    return OAUTH_STATE_TTL_MINUTES * SECONDS_PER_MINUTE


class OAuthStatePayload(TypedDict):
    state: str
    code_verifier: str
    track: str


def generate_oauth_state_token(state: str, code_verifier: str, track: str) -> str:
    """Sign the PKCE state+verifier pair for the organizer_oauth_state /
    oauth_state cookie (ADR 0002). ``track`` ("organizer" or "user") is
    checked at verify time so a state token minted for one track's callback
    can never be replayed against the other's."""
    return _serializer().dumps(
        {"state": state, "code_verifier": code_verifier, "track": track},
        salt=AUTH_OAUTH_STATE_SALT,
    )


def verify_oauth_state_token(token: str, *, track: str) -> OAuthStatePayload:
    """Decode the signed state cookie value. Raises SignatureExpired or
    BadSignature on failure, including a track mismatch — the callback must
    fail closed exactly like any other tampered/expired token."""
    payload = _serializer().loads(
        token, salt=AUTH_OAUTH_STATE_SALT, max_age=oauth_state_ttl_seconds()
    )
    if payload.get("track") != track:
        raise BadSignature("oauth state track mismatch")
    return {
        "state": str(payload["state"]),
        "code_verifier": str(payload["code_verifier"]),
        "track": str(payload["track"]),
    }


def generate_google_link_binding_token(sub: str, track: str) -> str:
    """Sign the pending Google ``sub`` for the google_link_binding /
    organizer_google_link_binding cookie (OWASP audit #3). Set in the browser
    that completed the Google sign-in whose confirmation magic link was just
    emailed; the verify route only absorbs a link's ``pending_google_sub``
    when this cookie carries the same sub. ``track`` ("organizer" or "user")
    is checked at verify time, same cross-track guard as the OAuth state."""
    return _serializer().dumps(
        {"sub": sub, "track": track}, salt=AUTH_GOOGLE_LINK_BINDING_SALT
    )


def google_link_binding_matches(
    token: str | None, *, sub: str, track: str, max_age: int | None = None
) -> bool:
    """True only when ``token`` is an unexpired, untampered binding cookie for
    this track carrying exactly ``sub``. Any failure — missing cookie, bad
    signature, expiry, other track, other sub — is False, never an exception:
    the caller falls back to a plain sign-in with no identity link. ``max_age``
    defaults to the consumer magic-link TTL; the organizer track passes its own."""
    if not isinstance(token, str) or not token:
        return False
    try:
        payload = _serializer().loads(
            token,
            salt=AUTH_GOOGLE_LINK_BINDING_SALT,
            max_age=max_age if max_age is not None else magic_ttl_seconds(),
        )
    except BadSignature:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("track") == track
        and isinstance(payload.get("sub"), str)
        and secrets.compare_digest(payload["sub"], sub)
    )


def _admin_session_epoch() -> str:
    """Derive the "e" claim from the credentials themselves, not just the
    standalone ADMIN_SESSION_EPOCH var — so rotating ADMIN_PASSWORD or
    ADMIN_TOTP_SECRET after a suspected compromise auto-revokes every
    outstanding admin session, with no separate revocation lever an operator
    has to remember to pull (OWASP audit F4). ADMIN_SESSION_EPOCH stays in
    the mix so a manual bump still works even when credentials are unchanged."""
    return hashlib.sha256(
        f"{settings.ADMIN_SESSION_EPOCH}:{settings.ADMIN_PASSWORD}:{settings.ADMIN_TOTP_SECRET}".encode()
    ).hexdigest()[:ADMIN_SESSION_EPOCH_HASH_LEN]


def generate_admin_session_token() -> str:
    """Admin console session (routers/admin_auth.py) — no admins table, no
    per-admin identity, so unlike generate_session_token/
    generate_organizer_session_token there is no id or "v" (revocation)
    claim to embed. Revocation is TTL expiry (ADMIN_SESSION_TTL_SECONDS) plus
    the "e" (epoch) claim below, derived from the credentials
    (_admin_session_epoch): rotating ADMIN_PASSWORD/ADMIN_TOTP_SECRET, or
    bumping settings.ADMIN_SESSION_EPOCH directly, invalidates every
    outstanding admin session immediately — the cheapest durable revocation
    that fits this no-Redis/no-admins-table design — see M-1/F4 in the OWASP
    audit."""
    return _serializer().dumps(
        {"admin": True, "e": _admin_session_epoch()}, salt=AUTH_ADMIN_SESSION_SALT
    )


def verify_admin_session_token(token: str) -> None:
    """Raises BadSignature / SignatureExpired on failure; returns nothing on
    success (there is no id/version to hand back — see generate_admin_session_token).
    A token whose "e" claim doesn't match the currently derived epoch
    (credentials + ADMIN_SESSION_EPOCH) is treated as an invalid signature —
    this is what lets rotating either credential, or bumping the env var,
    revoke every previously issued admin session without a per-session
    revocation table."""
    payload = _serializer().loads(
        token, salt=AUTH_ADMIN_SESSION_SALT, max_age=ADMIN_SESSION_TTL_SECONDS
    )
    if payload.get("e", "") != _admin_session_epoch():
        raise BadSignature("admin session epoch mismatch")


def generate_unsubscribe_token(user_id: int) -> str:
    """No-login digest-unsubscribe token — long TTL so an old inbox email's
    link still works; salted separately from magic-link/session tokens so a
    leaked one-click-unsubscribe link can never be replayed as a sign-in."""
    return _serializer().dumps({"uid": user_id}, salt=AUTH_UNSUBSCRIBE_SALT)


def verify_unsubscribe_token(token: str) -> int:
    """Decode and return user_id. Raises SignatureExpired or BadSignature on failure."""
    payload = _serializer().loads(
        token,
        salt=AUTH_UNSUBSCRIBE_SALT,
        max_age=UNSUBSCRIBE_TOKEN_TTL_DAYS * SECONDS_PER_DAY,
    )
    return int(payload["uid"])
