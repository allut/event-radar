"""Helpers shared across the ranking test modules."""

from datetime import datetime, timedelta
from typing import cast
from unittest.mock import MagicMock

from app.constants.core import TALLINN_TZ
from app.models.events import Event
from app.ranking.score import FeedbackContext, _FeedbackRow


def fixed_now() -> datetime:
    return datetime(2026, 5, 10, 9, 0, 0, tzinfo=TALLINN_TZ)



def make_event(
    event_id: int = 1,
    starts_at: datetime | None = None,
    categories: list[str] | None = None,
    vibes: list[str] | None = None,
    quality: float = 0.7,
    lat: float = 59.437,
    lng: float = 24.745,
    dedup_group: int | None = None,
    venue_id: int | None = None,
    venue: MagicMock | None = None,
) -> Event:
    e = MagicMock()
    e.id = event_id
    e.starts_at = starts_at or (fixed_now() + timedelta(days=2))
    e.lat = lat
    e.lng = lng
    e.venue_id = venue_id
    e.venue = venue
    e.dedup_group_id = dedup_group
    cl = MagicMock()
    cl.categories = categories or ["music"]
    cl.vibes = vibes or ["underground"]
    cl.quality_score = quality
    e.classification = cl
    return cast(Event, e)


def make_ctx(*rows: tuple[str, int, list[str], int | None, datetime]) -> FeedbackContext:
    fb_rows = [
        _FeedbackRow(signal=sig, event_id=eid, categories=cats, dedup_group_id=grp, created_at=ts)
        for sig, eid, cats, grp, ts in rows
    ]
    disliked_groups = frozenset(
        r.dedup_group_id
        for r in fb_rows
        if r.signal == "dislike" and r.dedup_group_id is not None
    )
    disliked_event_ids = frozenset(r.event_id for r in fb_rows if r.signal == "dislike")
    direct_map: dict[int, list[_FeedbackRow]] = {}
    for r in fb_rows:
        direct_map.setdefault(r.event_id, []).append(r)
    liked_rows = [r for r in fb_rows if r.signal == "like"]
    return FeedbackContext(
        rows=fb_rows,
        disliked_groups=disliked_groups,
        disliked_event_ids=disliked_event_ids,
        direct_map=direct_map,
        liked_rows=liked_rows,
    )
