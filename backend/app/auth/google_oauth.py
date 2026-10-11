"""Google OAuth 2.0 authorization-code + PKCE helpers (docs/adr/0002).

PKCE pair generation, the authorization-URL builder, the code-for-token
exchange (via app/ingestion/http_client.py's http_post, per this repo's
retry-logic convention), and ID-token verification (PyJWT + PyJWKClient —
see the ADR for why this library over google-auth). No refresh token is ever
requested or stored (ADR 0002's "nothing on our side to revoke" invariant).

`PyJWKClient`'s JWKS fetch bypasses http_get/http_post (it does its own sync
urllib fetch, cached via cache_jwk_set) — documented as a Retry logic bypass
site in docs/conventions.md, justified the same way the ADR justifies choosing
PyJWKClient over google-auth: caching with no new async/sync-mixing cost.
"""

import base64
import hashlib
import logging
import secrets
from typing import TypedDict
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from app.config import settings
from app.constants.auth import (
    GOOGLE_AUTHORITATIVE_EMAIL_DOMAINS,
    GOOGLE_JWKS_CACHE_LIFESPAN_SECONDS,
    GOOGLE_OAUTH_AUTHORIZATION_ENDPOINT,
    GOOGLE_OAUTH_ISSUERS,
    GOOGLE_OAUTH_JWKS_URL,
    GOOGLE_OAUTH_SCOPE,
    GOOGLE_OAUTH_TOKEN_ENDPOINT,
    GOOGLE_OAUTH_TOKEN_TIMEOUT_SECONDS,
    OAUTH_PKCE_TOKEN_BYTES,
)
from app.ingestion.http_client import http_post

log = logging.getLogger(__name__)

# Cached process-wide (module-level singleton) — PyJWKClient's own
# cache_jwk_set keeps the fetched keys for its lifespan; recreating the
# client per call would defeat that cache.
_jwks_client = PyJWKClient(
    GOOGLE_OAUTH_JWKS_URL, cache_jwk_set=True, lifespan=GOOGLE_JWKS_CACHE_LIFESPAN_SECONDS
)


class GoogleIdentity(TypedDict):
    sub: str
    email: str
    email_verified: bool
    hd: str | None


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) — S256 only (RFC 9700 §2.1.1;
    `plain` is never used). code_verifier is a 43-char URL-safe random
    string, within RFC 7636's 43-128 char bound."""
    code_verifier = secrets.token_urlsafe(OAUTH_PKCE_TOKEN_BYTES)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def generate_state() -> str:
    return secrets.token_urlsafe(OAUTH_PKCE_TOKEN_BYTES)


def build_authorization_url(*, state: str, code_challenge: str, redirect_uri: str) -> str:
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_OAUTH_SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{GOOGLE_OAUTH_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


class GoogleTokenExchangeError(Exception):
    """Google's token endpoint returned 2xx but a body this app can't use
    (not JSON, or missing id_token) — treated as upstream degradation by the
    caller, same as a network/non-2xx failure, never a 500."""


async def exchange_code_for_id_token(
    *, code: str, code_verifier: str, redirect_uri: str
) -> str:
    """Server-to-server code-for-token exchange. Returns the raw ID token
    JWT. Raises httpx.HTTPError on network/non-2xx failure, or
    GoogleTokenExchangeError on a malformed 2xx body — the caller
    (routers/organizer_auth.py) maps both to LOG_EVENT_GOOGLE_SIGNIN_DEGRADED
    and a redirect-with-error, never a 500."""
    async with httpx.AsyncClient(timeout=GOOGLE_OAUTH_TOKEN_TIMEOUT_SECONDS) as client:
        response = await http_post(
            client,
            GOOGLE_OAUTH_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
    try:
        body = response.json()
        id_token = body["id_token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GoogleTokenExchangeError("malformed token endpoint response") from exc
    return str(id_token)


def verify_google_id_token(id_token: str) -> GoogleIdentity:
    """Verify signature (RS256 against Google's published JWKS), `iss`, and
    `aud`; return the claims this app is allowed to look at (sub/email/
    email_verified/hd — never name/picture, per ADR 0002's scope decision).
    Raises jwt.PyJWTError (or a subclass) on any verification failure."""
    signing_key = _jwks_client.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.GOOGLE_OAUTH_CLIENT_ID,
        issuer=list(GOOGLE_OAUTH_ISSUERS),
    )
    return {
        "sub": str(claims["sub"]),
        "email": str(claims["email"]).lower(),
        "email_verified": bool(claims.get("email_verified", False)),
        "hd": claims.get("hd"),
    }


def is_authoritative_identity(identity: GoogleIdentity) -> bool:
    """ADR 0002's linking gate: Google is authoritative for an address only
    when it's a Gmail/Googlemail address or carries a Workspace `hd` claim,
    and the token itself says the address is verified."""
    if not identity["email_verified"]:
        return False
    if identity["hd"]:
        return True
    domain = identity["email"].rsplit("@", 1)[-1]
    return domain in GOOGLE_AUTHORITATIVE_EMAIL_DOMAINS
