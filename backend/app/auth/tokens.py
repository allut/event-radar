"""Token utilities for magic-link auth and session management.

Magic-link token: URLSafeTimedSerializer signed payload {user_id}, 15-min TTL.
Session token: same serializer with a different salt, 7-day TTL.
The magic-link token hash (SHA-256 hex) is stored in auth_magic_links.token_hash
so a compromised DB row cannot be turned back into a valid token.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings
from app.constants import AUTH_MAGIC_SALT, AUTH_SESSION_SALT, SESSION_TTL_DAYS


def magic_ttl_seconds() -> int:
    return settings.MAGIC_LINK_TTL_MINUTES * 60


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


def generate_session_token(user_id: int) -> str:
    return _serializer().dumps(
        {"uid": user_id},
        salt=AUTH_SESSION_SALT,
    )


def verify_session_token(token: str) -> int:
    """Return user_id. Raises BadSignature / SignatureExpired on failure."""
    payload = _serializer().loads(
        token,
        salt=AUTH_SESSION_SALT,
        max_age=SESSION_TTL_DAYS * 86400,
    )
    return int(payload["uid"])
