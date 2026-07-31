"""User settings endpoints — read and update profile preferences."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import RATE_LIMIT_AUTHENTICATED_WRITE, VALID_LOCALES
from app.db import get_db
from app.models.models import Persona, User, UserPersona
from app.rate_limit import limiter
from app.routers.auth import get_current_user
from app.routers.utils import (
    compute_preferred_taxonomy,
    persona_weight_tuple,
    serialize_user,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/users/me", tags=["settings"])


class PatchSettingsBody(BaseModel):
    locale: str | None = None
    email_digest_opt_in: bool | None = None

    @field_validator("locale")
    @classmethod
    def locale_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_LOCALES:
            raise ValueError(f"locale must be one of {sorted(VALID_LOCALES)}")
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


@router.patch("", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTHENTICATED_WRITE)
async def patch_settings(
    body: PatchSettingsBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update locale and/or email digest preference."""
    if body.locale is None and body.email_digest_opt_in is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one field to update.",
        )

    if body.locale is not None:
        current_user.locale = body.locale
    if body.email_digest_opt_in is not None:
        current_user.email_digest_opt_in = body.email_digest_opt_in

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
