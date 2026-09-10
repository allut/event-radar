"""User settings endpoints — read and update profile preferences."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import generate_session_token
from app.constants import (
    ERROR_IDENTITY_NOT_FOUND,
    ERROR_NO_UPDATE_FIELDS,
    LOG_EVENT_IDENTITY_UNLINKED,
    RATE_LIMIT_AUTHENTICATED_WRITE,
    SECONDS_PER_DAY,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_PATH,
    VALID_LOCALES,
    VALID_THEME_PREFERENCES,
)
from app.config import settings
from app.db import get_db
from app.models.models import Persona, User, UserIdentity, UserPersona
from app.rate_limit import limiter
from app.routers.auth import get_current_user
from app.routers.utils import (
    compute_preferred_taxonomy,
    persona_weight_tuple,
    serialize_user,
    set_session_cookie,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/users/me", tags=["settings"])


class PatchSettingsBody(BaseModel):
    locale: str | None = None
    email_digest_opt_in: bool | None = None
    theme_preference: str | None = None

    @field_validator("locale")
    @classmethod
    def locale_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_LOCALES:
            raise ValueError(f"locale must be one of {sorted(VALID_LOCALES)}")
        return v

    @field_validator("theme_preference")
    @classmethod
    def theme_preference_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_THEME_PREFERENCES:
            raise ValueError(
                f"theme_preference must be one of {sorted(VALID_THEME_PREFERENCES)}"
            )
        return v


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
    return serialize_user(
        current_user,
        email_digest_opt_in=current_user.email_digest_opt_in,
        personas=personas,
        preferred_categories=preferred_categories,
        preferred_vibes=preferred_vibes,
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
    return {"detail": "Identity unlinked."}


@router.patch("", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTHENTICATED_WRITE)
async def patch_settings(
    body: PatchSettingsBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update locale, email digest preference, and/or theme preference.

    An explicitly-sent `theme_preference: null` clears the account column
    back to "no preference" (the client's way of durably reverting to
    System, #257) — distinct from omitting the field, which leaves the
    existing value untouched. Distinguished via `model_fields_set` since
    both cases parse to `None` on the model.
    """
    if (
        body.locale is None
        and body.email_digest_opt_in is None
        and "theme_preference" not in body.model_fields_set
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_NO_UPDATE_FIELDS,
        )

    if body.locale is not None:
        current_user.locale = body.locale
    if body.email_digest_opt_in is not None:
        current_user.email_digest_opt_in = body.email_digest_opt_in
    if "theme_preference" in body.model_fields_set:
        current_user.theme_preference = body.theme_preference

    await db.commit()
    await db.refresh(current_user)

    personas, weights = await _load_persona_data(current_user.id, db)
    preferred_categories, preferred_vibes = compute_preferred_taxonomy(weights)
    return serialize_user(
        current_user,
        email_digest_opt_in=current_user.email_digest_opt_in,
        personas=personas,
        preferred_categories=preferred_categories,
        preferred_vibes=preferred_vibes,
    )
