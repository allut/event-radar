"""Organizer profile — optional display name (#175).

Independent of the Venue work (#171/#174): nothing here prefills into
SubmitEventBody. GET backs the dashboard/submit nudge banner (has the
organizer set a name yet?); PATCH updates it, scoped to get_current_organizer.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import generate_organizer_session_token
from app.constants import (
    DETAIL_IDENTITY_UNLINKED,
    ERROR_IDENTITY_NOT_FOUND,
    LOG_EVENT_IDENTITY_UNLINKED,
    ORGANIZER_NAME_MAX_LEN,
    ORGANIZER_SESSION_COOKIE_NAME,
    ORGANIZER_SESSION_COOKIE_PATH,
    ORGANIZER_SESSION_TTL_DAYS,
    RATE_LIMIT_AUTHENTICATED_WRITE,
    RATE_LIMIT_SUBMIT,
    SECONDS_PER_DAY,
)
from app.db import get_db
from app.models.models import Organizer, OrganizerIdentity
from app.rate_limit import limiter
from app.routers.organizer_auth import get_current_organizer
from app.routers.utils import (
    is_identity_linked,
    set_session_cookie,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/organizer/profile", tags=["organizer-profile"])


class OrganizerProfilePatchBody(BaseModel):
    name: str | None = Field(None, max_length=ORGANIZER_NAME_MAX_LEN)


def _serialize(organizer: Organizer, *, google_linked: bool) -> dict:
    return {
        "id": organizer.id,
        "email": organizer.email,
        "locale": organizer.locale,
        "verified": organizer.verified,
        "name": organizer.name,
        "google_linked": google_linked,
    }


@router.get("")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def get_own_profile(
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    google_linked = await is_identity_linked(
        db, OrganizerIdentity, OrganizerIdentity.organizer_id, current_organizer.id
    )
    return _serialize(current_organizer, google_linked=google_linked)


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
    google_linked = await is_identity_linked(
        db, OrganizerIdentity, OrganizerIdentity.organizer_id, current_organizer.id
    )
    return _serialize(current_organizer, google_linked=google_linked)


@router.delete("/identities/{provider}", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTHENTICATED_WRITE)
async def unlink_own_identity(
    provider: str,
    request: Request,
    response: Response,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Unconditional unlink (ADR 0002) — no last-factor guard, since magic
    link always remains as a sign-in path. Bumps session_token_version (a
    sign-out-everywhere shape) and immediately re-issues the caller's own
    session cookie at the new version, so only *other* devices drop."""
    result = await db.execute(
        delete(OrganizerIdentity)
        .where(
            OrganizerIdentity.organizer_id == current_organizer.id,
            OrganizerIdentity.provider == provider,
        )
        .returning(OrganizerIdentity.id)
    )
    if result.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_IDENTITY_NOT_FOUND
        )

    # Atomic UPDATE — same race-safe pattern as organizer_auth.py::organizer_logout_all.
    version_result = await db.execute(
        update(Organizer)
        .where(Organizer.id == current_organizer.id)
        .values(session_token_version=Organizer.session_token_version + 1)
        .returning(Organizer.session_token_version)
    )
    current_organizer.session_token_version = version_result.scalar_one()
    await db.commit()

    log.info(
        "organizer identity unlinked: organizer_id=%s provider=%s",
        current_organizer.id,
        provider,
        extra={"event": LOG_EVENT_IDENTITY_UNLINKED, "provider": provider},
    )

    session_token = generate_organizer_session_token(
        current_organizer.id, current_organizer.session_token_version
    )
    set_session_cookie(
        response,
        name=ORGANIZER_SESSION_COOKIE_NAME,
        token=session_token,
        path=ORGANIZER_SESSION_COOKIE_PATH,
        ttl_seconds=ORGANIZER_SESSION_TTL_DAYS * SECONDS_PER_DAY,
    )
    return {"detail": DETAIL_IDENTITY_UNLINKED}
