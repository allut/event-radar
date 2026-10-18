"""Promotion content snapshots: what a Promotion displayed, append-only."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.core import LOCALE_ET, LOCALE_EN, LOCALE_RU
from app.constants.promotions import (
    PROMOTION_LABEL_TEXT_TEMPLATE,
    PROMOTION_SNAPSHOT_DESCRIPTION_MAX_CHARS,
)
from app.events.localize import resolve_description, resolve_title
from app.models.models import Event, Promotion, PromotionSnapshot


def label_text(promotion: Promotion) -> str:
    return PROMOTION_LABEL_TEXT_TEMPLATE.format(advertiser=promotion.advertiser_legal_name)


def description_excerpt(event: Event) -> str | None:
    text = (resolve_description(event, LOCALE_EN) or "").strip()
    return text[:PROMOTION_SNAPSHOT_DESCRIPTION_MAX_CHARS] or None


async def take_snapshot(
    db: AsyncSession, promotion: Promotion, event: Event, now: datetime, trigger: str
) -> PromotionSnapshot:
    """Record what `promotion` displays now. Flushes; the caller commits."""
    snapshot = PromotionSnapshot(
        promotion_id=promotion.id,
        taken_at=now,
        trigger=trigger,
        event_id=event.id,
        title_et=resolve_title(event, LOCALE_ET),
        title_en=resolve_title(event, LOCALE_EN),
        title_ru=resolve_title(event, LOCALE_RU),
        description_excerpt=description_excerpt(event),
        image_url=event.image_url,
        venue_name=event.venue_name,
        event_starts_at=event.starts_at,
        event_ends_at=event.ends_at,
        start_date=promotion.start_date,
        end_date=promotion.end_date,
        net_price_cents=promotion.net_price_cents,
        vat_rate_percent=promotion.vat_rate_percent,
        label_text=label_text(promotion),
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


async def list_snapshots(db: AsyncSession, promotion_id: int) -> list[PromotionSnapshot]:
    """Newest first."""
    return list(
        (
            await db.scalars(
                select(PromotionSnapshot)
                .where(PromotionSnapshot.promotion_id == promotion_id)
                .order_by(PromotionSnapshot.id.desc())
            )
        ).all()
    )


def serialize_snapshot(snapshot: PromotionSnapshot) -> dict:
    return {
        "id": snapshot.id,
        "taken_at": snapshot.taken_at.isoformat(),
        "trigger": snapshot.trigger,
        "event_id": snapshot.event_id,
        "title": {
            LOCALE_ET: snapshot.title_et,
            LOCALE_EN: snapshot.title_en,
            LOCALE_RU: snapshot.title_ru,
        },
        "description_excerpt": snapshot.description_excerpt,
        "image_url": snapshot.image_url,
        "venue_name": snapshot.venue_name,
        "event_starts_at": snapshot.event_starts_at.isoformat() if snapshot.event_starts_at else None,
        "event_ends_at": snapshot.event_ends_at.isoformat() if snapshot.event_ends_at else None,
        "start_date": snapshot.start_date.isoformat(),
        "end_date": snapshot.end_date.isoformat(),
        "net_price_cents": snapshot.net_price_cents,
        "vat_rate_percent": str(snapshot.vat_rate_percent),
        "label_text": snapshot.label_text,
    }
