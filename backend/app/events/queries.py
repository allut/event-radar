"""Event query predicates and series identity shared by the feed, publish gate,
claims and dedup — the one home for "which events count" definitions."""

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Protocol, TypeVar, cast

from sqlalchemy import Select, and_, ColumnElement, exists, false, func, or_, select, true
from sqlalchemy.orm import aliased, selectinload

from app.constants.core import TALLINN_TZ
from app.constants.events import EVENT_STATUS_CANCELLED, EVENT_STATUS_PUBLISHED
from app.events.venue import resolve_venue_name
from app.models.models import Event, EventClassification


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


def event_date_range_filter(
    date_from: date | None, date_to: date | None
) -> ColumnElement[bool] | None:
    """Overlap check, not starts_at-only: an ongoing exhibition that started
    last month must still match a "Today" filter. Bounds are Tallinn-midnight
    datetimes; date_to is exclusive (next-day midnight).

    Shared by /explore's date facet and /public/counts' ``today_count`` so the
    pulse chip's number always agrees with the page its link lands on."""
    if date_from is None and date_to is None:
        return None
    conditions: list[ColumnElement[bool]] = []
    if date_to is not None:
        date_to_end = datetime.combine(
            date_to + timedelta(days=1), datetime.min.time(), tzinfo=TALLINN_TZ
        )
        conditions.append(Event.starts_at < date_to_end)
    if date_from is not None:
        date_from_start = datetime.combine(
            date_from, datetime.min.time(), tzinfo=TALLINN_TZ
        )
        conditions.append(func.coalesce(Event.ends_at, Event.starts_at) >= date_from_start)
    return and_(*conditions)


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


class SeriesInstance(Protocol):
    """What ``collapse_series_duplicates`` reads: an Event, or a slim row
    carrying the same three columns."""

    @property
    def id(self) -> int: ...

    @property
    def title_orig(self) -> str: ...

    @property
    def starts_at(self) -> datetime: ...


_SeriesT = TypeVar("_SeriesT", bound=SeriesInstance)


def collapse_series_duplicates(
    event_rows: Sequence[_SeriesT],
    venue_name_of: Callable[[_SeriesT], str | None] | None = None,
) -> tuple[list[_SeriesT], dict[int, tuple[str, str]]]:
    """One representative per event_series_key — nearest (earliest) starts_at
    wins; ties broken by event id, so the surviving instance is deterministic
    across builds even when the underlying query has no ORDER BY.

    A multi-date listing (e.g. a workshop running Tue/Thu/Sat) ingests as
    several Event rows sharing a series key but distinct dedup_group_ids
    (recurring series are intentionally not dedup-grouped at ingestion), so
    without this more than one date-instance of the same series could score
    well and both land in a single user's Daily 5 on the same day, or both
    appear in the public showcase grid. Shared by the Daily 5 candidate loader
    (``_load_candidate_events``) and the public showcase (``showcase``), each
    running this once per build/request, upstream of any downstream ordering.

    Returns the collapsed events plus their series keys (each key computed
    exactly once here) so callers building `candidate_series_key` don't
    recompute `event_series_key()` a second time over the same rows.

    ``venue_name_of`` resolves a slim row's venue name; omitted, each row is
    an Event and its linked venue is read.
    """
    earliest_by_key: dict[tuple[str, str], _SeriesT] = {}
    for event in event_rows:
        venue_name = (
            venue_name_of(event)
            if venue_name_of is not None
            else resolve_venue_name(cast(Event, event))
        )
        key = event_series_key(event.title_orig, venue_name)
        current = earliest_by_key.get(key)
        if current is None or (event.starts_at, event.id) < (
            current.starts_at,
            current.id,
        ):
            earliest_by_key[key] = event
    collapsed = list(earliest_by_key.values())
    series_key_by_event_id = {
        event.id: key for key, event in earliest_by_key.items()
    }
    return collapsed, series_key_by_event_id


def select_events_with_classification() -> Select[tuple[Event]]:
    """Base SELECT for Event with classification + linked Venue eager-loaded
    (#177 — venue read-path resolution must not N+1). Callers add their own .where()."""
    return select(Event).options(
        selectinload(Event.classification), selectinload(Event.venue)
    )


def no_live_dedup_sibling_clause(now: datetime) -> ColumnElement[bool]:
    """True when no other, still-live member points its ``dedup_group_id`` at
    this event's id.

    Guards every bulk-cancel sweep (classifier ended-draft sweep, refetch source-gone cancel): a dedup-canonical representative must not be
    cancelled out from under a still-live sibling (same dedup group, not yet
    ended, not already cancelled) — that sibling's ``dedup_group_id`` would
    keep pointing at a cancelled id until the next ``dedup_pass`` reclusters,
    stranding it outside ``canonical_event_filter()`` (and hence unreachable by
    ``classify_pending``) for up to one 6h cycle. Ungrouped events (no row
    references their id as a group) and events with only already-ended or
    already-cancelled siblings are unaffected and cancel normally.
    """
    sibling = aliased(Event)
    return ~exists(
        select(1)
        .select_from(sibling)
        .where(
            sibling.dedup_group_id == Event.id,
            sibling.id != Event.id,
            sibling.status != EVENT_STATUS_CANCELLED,
            event_not_ended_filter(now, entity=sibling),
        )
    )


def escape_ilike_pattern(q: str) -> str:
    """Escape SQL LIKE wildcards in user-supplied search text, wrapped as a
    ``%...%`` substring pattern — otherwise a literal ``%``/``_`` in the
    search box would wildcard-match. Shared by the Explore keyword search and
    organizer_claims.py's claim-discovery search (#414); pass the result to
    ``.ilike(pattern, escape="\\\\")``."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def free_filter() -> ColumnElement[bool]:
    return or_(Event.price_min == 0, Event.has_free_tier == true())


def keyword_filter(q: str) -> ColumnElement[bool]:
    pattern = escape_ilike_pattern(q)
    return or_(
        Event.title_orig.ilike(pattern, escape="\\"),
        Event.description_orig.ilike(pattern, escape="\\"),
    )


def facet_conditions(
    categories: list[str],
    vibes: list[str],
    free: bool,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    now: datetime,
) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [
        public_event_filter(),
        event_not_ended_filter(now),
        canonical_event_filter(),
    ]
    if categories:
        conds.append(EventClassification.categories.overlap(categories))
    if vibes:
        conds.append(EventClassification.vibes.overlap(vibes))
    if free:
        conds.append(free_filter())
    if q:
        conds.append(keyword_filter(q))
    date_cond = event_date_range_filter(date_from, date_to)
    if date_cond is not None:
        conds.append(date_cond)
    return conds
