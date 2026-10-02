"""Event query predicates and series identity shared by the feed, publish gate,
claims and dedup — the one home for "which events count" definitions."""

from datetime import datetime
from typing import Any

from sqlalchemy import and_, ColumnElement, false, func, or_

from app.constants import EVENT_STATUS_PUBLISHED
from app.models.models import Event


def canonical_event_filter() -> ColumnElement[bool]:
    """Event is dedup-canonical: ungrouped, or the representative of its group.

    Shared by any query that must not surface a duplicate a second time —
    ``classify_pending`` only classifies canonical drafts, ``admin_stats``
    counts canonical events, and the Daily 5 candidate query excludes
    non-canonical duplicates that were somehow already published (dedup
    normally runs before classify/publish, so this is a defense-in-depth
    backstop, not the primary suppression mechanism).
    """
    return or_(Event.dedup_group_id.is_(None), Event.dedup_group_id == Event.id)


def public_event_filter() -> ColumnElement[bool]:
    """Event is publicly visible: published, and neither explicit nor a non-event.

    Shared by any endpoint that accepts a caller-supplied event_id and must not
    leak the existence of a draft/hidden/explicit/non-event row via a 200-vs-404
    timing or status-code oracle (e.g. GET /events/{id}, POST /feedback).
    """
    return and_(
        Event.status == EVENT_STATUS_PUBLISHED,
        Event.is_explicit == false(),
        Event.is_non_event == false(),
    )


def event_not_ended_filter(now: datetime, entity: Any = Event) -> ColumnElement[bool]:
    """Event is live (publishable / feed-eligible) until it ends.

    Uses ``ends_at`` when present, else falls back to ``starts_at``. A past
    ``starts_at`` with a future ``ends_at`` (multi-day runs, ongoing
    exhibitions) stays live — only a genuinely-over event fails this.

    Written as ``coalesce(ends_at, starts_at) >= now`` — exactly equivalent
    to the OR form, but sargable against ``ix_events_live_until ON events
    (coalesce(ends_at, starts_at))`` (migration ``0023``). The OR form
    Postgres cannot match to that expression index, forcing a seq scan on
    ``events`` (a table rows are never removed from — see ``cleanup.py``) at
    every call site.

    ``entity`` accepts ``Event`` (default) or an ``aliased(Event)`` so
    self-join clauses reuse this definition instead of re-deriving it.
    """
    return func.coalesce(entity.ends_at, entity.starts_at) >= now


def event_ended_filter(now: datetime, entity: Any = Event) -> ColumnElement[bool]:
    """Event has ended — the complement of ``event_not_ended_filter``.

    Also written via ``coalesce`` (see ``event_not_ended_filter``) so it hits
    the same index. Unlike the old OR form, ``coalesce(...) < now`` carries
    no three-valued-logic trap: ``coalesce`` never evaluates to NULL here
    (``starts_at`` is NOT NULL), so this is safe to use directly — no need to
    build the negation of ``event_not_ended_filter`` by hand.
    """
    return func.coalesce(entity.ends_at, entity.starts_at) < now


def normalized_title(title: str) -> str:
    """Canonical title key: lowercase + collapse all internal whitespace.

    Shared by dedup same-day bucketing (``apply_same_day_title_unions``) and the
    feed-level series identity (``event_series_key``) so both agree on what
    counts as "the same title".
    """
    return " ".join(title.lower().split())


def event_series_key(title_orig: str, venue_name: str | None) -> tuple[str, str]:
    """Identity of an ongoing series, independent of ``starts_at``.

    Deliberately broader than the dedup same-day title bucket (which is per-day
    and feeds dedup) and independent of ``dedup_group_id`` (multi-day series are
    intentionally not dedup-grouped). Used by the Daily 5 builder to cool down a
    series already surfaced within the recent cooldown window.

    Both halves go through ``normalized_title`` (lowercase + collapse internal
    whitespace) so the same series still matches across minor venue-string drift
    between ingest/refetch passes. Match is exact on the normalized key — venue
    respellings beyond whitespace/case (a parenthetical suffix, a translation)
    are an accepted limitation, since the cooldown is a soft feed-diversity
    filter, not a correctness gate.
    """
    return (normalized_title(title_orig), normalized_title(venue_name or ""))


def serialize_event_series_key(key: tuple[str, str]) -> str:
    """``event_series_key()``'s tuple, flattened to the single-string form
    stored in ``Claim.event_series_key`` (models.py docstring) — a Series
    claim's key column can't hold a tuple, and the U+001F separator can never
    appear in either half (both go through ``normalized_title``, which only
    ever produces lowercase text and single spaces)."""
    title_key, venue_key = key
    return f"{title_key}\x1f{venue_key}"
