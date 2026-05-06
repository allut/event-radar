"""Onboarding endpoint — persona selection."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import PERSONA_PRIMARY_WEIGHT, PERSONA_SECONDARY_WEIGHT
from app.db import get_db
from app.models.models import Persona, User, UserPersona
from app.routers.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class PersonaBody(BaseModel):
    primary_slug: str
    secondary_slug: Optional[str] = None


@router.post("/persona", status_code=status.HTTP_200_OK)
async def set_persona(
    body: PersonaBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set (or replace) the user's persona selection."""
    slugs = [body.primary_slug]
    if body.secondary_slug:
        if body.secondary_slug == body.primary_slug:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Primary and secondary personas must differ.",
            )
        slugs.append(body.secondary_slug)

    personas = (
        await db.scalars(select(Persona).where(Persona.slug.in_(slugs)))
    ).all()

    found_slugs = {p.slug for p in personas}
    missing = set(slugs) - found_slugs
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown persona slug(s): {sorted(missing)}",
        )

    # Replace existing selections atomically
    await db.execute(
        delete(UserPersona).where(UserPersona.user_id == current_user.id)
    )

    persona_by_slug = {p.slug: p for p in personas}
    db.add(
        UserPersona(
            user_id=current_user.id,
            persona_id=persona_by_slug[body.primary_slug].id,
            weight=PERSONA_PRIMARY_WEIGHT,
        )
    )
    if body.secondary_slug:
        db.add(
            UserPersona(
                user_id=current_user.id,
                persona_id=persona_by_slug[body.secondary_slug].id,
                weight=PERSONA_SECONDARY_WEIGHT,
            )
        )

    await db.commit()

    result = [{"slug": body.primary_slug, "weight": PERSONA_PRIMARY_WEIGHT}]
    if body.secondary_slug:
        result.append({"slug": body.secondary_slug, "weight": PERSONA_SECONDARY_WEIGHT})

    return {"personas": result}
