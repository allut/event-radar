"""User settings endpoints — read and update profile preferences."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import generate_session_token
from app._generated.shared_constants import VALID_LOCALES
from app.constants.auth import (
    DETAIL_IDENTITY_UNLINKED,
    ERROR_IDENTITY_NOT_FOUND,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_PATH,
)
from app.constants.email import (
    CONSENT_SOURCE_SETTINGS,
    EMAIL_AD_CONSENT_WORDING_VERSION,
    ERROR_AD_CONSENT_UNAVAILABLE,
)
from app.constants.core import ERROR_NO_UPDATE_FIELDS, SECONDS_PER_DAY
from app.constants.log_events import LOG_EVENT_IDENTITY_UNLINKED
from app.constants.rate_limits import RATE_LIMIT_AUTHENTICATED_WRITE
from app.config import settings
from app.db import get_db
from app.email.consent import grant_ad_consent, withdraw_ad_consent
from app.email.subscription import set_digest_subscription
from app.models.users import Persona, User, UserIdentity, UserPersona
from app.rate_limit import limiter
from app.auth.dependencies import get_current_user
from app.routers.utils import (
    compute_preferred_taxonomy,
    is_identity_linked,
    serialize_user,
    set_session_cookie,
)
from app.ranking.score import persona_weight_tuple

log = logging.getLogger(__name__)
router = APIRouter(prefix="/users/me", tags=["settings"])


class PatchSettingsBody(BaseModel):
    locale: str | None = None
    email_digest_opt_in: bool | None = None
    email_ad_consent: bool | None = None

    @field_validator("locale")
    @classmethod
    def locale_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_LOCALES:
            raise ValueError(f"locale must be one of {sorted(VALID_LOCALES)}")
        return v


def _consent_fields(user: User) -> dict:
    """Email ad consent state for the Settings toggle. `available` is when the
    toggle may show and be turned on: digest on and the slots flag on."""
    return {
        "email_ad_consent": user.email_ad_consent,
        "email_ad_consent_available": _consent_available(user),
        "email_ad_consent_wording_version": EMAIL_AD_CONSENT_WORDING_VERSION,
    }


def _consent_available(user: User) -> bool:
    return bool(user.email_digest_opt_in and settings.PROMOTIONS_SLOTS_ENABLED)


async def _load_persona_data(
    user_id: int, db: AsyncSession
) -> tuple[list[dict], list[tuple[float, dict]]]:
    """(persona display list, [(weight, affinity_vector), ...]) — one query,
    reused both for the settings persona display and preferred_categories/
    preferred_vibes (compute_preferred_taxonomy)."""
    rows = (
        await db.execute(
            select(UserPersona, Persona)
            .join(Persona, UserPersona.persona_id == Persona.id)
            .where(UserPersona.user_id == user_id)
            .order_by(UserPersona.weight.desc())
        )
    ).all()
    personas = [
        {
            "slug": persona.slug,
            "display_name_en": persona.display_name_en,
            "display_name_et": persona.display_name_et,
            "display_name_ru": persona.display_name_ru,
            "weight": up.weight,
        }
        for up, persona in rows
    ]
    weights = [persona_weight_tuple(up, persona) for up, persona in rows]
    return personas, weights


@router.get("", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTHENTICATED_WRITE)
async def get_settings(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return current user profile + settings."""
    personas, weights = await _load_persona_data(current_user.id, db)
    preferred_categories, preferred_vibes = compute_preferred_taxonomy(weights)
    google_linked = await is_identity_linked(
        db, UserIdentity, UserIdentity.user_id, current_user.id
    )
    return serialize_user(
        current_user,
        email_digest_opt_in=current_user.email_digest_opt_in,
        **_consent_fields(current_user),
        personas=personas,
        preferred_categories=preferred_categories,
        preferred_vibes=preferred_vibes,
        google_linked=google_linked,
    )


@router.delete("/identities/{provider}", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTHENTICATED_WRITE)
async def unlink_own_identity(
    provider: str,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Unconditional unlink (ADR 0002) — no last-factor guard, since magic
    link always remains as a sign-in path. Bumps session_token_version (a
    sign-out-everywhere shape) and immediately re-issues the caller's own
    session cookie at the new version, so only *other* devices drop. Mirrors
    organizer_profile.py::unlink_own_identity."""
    result = await db.execute(
        delete(UserIdentity)
        .where(
            UserIdentity.user_id == current_user.id,
            UserIdentity.provider == provider,
        )
        .returning(UserIdentity.id)
    )
    if result.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_IDENTITY_NOT_FOUND
        )

    # Atomic UPDATE — same race-safe pattern as auth.py::logout_all.
    version_result = await db.execute(
        update(User)
        .where(User.id == current_user.id)
        .values(session_token_version=User.session_token_version + 1)
        .returning(User.session_token_version)
    )
    current_user.session_token_version = version_result.scalar_one()
    await db.commit()

    log.info(
        "user identity unlinked: user_id=%s provider=%s",
        current_user.id,
        provider,
        extra={"event": LOG_EVENT_IDENTITY_UNLINKED, "provider": provider},
    )

    session_token = generate_session_token(current_user.id, current_user.session_token_version)
    set_session_cookie(
        response,
        name=SESSION_COOKIE_NAME,
        token=session_token,
        path=SESSION_COOKIE_PATH,
        ttl_seconds=settings.SESSION_TTL_DAYS * SECONDS_PER_DAY,
    )
    return {"detail": DETAIL_IDENTITY_UNLINKED}


@router.patch("", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTHENTICATED_WRITE)
async def patch_settings(
    body: PatchSettingsBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update locale and/or email digest preference."""
    if (
        body.locale is None
        and body.email_digest_opt_in is None
        and body.email_ad_consent is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_NO_UPDATE_FIELDS,
        )

    if body.locale is not None:
        current_user.locale = body.locale
    if body.email_digest_opt_in is not None:
        set_digest_subscription(current_user, body.email_digest_opt_in, db)
    if body.email_ad_consent is True:
        if not _consent_available(current_user):
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ERROR_AD_CONSENT_UNAVAILABLE,
            )
        grant_ad_consent(current_user, db, CONSENT_SOURCE_SETTINGS)
    elif body.email_ad_consent is False:
        withdraw_ad_consent(current_user, db, CONSENT_SOURCE_SETTINGS)

    await db.commit()
    await db.refresh(current_user)

    personas, weights = await _load_persona_data(current_user.id, db)
    preferred_categories, preferred_vibes = compute_preferred_taxonomy(weights)
    google_linked = await is_identity_linked(
        db, UserIdentity, UserIdentity.user_id, current_user.id
    )
    return serialize_user(
        current_user,
        email_digest_opt_in=current_user.email_digest_opt_in,
        **_consent_fields(current_user),
        personas=personas,
        preferred_categories=preferred_categories,
        preferred_vibes=preferred_vibes,
        google_linked=google_linked,
    )
