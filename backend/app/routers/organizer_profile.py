"""Organizer profile — optional display name (#175).

Independent of the Venue work (#171/#174): nothing here prefills into
SubmitEventBody. GET backs the dashboard/submit nudge banner (has the
organizer set a name yet?); PATCH updates it, scoped to get_current_organizer.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    ORGANIZER_NAME_MAX_LEN,
    RATE_LIMIT_SUBMIT,
    VALID_THEME_PREFERENCES,
)
from app.db import get_db
from app.models.models import Organizer
from app.rate_limit import limiter
from app.routers.organizer_auth import get_current_organizer

router = APIRouter(prefix="/organizer/profile", tags=["organizer-profile"])


class OrganizerProfilePatchBody(BaseModel):
    name: str | None = Field(None, max_length=ORGANIZER_NAME_MAX_LEN)
    theme_preference: str | None = None

    @field_validator("theme_preference")
    @classmethod
    def theme_preference_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_THEME_PREFERENCES:
            raise ValueError(
                f"theme_preference must be one of {sorted(VALID_THEME_PREFERENCES)}"
            )
        return v


def _serialize(organizer: Organizer) -> dict:
    return {
        "id": organizer.id,
        "email": organizer.email,
        "locale": organizer.locale,
        "theme_preference": organizer.theme_preference,
        "verified": organizer.verified,
        "name": organizer.name,
    }


@router.get("")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def get_own_profile(
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
) -> dict:
    return _serialize(current_organizer)


@router.patch("")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def update_own_profile(
    body: OrganizerProfilePatchBody,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if "name" in body.model_fields_set:
        stripped = body.name.strip() if body.name else None
        current_organizer.name = stripped or None
    if body.theme_preference is not None:
        current_organizer.theme_preference = body.theme_preference
    await db.commit()
    await db.refresh(current_organizer)
    return _serialize(current_organizer)
