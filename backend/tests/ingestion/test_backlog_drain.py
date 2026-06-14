"""Tests for app.ingestion.jobs._drain_backlog and the drained job wrappers."""

from unittest.mock import AsyncMock

import pytest

from app.constants import LLM_BACKLOG_MAX_DRAIN_PASSES, LLM_CLASSIFY_BATCH_SIZE
from app.ingestion.jobs import (
    _drain_backlog,
    classify_pending_drained,
    dedup_pass_drained,
)


@pytest.mark.asyncio
async def test_clears_after_a_few_passes(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("app.ingestion.jobs.asyncio.sleep", sleep)

    summaries = [{"deferred_pairs": 2}, {"deferred_pairs": 1}, {"deferred_pairs": 0}]
    run_once = AsyncMock(side_effect=summaries)

    result = await _drain_backlog(run_once, lambda s: s["deferred_pairs"] > 0, "test")

    assert result == {"deferred_pairs": 0}
    assert run_once.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_cap_reached_when_backlog_never_clears(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("app.ingestion.jobs.asyncio.sleep", sleep)

    run_once = AsyncMock(return_value={"deferred_pairs": 5})

    result = await _drain_backlog(run_once, lambda s: s["deferred_pairs"] > 0, "test")

    assert result == {"deferred_pairs": 5}
    assert run_once.await_count == LLM_BACKLOG_MAX_DRAIN_PASSES
    assert sleep.await_count == LLM_BACKLOG_MAX_DRAIN_PASSES - 1


@pytest.mark.asyncio
async def test_no_backlog_on_first_pass(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("app.ingestion.jobs.asyncio.sleep", sleep)

    run_once = AsyncMock(return_value={"deferred_pairs": 0})

    result = await _drain_backlog(run_once, lambda s: s["deferred_pairs"] > 0, "test")

    assert result == {"deferred_pairs": 0}
    assert run_once.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.parametrize(
    "summary,expected",
    [
        ({"deferred_pairs": 0}, False),
        ({"deferred_pairs": 5}, True),
    ],
)
@pytest.mark.asyncio
async def test_dedup_pass_drained_predicate(monkeypatch, summary, expected):
    sleep = AsyncMock()
    monkeypatch.setattr("app.ingestion.jobs.asyncio.sleep", sleep)
    monkeypatch.setattr(
        "app.ingestion.jobs.dedup_pass", AsyncMock(return_value=summary)
    )

    result = await dedup_pass_drained()

    assert result == summary
    if expected:
        sleep.assert_awaited()
    else:
        sleep.assert_not_awaited()


@pytest.mark.parametrize(
    "summary,expected",
    [
        # full batch + progress -> backlog remains
        ({"attempted": LLM_CLASSIFY_BATCH_SIZE, "succeeded": 1}, True),
        # full batch but every call failed -> outage guard, no backlog
        ({"attempted": LLM_CLASSIFY_BATCH_SIZE, "succeeded": 0}, False),
        # partial batch -> no backlog
        ({"attempted": LLM_CLASSIFY_BATCH_SIZE - 1, "succeeded": 1}, False),
    ],
)
@pytest.mark.asyncio
async def test_classify_pending_drained_predicate(monkeypatch, summary, expected):
    sleep = AsyncMock()
    monkeypatch.setattr("app.ingestion.jobs.asyncio.sleep", sleep)
    monkeypatch.setattr(
        "app.ingestion.jobs.classify_pending_job", AsyncMock(return_value=summary)
    )

    result = await classify_pending_drained()

    assert result == summary
    if expected:
        sleep.assert_awaited()
    else:
        sleep.assert_not_awaited()
