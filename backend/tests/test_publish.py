"""Unit tests for the publish gate (app/publish.py)."""

import re
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.constants import (
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    PUBLISH_DIAGNOSTICS_WINDOW_DAYS,
    PUBLISH_MIN_QUALITY_SCORE,
    TALLINN_REGION_BBOX,
    TALLINN_TZ,
)
from app.publish import publish_pending

REJECT_ROW_ZERO = SimpleNamespace(
    unpublished=0,
    fail_quality=0,
    fail_explicit=0,
    fail_non_event=0,
    fail_out_of_area=0,
    fail_ended=0,
    fail_no_title=0,
    fail_coords_bbox=0,
    fail_unverified_organizer=0,
)


def _configure_execute(mock_db, rowcount: int, reject_row=REJECT_ROW_ZERO):
    """Gate now issues two execute() calls: the bulk UPDATE, then a diagnostic
    SELECT over the still-classified rows. side_effect gives each call its
    own mocked result."""
    update_result = MagicMock()
    update_result.rowcount = rowcount
    select_result = MagicMock()
    select_result.one.return_value = reject_row
    mock_db.execute.side_effect = [update_result, select_result]


@pytest.mark.asyncio
async def test_publish_pending_returns_rowcount_from_update(mock_db):
    _configure_execute(mock_db, rowcount=3)

    result = await publish_pending(mock_db)

    assert result["published"] == 3
    assert mock_db.execute.call_count == 2


@pytest.mark.asyncio
async def test_publish_pending_zero_rowcount_when_nothing_qualifies(mock_db):
    _configure_execute(mock_db, rowcount=0)

    result = await publish_pending(mock_db)

    assert result["published"] == 0


@pytest.mark.asyncio
async def test_reject_breakdown_statement_bounds_to_recent_window(mock_db):
    """F3: the diagnostic reject-breakdown SELECT must stay bounded to the
    last PUBLISH_DIAGNOSTICS_WINDOW_DAYS (by starts_at), not scan every
    all-time classified reject."""
    _configure_execute(mock_db, rowcount=0)

    await publish_pending(mock_db)

    reject_stmt = mock_db.execute.call_args_list[1][0][0]
    compiled = str(reject_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert f"events.status = '{EVENT_STATUS_CLASSIFIED}'" in compiled
    assert "events.starts_at >=" in compiled

    # The cutoff is computed in Python (now - PUBLISH_DIAGNOSTICS_WINDOW_DAYS),
    # not baked into the SQL as a literal day-count — assert the bound itself
    # is correct rather than looking for a magic number/keyword in the SQL text.
    match = re.search(r"events\.starts_at >= '([^']+)'", compiled)
    assert match is not None
    cutoff = datetime.fromisoformat(match.group(1))
    expected = datetime.now(TALLINN_TZ) - timedelta(days=PUBLISH_DIAGNOSTICS_WINDOW_DAYS)
    assert abs((cutoff - expected).total_seconds()) < 5


@pytest.mark.asyncio
async def test_publish_pending_returns_reject_breakdown(mock_db):
    reject_row = SimpleNamespace(
        unpublished=5,
        fail_quality=2,
        fail_explicit=0,
        fail_non_event=3,
        fail_out_of_area=1,
        fail_ended=4,
        fail_no_title=0,
        fail_coords_bbox=0,
        fail_unverified_organizer=1,
    )
    _configure_execute(mock_db, rowcount=3, reject_row=reject_row)

    result = await publish_pending(mock_db)

    assert result == {
        "published": 3,
        "unpublished": 5,
        "fail_quality": 2,
        "fail_explicit": 0,
        "fail_non_event": 3,
        "fail_out_of_area": 1,
        "fail_ended": 4,
        "fail_no_title": 0,
        "fail_coords_bbox": 0,
        "fail_unverified_organizer": 1,
    }


@pytest.mark.asyncio
async def test_publish_pending_statement_encodes_gate_criteria(mock_db):
    """The single bulk UPDATE must encode all gate criteria from the plan."""
    _configure_execute(mock_db, rowcount=0)

    await publish_pending(mock_db)

    stmt = mock_db.execute.call_args_list[0][0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # Reads classified, writes published — idempotent re-run is a no-op.
    assert f"events.status = '{EVENT_STATUS_CLASSIFIED}'" in compiled
    assert f"SET status='{EVENT_STATUS_PUBLISHED}'" in compiled or (
        f"status='{EVENT_STATUS_PUBLISHED}'" in compiled
    )
    # is_explicit=false gate.
    assert "is_explicit" in compiled
    # is_non_event=false gate (gift cards / merch / webinars).
    assert "is_non_event" in compiled
    # is_out_of_area=false gate (LLM location signal).
    assert "is_out_of_area" in compiled
    # event_not_ended_filter: coalesce(ends_at, starts_at) >= now (sargable
    # against ix_events_live_until).
    assert "coalesce(events.ends_at, events.starts_at) >=" in compiled
    # title_orig presence check.
    assert "title_orig" in compiled
    # quality_score gate joined via event_classifications subquery.
    assert "event_classifications" in compiled
    assert "quality_score" in compiled
    assert str(PUBLISH_MIN_QUALITY_SCORE) in compiled
    # Tallinn bbox guard — lat/lng columns must appear in the compiled SQL.
    lat_min, lat_max, lng_min, lng_max = TALLINN_REGION_BBOX
    assert "lat" in compiled
    assert "lng" in compiled
    assert str(lat_min) in compiled
    assert str(lng_max) in compiled
    # Unverified-organizer gate: NULL-safe OR around a NOT IN over unverified
    # organizer ids (M2 — see CLAUDE.md Organizer Event Submission).
    assert "submitted_by_organizer_id" in compiled
    assert "organizers" in compiled
    assert "verified" in compiled


@pytest.mark.asyncio
async def test_publish_pending_reject_breakdown_includes_unverified_organizer(mock_db):
    """The diagnostic reject-count SELECT must report the new
    fail_unverified_organizer reason like every other gate reason."""
    _configure_execute(mock_db, rowcount=0)

    result = await publish_pending(mock_db)

    assert "fail_unverified_organizer" in result
    select_stmt = mock_db.execute.call_args_list[1][0][0]
    compiled = str(select_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "fail_unverified_organizer" in compiled
