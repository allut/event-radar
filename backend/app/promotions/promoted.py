""""Promoted" trust tagging (#612): an event with a live `paid` Promotion.
Reports on it are tagged, sorted first and marked in the notify subject. A
report never pauses a Promotion; only the fill gate does."""

from datetime import date

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute

from app.constants.promotions import PROMOTION_STATUS_PAID
from app.models.promotions import Promotion


def promoted_clause(event_id_col: QueryableAttribute[int], today: date) -> ColumnElement[bool]:
    """EXISTS a paid Promotion on `event_id_col` whose window covers `today`."""
    return exists().where(
        Promotion.event_id == event_id_col,
        Promotion.status == PROMOTION_STATUS_PAID,
        Promotion.start_date <= today,
        Promotion.end_date >= today,
    )


async def is_event_promoted(db: AsyncSession, event_id: int, today: date) -> bool:
    return (
        await db.scalar(
            select(Promotion.id)
            .where(
                Promotion.event_id == event_id,
                Promotion.status == PROMOTION_STATUS_PAID,
                Promotion.start_date <= today,
                Promotion.end_date >= today,
            )
            .limit(1)
        )
    ) is not None
