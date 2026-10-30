"""Auth tracks: signing salts, cookies, sessions, magic links, Google OAuth, admin auth/TOTP, and their API messages."""

from typing import Literal

from app._generated.shared_constants import (
    MAGIC_LINK_TTL_MINUTES as _MAGIC_LINK_TTL_MINUTES_SHARED,
    SESSION_TTL_DAYS as _SESSION_TTL_DAYS_SHARED,
)

# Default value of settings.ADMIN_USERNAME. In production, admin_login fails
# closed if this hasn't been overridden — a guessable, well-known admin
# username removes half of the credential pair an attacker needs to brute-force.
ADMIN_USERNAME_DEFAULT = "admin"

# Consecutive-failure lockout on top of RATE_LIMIT_ADMIN (routers/admin.py::
# _require_admin) — a static username/password pair has no other brute-force
# damper. In-memory (single Render process, no Redis — matches the rest of
# this codebase's "no Celery/Redis" design), so it resets on deploy/restart;
# accepted since this pairs with, not replaces, a strong ADMIN_PASSWORD.
ADMIN_AUTH_MAX_FAILURES = 5
ADMIN_AUTH_LOCKOUT_SECONDS = 300
# Bounds _admin_auth_failures (routers/admin.py) the same way browse.py bounds
# _score_cache — an unbounded dict keyed by client_key() would grow forever
# under sustained scanning/brute-force traffic.
ADMIN_AUTH_FAILURES_MAX_ENTRIES = 4096

# Auth tokens
AUTH_MAGIC_SALT = "magic-link-v1"
AUTH_SESSION_SALT = "session-v1"
# Session-cookie transport (issue #26 / docs/adr/0001). Path scoping is what
# keeps the higher-value organizer credential off ordinary consumer requests —
# both paths sit under the `/api` proxy that makes the SPA same-origin
# with this API, so a browser only ever attaches SESSION_COOKIE_NAME under
# /api and ORGANIZER_SESSION_COOKIE_NAME under /api/organizer.
SESSION_COOKIE_NAME = "session"
SESSION_COOKIE_PATH = "/api"
ORGANIZER_SESSION_COOKIE_NAME = "organizer_session"
ORGANIZER_SESSION_COOKIE_PATH = "/api/organizer"
# Shared by routers/utils.py::set_session_cookie/clear_session_cookie — a single
# source of truth so the two functions can never drift apart (clear_session_cookie
# only actually clears the cookie in the browser if every attribute here matches
# what set_session_cookie used to set it).
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE: Literal["strict"] = "strict"
# Fallback "v" claim for session/organizer-session tokens minted before that
# claim existed (auth/tokens.py) — mirrors the session_token_version column's
# server_default/model default.
DEFAULT_SESSION_TOKEN_VERSION = 1
AUTH_UNSUBSCRIBE_SALT = "unsubscribe-v1"
# The "Stop ads in this email" link (routers/unsubscribe.py): purpose-bound, so an
# unsubscribe token can never withdraw Email ad consent or the reverse.
AUTH_ADS_OFF_SALT = "ads-off-v1"
# Organizer auth — distinct salts from the user stack above so a user's magic-link
# or session token can never verify as an organizer token (and vice versa), even
# though both use the same URLSafeTimedSerializer(settings.SECRET_KEY).
AUTH_ORGANIZER_MAGIC_SALT = "organizer-magic-v1"
AUTH_ORGANIZER_SESSION_SALT = "organizer-session-v1"
# Organizer TTLs mirror the user-facing defaults (no separate settings override —
# organizers are not expected to need a different cadence than consumers).
ORGANIZER_MAGIC_LINK_TTL_MINUTES = _MAGIC_LINK_TTL_MINUTES_SHARED
ORGANIZER_SESSION_TTL_DAYS = _SESSION_TTL_DAYS_SHARED

# Google sign-in (ADR 0002) — server-side OAuth 2.0 authorization code + PKCE.
# One salt shared by both tracks' state cookies (payload's "track" field keeps
# a user state token from verifying against the organizer callback and vice
# versa, same defense-in-depth shape as the magic-link/session salt split).
AUTH_OAUTH_STATE_SALT = "oauth-state-v1"
OAUTH_STATE_TTL_MINUTES = 10
# generate_oauth_state_token/verify_oauth_state_token's "track" discriminator
# (app/auth/tokens.py) — the cross-track replay guard; a typo at any of the
# four call sites (auth.py x2, organizer_auth.py x2) would silently break the
# mint/verify pairing, so both are named constants rather than inline strings.
# PyJWKClient's own cache_jwk_set lifespan (app/auth/google_oauth.py) — how
# long the fetched Google JWKS keyset is cached before a re-fetch.
GOOGLE_JWKS_CACHE_LIFESPAN_SECONDS = 300
# secrets.token_urlsafe() byte count for the PKCE code_verifier and the OAuth
# state value (app/auth/google_oauth.py) — 32 bytes -> 43 URL-safe chars,
# within RFC 7636's 43-128 char code_verifier bound.
OAUTH_PKCE_TOKEN_BYTES = 32
# Timeout for the server-to-server code-for-token exchange
# (app/auth/google_oauth.py::exchange_code_for_id_token), awaited inline in
# the OAuth callback — deliberately shorter than HTTP_TIMEOUT_SECONDS.
GOOGLE_OAUTH_TOKEN_TIMEOUT_SECONDS = 10.0
IDENTITY_PROVIDER_GOOGLE = "google"
GOOGLE_OAUTH_SCOPE = "openid email"  # never "profile" — no name/picture stored
GOOGLE_OAUTH_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_OAUTH_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
# Domains Google is authoritative for (ADR 0002's linking gate) — an `hd` claim
# on the ID token is the other authoritative signal, checked separately.
GOOGLE_AUTHORITATIVE_EMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
# organizer_oauth_state / oauth_state cookies (Path scoped to the callback
# route only, unlike the session cookie's broader /api/organizer or /api —
# each is only ever read on one route). SameSite=Lax, not Strict — see
# docs/adr/0002 for why.
ORGANIZER_OAUTH_STATE_COOKIE_NAME = "organizer_oauth_state"
ORGANIZER_GOOGLE_CALLBACK_PUBLIC_PATH = "/api/organizer/auth/google/callback"
# The state cookie is Path-scoped to the callback route, so the two must be equal.
ORGANIZER_OAUTH_STATE_COOKIE_PATH = ORGANIZER_GOOGLE_CALLBACK_PUBLIC_PATH
OAUTH_STATE_COOKIE_NAME = "oauth_state"
GOOGLE_CALLBACK_PUBLIC_PATH = "/api/auth/google/callback"
OAUTH_STATE_COOKIE_PATH = GOOGLE_CALLBACK_PUBLIC_PATH
OAUTH_STATE_COOKIE_SAMESITE: Literal["lax"] = "lax"
# Google-link binding cookies (OWASP audit #3): set on the callback that sends a
# confirmation magic link, carrying the pending Google `sub`, so the link only
# attaches that identity when clicked in the browser that started the Google
# sign-in. Unlike the state cookies these are SameSite=Strict session-style
# cookies (set on a top-level response, read on the SPA's same-site POST to the
# verify route), scoped to that one route. Own salt so a binding token never
# verifies as a magic-link/session/state token.
AUTH_GOOGLE_LINK_BINDING_SALT = "google-link-binding-v1"
GOOGLE_LINK_BINDING_COOKIE_NAME = "google_link_binding"
GOOGLE_LINK_BINDING_COOKIE_PATH = "/api/auth/verify"
ORGANIZER_GOOGLE_LINK_BINDING_COOKIE_NAME = "organizer_google_link_binding"
ORGANIZER_GOOGLE_LINK_BINDING_COOKIE_PATH = "/api/organizer/auth/verify"
# Google sign-in outcomes (routers/organizer_auth.py / routers/auth.py
# callbacks) — carried on LOG_EVENT_GOOGLE_SIGNIN's `outcome` field.
GOOGLE_SIGNIN_OUTCOME_EXISTING_LOGIN = "existing_login"
GOOGLE_SIGNIN_OUTCOME_NEW_ACCOUNT = "new_account"
GOOGLE_SIGNIN_OUTCOME_AUTO_LINKED = "auto_linked"
GOOGLE_SIGNIN_OUTCOME_CONFIRMATION_SENT = "confirmation_sent"
# Google reported the address as unverified and it isn't an authoritative
# domain — no confirmation link is sent (OWASP audit #3), nothing is created.
GOOGLE_SIGNIN_OUTCOME_UNVERIFIED_EMAIL = "unverified_email"

# Callback success-redirect marker — the frontend's signed-in localStorage
# hint is written by the magic-link verify routes only; a Google callback is
# a server-side redirect with no app JS in between, so this param tells
# main.tsx which track's hint to set before the router's first render (see
# frontend/src/lib/googleSignInLanding.ts). Values reuse AUTH_TRACK_USER/
# AUTH_TRACK_ORGANIZER from app._generated.shared_constants — no separate value
# constants.
# Callback redirect-with-error query param + failure reason codes — internal,
# not i18n keys (mirrors the ERROR_* constants' English-only convention).
OAUTH_ERROR_STATE_INVALID = "state_invalid"
OAUTH_ERROR_TOKEN_EXCHANGE_FAILED = "token_exchange_failed"
OAUTH_ERROR_VERIFICATION_FAILED = "verification_failed"

# Admin console auth (issue #154) — third auth track alongside the consumer and
# organizer ones above. No magic link (password + TOTP instead) and no admins
# table (a session just asserts "a valid login happened", nothing per-admin —
# see routers/admin_auth.py), so this token carries no id/version claim, only a
# distinct salt so it can never verify as a user/organizer token or vice versa.
AUTH_ADMIN_SESSION_SALT = "admin-session-v1"
ADMIN_SESSION_COOKIE_NAME = "admin_session"
# Scoped under /api/admin like the organizer cookie is scoped under
# /api/organizer — an admin route added outside /admin/* would silently 401.
ADMIN_SESSION_COOKIE_PATH = "/api/admin"
# 12h, shorter than the 2-day consumer/organizer TTL — a higher-value credential
# with no revocation mechanism beyond expiry (see docs/adr/0001).
ADMIN_SESSION_TTL_SECONDS = 12 * 60 * 60
# One 30s step of drift tolerance either side of "now" (pyotp's valid_window is a
# count of steps, not seconds; app/auth/totp.py) — accounts for clock skew between
# the admin's authenticator app and this server without materially widening the
# guess window.
ADMIN_TOTP_VALID_WINDOW = 1
# _admin_session_epoch()'s hexdigest truncation length (app/auth/tokens.py) —
# 16 hex chars (64 bits) of the HMAC-SHA256 digest is ample for a value that
# only ever gates an already-signed token, not a standalone credential.
ADMIN_SESSION_EPOCH_HASH_LEN = 16

# Per-email magic-link resend cooldown (routers/auth.py::_recent_unused_link_exists) —
# prevents Resend quota exhaustion from rapid repeat requests for the same address.
MAGIC_LINK_RESEND_COOLDOWN_SECONDS = 120

# PII masking — number of leading local-part characters kept visible by mask_email()
# (routers/utils.py) so log lines stay correlatable without persisting raw addresses.
EMAIL_MASK_VISIBLE_CHARS = 2

# Auth success-detail response strings, shared verbatim across the consumer,
# organizer, and admin tracks (each track's endpoint file imports the subset
# it needs). Anti-enumeration responses (request-link) are deliberately
# identical whether or not the address is registered.
DETAIL_MAGIC_LINK_SENT = "If that address is registered, a sign-in link has been sent."
DETAIL_SIGNED_IN = "Signed in."
DETAIL_SIGNED_OUT = "Signed out."
DETAIL_SIGNED_OUT_ALL = "Signed out of all devices."
DETAIL_IDENTITY_UNLINKED = "Identity unlinked."

# Daily cap (process-wide, not per-IP) on new unverified User/Organizer rows
# created via the magic-link request endpoints before an operator alert fires
# — an early signal ahead of Resend's own sender-reputation/quota controls
# (OWASP audit F10). Well above realistic organic signup volume for this
# single-city MVP; tune from real data once there's a baseline.
UNVERIFIED_ACCOUNT_DAILY_BUDGET = 200

# Magic-link verify path defaults — app/auth/email.py::send_magic_link's
# verify_path parameter, and organizer_auth.py's override of it.
AUTH_VERIFY_PATH = "/auth/verify"
ORGANIZER_AUTH_VERIFY_PATH = "/organizer/verify"

# HTTP error `detail` strings (app/routers/*). English-only server strings,
# not i18n keys (contrast shared/i18n/*.json, the user-facing string source
# of truth) — these are internal API error text, not rendered UI copy.
# f"…{var}…" details stay as {placeholder} format templates here, .format()'d
# at the call site.

# Auth (routers/auth.py + routers/organizer_auth.py) — identical wording on
# both the user and organizer auth tracks; duplicated verbatim before this.
ERROR_MISSING_SESSION_COOKIE = "Missing session cookie"
ERROR_SESSION_INVALID = "Session token expired or invalid"
ERROR_SESSION_REVOKED = "Session revoked. Please sign in again."
ERROR_MAGIC_LINK_EXPIRED = "Sign-in link has expired. Please request a new one."
ERROR_MAGIC_LINK_INVALID = "Invalid sign-in link."
ERROR_MAGIC_LINK_CONSUMED = "Sign-in link already used, expired, or not found."

ERROR_USER_NOT_FOUND = "User not found."

ERROR_IDENTITY_NOT_FOUND = "No linked identity found for that provider."

# routers/admin.py
ERROR_ADMIN_LOCKOUT = "Too many failed admin login attempts; try again later."
ERROR_ADMIN_DISABLED = (
    "Admin endpoints disabled: ADMIN_USERNAME left at its default value"
)
ERROR_ADMIN_INCORRECT_CREDENTIALS = "Incorrect credentials"

# Request-body bounds (OWASP audit L-6).
AUTH_TOKEN_MAX_LEN = 2048

# Estonia Concert Hall's Piletilevi session JWT: header.payload.signature, with
# payload base64url-encoded unpadded (padded to a multiple of 4 to decode).
JWT_SEGMENT_COUNT = 3
JWT_PAYLOAD_INDEX = 1
BASE64_PAD_MULTIPLE = 4
