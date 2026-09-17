"""Onboarding endpoint — persona selection."""

import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    status,
)
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    ERROR_PERSONA_COUNT,
    ERROR_PERSONA_DUPLICATE,
    ERROR_PERSONA_UNKNOWN,
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
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set (or replace) the user's ranked persona selection (1-3, first pick leads)."""
    slugs = body.persona_slugs

    if not 1 <= len(slugs) <= PERSONA_MAX_SELECTABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_PERSONA_COUNT.format(max_selectable=PERSONA_MAX_SELECTABLE),
        )

    if len(set(slugs)) != len(slugs):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_PERSONA_DUPLICATE,
        )

    personas = (await db.scalars(select(Persona).where(Persona.slug.in_(slugs)))).all()

    found_slugs = {p.slug for p in personas}
    missing = set(slugs) - found_slugs
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_PERSONA_UNKNOWN.format(missing=sorted(missing)),
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

    await invalidate_user_scores(db, current_user.id)
    await db.commit()

    background_tasks.add_task(_build_initial_feed, current_user.id)

    return {"personas": result}


async def _build_initial_feed(user_id: int) -> None:
    """Best-effort initial feed build, run after the response is sent.

    Moved off the request path (Big-O audit #5, item 1.2) — the full
    candidate-catalogue load + scoring pass in build_daily_feed_for_user is
    too expensive to run synchronously inside a rate-limited HTTP request.
    Uses its own DB session since the request-scoped one is already closed.
    """
    async for session in get_db():
        try:
            await build_daily_feed_for_user(session, user_id)
        except Exception:
            log.exception("initial feed build failed for user %s", user_id)
