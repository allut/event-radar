"""Auth-domain helpers shared across routers and domain packages: email
normalization/masking and the fail-closed secret gate."""

import logging
from datetime import datetime, timezone
from typing import Protocol

from fastapi import HTTPException, status

from app.constants.auth import EMAIL_MASK_VISIBLE_CHARS
from app.constants.core import APP_ENV_DEVELOPMENT
from app.constants.security import ERROR_FEATURE_DISABLED

log = logging.getLogger(__name__)


class _VerifiableOrganizer(Protocol):
    email_verified_at: datetime | None


def mark_organizer_verified(organizer: _VerifiableOrganizer) -> bool:
    """Stamp ``email_verified_at`` the first time an organizer authenticates
    (magic link, claim link, Google). Returns True when the caller must commit.
    Without this durable signal the weekly cleanup cannot tell an
    authenticated organizer from a never-proven one once their magic-link rows
    are pruned."""
    if organizer.email_verified_at is not None:
        return False
    organizer.email_verified_at = datetime.now(timezone.utc)
    return True


def mask_email(email: str) -> str:
    """Mask an email for log output — keep the first few local-part characters and
    the full domain so entries stay correlatable without persisting raw PII in
    cleartext logs (e.g. 'jane.doe@example.com' -> 'ja***@example.com')."""
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    return f"{local[:EMAIL_MASK_VISIBLE_CHARS]}***@{domain}"


def normalize_email(email: str) -> str:
    """Canonical comparison form for an email address — strip surrounding
    whitespace, lowercase. Shared by both sides of the Piletilevi mailbox-
    match auto-grant check (`piletilevi_promoter.py::extract_contact_email`'s
    stored contact and `verification.py::verify_piletilevi_claim`'s claimant
    email) so the two normalizations can't drift independently (#439)."""
    return email.strip().lower()


def require_configured_secret(
    secret: str | None,
    *,
    feature: str,
    setting_name: str,
    app_env: str,
    allow_insecure_dev: bool = False,
) -> bool:
    """Fail-closed gate shared by every secret-protected surface (admin auth,
    inbound webhook).

    Returns True when the secret is configured — the caller must then verify
    it. When unset: 503 unless BOTH ``app_env == development`` AND
    ``allow_insecure_dev`` are true, in which case a warning is logged and
    False is returned (caller skips verification). Requiring the second,
    explicit opt-in (settings.ALLOW_INSECURE_DEV) means a dev-shaped APP_ENV
    alone — e.g. a misconfigured or never-overridden env var on a real
    deployment — can never silently open the admin surface or the inbound
    webhook. Callers pass their own module's ``settings`` values so tests
    that patch the caller's settings keep working.
    """
    if secret:
        return True
    if not (app_env == APP_ENV_DEVELOPMENT and allow_insecure_dev):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ERROR_FEATURE_DISABLED.format(
                feature=feature, setting_name=setting_name
            ),
        )
    log.warning(
        "%s not set; %s unprotected (development mode, ALLOW_INSECURE_DEV=true)",
        setting_name,
        feature,
    )
    return False
