"""Unit tests for the publish gate (app/publish.py)."""

import pytest

from app.constants import (
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    PUBLISH_MIN_QUALITY_SCORE,
)
from app.publish import publish_pending


@pytest.mark.asyncio
async def test_publish_pending_returns_rowcount_from_update(mock_db):
    mock_db.execute.return_value.rowcount = 3

    result = await publish_pending(mock_db)

    assert result == {"published": 3}
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_pending_zero_rowcount_when_nothing_qualifies(mock_db):
    mock_db.execute.return_value.rowcount = 0

    result = await publish_pending(mock_db)

    assert result == {"published": 0}


@pytest.mark.asyncio
async def test_publish_pending_statement_encodes_gate_criteria(mock_db):
    """The single bulk UPDATE must encode all four gate criteria from the plan."""
    mock_db.execute.return_value.rowcount = 0

    await publish_pending(mock_db)

    stmt = mock_db.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # Reads classified, writes published — idempotent re-run is a no-op.
    assert f"events.status = '{EVENT_STATUS_CLASSIFIED}'" in compiled
    assert f"SET status='{EVENT_STATUS_PUBLISHED}'" in compiled or (
        f"status='{EVENT_STATUS_PUBLISHED}'" in compiled
    )
    # is_explicit=false gate.
    assert "is_explicit" in compiled
    # starts_at must be in the future.
    assert "starts_at >=" in compiled
    # title_orig presence check.
    assert "title_orig" in compiled
    # quality_score gate joined via event_classifications subquery.
    assert "event_classifications" in compiled
    assert "quality_score" in compiled
    assert str(PUBLISH_MIN_QUALITY_SCORE) in compiled
