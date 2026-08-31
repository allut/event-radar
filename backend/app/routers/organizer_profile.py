"""Organizer profile — optional display name (#175).

Independent of the Venue work (#171/#174): nothing here prefills into
SubmitEventBody. GET backs the dashboard/submit nudge banner (has the
organizer set a name yet?); PATCH updates it, scoped to get_current_organizer.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import ORGANIZER_NAME_MAX_LEN, RATE_LIMIT_SUBMIT
from app.db import get_db
from app.models.models import Organizer
from app.rate_limit import limiter
from app.routers.organizer_auth import get_current_organizer

router = APIRouter(prefix="/organizer/profile", tags=["organizer-profile"])


class OrganizerProfilePatchBody(BaseModel):
    name: str | None = Field(None, max_length=ORGANIZER_NAME_MAX_LEN)


def _serialize(organizer: Organizer) -> dict:
    return {
        "id": organizer.id,
        "email": organizer.email,
        "locale": organizer.locale,
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
    await db.commit()
    await db.refresh(current_organizer)
    return _serialize(current_organizer)
