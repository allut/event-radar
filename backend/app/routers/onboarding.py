"""Onboarding endpoint — persona selection."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    PERSONA_MAX_SELECTABLE,
    PERSONA_RANK_WEIGHTS,
    RATE_LIMIT_AUTHENTICATED_WRITE,
)
from app.db import get_db
from app.models.models import Persona, User, UserPersona
from app.ranking.score import build_daily_feed_for_user
from app.rate_limit import limiter
from app.routers.auth import get_current_user
from app.routers.utils import invalidate_user_scores

log = logging.getLogger(__name__)
router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class PersonaBody(BaseModel):
    persona_slugs: list[str]


@router.post("/persona", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTHENTICATED_WRITE)
async def set_persona(
    body: PersonaBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set (or replace) the user's ranked persona selection (1-3, first pick leads)."""
    slugs = body.persona_slugs

    if not 1 <= len(slugs) <= PERSONA_MAX_SELECTABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Select between 1 and {PERSONA_MAX_SELECTABLE} personas.",
        )

    if len(set(slugs)) != len(slugs):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Persona slugs must not repeat.",
        )

    personas = (await db.scalars(select(Persona).where(Persona.slug.in_(slugs)))).all()

    found_slugs = {p.slug for p in personas}
    missing = set(slugs) - found_slugs
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown persona slug(s): {sorted(missing)}",
        )

    # Replace existing selections atomically
    await db.execute(delete(UserPersona).where(UserPersona.user_id == current_user.id))

    persona_by_slug = {p.slug: p for p in personas}
    result = []
    for i, slug in enumerate(slugs):
        weight = PERSONA_RANK_WEIGHTS[i]
        db.add(
            UserPersona(
                user_id=current_user.id,
                persona_id=persona_by_slug[slug].id,
                weight=weight,
            )
        )
        result.append({"slug": slug, "weight": weight})

    await db.commit()

    try:
        await invalidate_user_scores(db, current_user.id)
        await build_daily_feed_for_user(db, current_user.id)
    except Exception:
        log.exception("initial feed build failed for user %s", current_user.id)

    return {"personas": result}
