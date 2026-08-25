"""Token utilities for magic-link auth and session management.

Magic-link token: URLSafeTimedSerializer signed payload {user_id}, 15-min TTL.
Session token: same serializer with a different salt, SESSION_TTL_DAYS TTL
(2 days as of shared/app-config.json — see CLAUDE.md Auth).
The magic-link token hash (SHA-256 hex) is stored in auth_magic_links.token_hash
so a compromised DB row cannot be turned back into a valid token.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from itsdangerous import URLSafeTimedSerializer

from app.config import settings
from app.constants import (
    ADMIN_SESSION_TTL_SECONDS,
    AUTH_ADMIN_SESSION_SALT,
    AUTH_MAGIC_SALT,
    AUTH_ORGANIZER_MAGIC_SALT,
    AUTH_ORGANIZER_SESSION_SALT,
    AUTH_SESSION_SALT,
    AUTH_UNSUBSCRIBE_SALT,
    DEFAULT_SESSION_TOKEN_VERSION,
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


def generate_admin_session_token() -> str:
    """Admin console session (routers/admin_auth.py) — no admins table, no
    per-admin identity, so unlike generate_session_token/
    generate_organizer_session_token there is no id or "v" (revocation)
    claim to embed: the payload just asserts a login happened. Revocation is
    TTL expiry only (ADMIN_SESSION_TTL_SECONDS), per the ticket's scope."""
    return _serializer().dumps({"admin": True}, salt=AUTH_ADMIN_SESSION_SALT)


def verify_admin_session_token(token: str) -> None:
    """Raises BadSignature / SignatureExpired on failure; returns nothing on
    success (there is no id/version to hand back — see generate_admin_session_token)."""
    _serializer().loads(
        token, salt=AUTH_ADMIN_SESSION_SALT, max_age=ADMIN_SESSION_TTL_SECONDS
    )


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
