"""User settings endpoints — read and update profile preferences."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DEFAULT_USER_LOCALE, PERSONA_PRIMARY_WEIGHT, PERSONA_SECONDARY_WEIGHT, VALID_LOCALES
from app.db import get_db
from app.models.models import Persona, User, UserPersona
from app.routers.auth import get_current_user
from app.routers.utils import serialize_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/users/me", tags=["settings"])


class PatchSettingsBody(BaseModel):
    locale: Optional[str] = None
    email_digest_opt_in: Optional[bool] = None

    @field_validator("locale")
    @classmethod
    def locale_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_LOCALES:
            raise ValueError(f"locale must be one of {sorted(VALID_LOCALES)}")
        return v


async def _get_persona_list(user_id: int, db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(
            select(UserPersona, Persona)
            .join(Persona, UserPersona.persona_id == Persona.id)
            .where(UserPersona.user_id == user_id)
            .order_by(UserPersona.weight.desc())
        )
    ).all()
    return [
        {
            "slug": persona.slug,
            "display_name_en": persona.display_name_en,
            "display_name_et": persona.display_name_et,
            "display_name_ru": persona.display_name_ru,
            "weight": up.weight,
        }
        for up, persona in rows
    ]


@router.get("", status_code=status.HTTP_200_OK)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current user profile + settings."""
    personas = await _get_persona_list(current_user.id, db)
    return serialize_user(
        current_user,
        email_digest_opt_in=current_user.email_digest_opt_in,
        personas=personas,
    )


@router.patch("", status_code=status.HTTP_200_OK)
async def patch_settings(
    body: PatchSettingsBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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

    personas = await _get_persona_list(current_user.id, db)
    return serialize_user(
        current_user,
        email_digest_opt_in=current_user.email_digest_opt_in,
        personas=personas,
    )
