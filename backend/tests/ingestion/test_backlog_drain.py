"""Tests for app.ingestion.jobs._drain_backlog and the drained job wrappers."""

from unittest.mock import AsyncMock

import pytest

from app.constants.llm import LLM_BACKLOG_MAX_DRAIN_PASSES, LLM_CLASSIFY_BATCH_SIZE
from app.ingestion.jobs import (
    _drain_backlog,
    classify_pending_drain_now,
    classify_pending_drained,
    dedup_pass_drain_now,
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


@pytest.mark.asyncio
async def test_retry_seconds_zero_skips_sleep_across_passes(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("app.ingestion.jobs.asyncio.sleep", sleep)

    summaries = [{"deferred_pairs": 2}, {"deferred_pairs": 1}, {"deferred_pairs": 0}]
    run_once = AsyncMock(side_effect=summaries)

    result = await _drain_backlog(
        run_once, lambda s: s["deferred_pairs"] > 0, "test", retry_seconds=0
    )

    assert result == {"deferred_pairs": 0}
    assert run_once.await_count == 3
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_aggregate_sums_counts_across_passes(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("app.ingestion.jobs.asyncio.sleep", sleep)

    summaries = [
        {"attempted": 30, "succeeded": 28, "failed": 2},
        {"attempted": 30, "succeeded": 30, "failed": 0},
        {"attempted": 10, "succeeded": 10, "failed": 0},
    ]
    run_once = AsyncMock(side_effect=summaries)

    result = await _drain_backlog(
        run_once,
        lambda s: s["attempted"] >= 30 and s["succeeded"] > 0,
        "test",
        retry_seconds=0,
        aggregate=True,
    )

    assert result == {"attempted": 70, "succeeded": 68, "failed": 2, "passes": 3}


@pytest.mark.asyncio
async def test_aggregate_keeps_last_value_for_snapshot_fields(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("app.ingestion.jobs.asyncio.sleep", sleep)

    summaries = [
        {"total": 100, "candidate_pairs": 20, "grouped": 100, "groups": 60, "updated": 5},
        {"total": 98, "candidate_pairs": 15, "grouped": 98, "groups": 58, "updated": 3},
        {"total": 98, "candidate_pairs": 0, "grouped": 98, "groups": 58, "updated": 0},
    ]
    run_once = AsyncMock(side_effect=summaries)

    result = await _drain_backlog(
        run_once,
        lambda s: s["candidate_pairs"] > 0,
        "test",
        retry_seconds=0,
        aggregate=True,
    )

    # snapshot fields take the last pass's value
    assert result["total"] == 98
    assert result["candidate_pairs"] == 0
    assert result["grouped"] == 98
    assert result["groups"] == 58
    # work-done fields are summed
    assert result["updated"] == 8
    assert result["passes"] == 3


@pytest.mark.asyncio
async def test_dedup_pass_drain_now_no_sleep_aggregated_capped(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("app.ingestion.jobs.asyncio.sleep", sleep)
    monkeypatch.setattr(
        "app.ingestion.jobs.dedup_pass",
        AsyncMock(return_value={"total": 100, "deferred_pairs": 5}),
    )

    result = await dedup_pass_drain_now()

    sleep.assert_not_awaited()
    assert result["passes"] == LLM_BACKLOG_MAX_DRAIN_PASSES
    assert result["deferred_pairs"] == 5 * LLM_BACKLOG_MAX_DRAIN_PASSES
    # snapshot fields (recomputed each pass over the whole corpus) report the
    # last pass's value, not a sum across passes
    assert result["total"] == 100


@pytest.mark.asyncio
async def test_classify_pending_drain_now_no_sleep_aggregated(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("app.ingestion.jobs.asyncio.sleep", sleep)

    summaries = [
        {"attempted": LLM_CLASSIFY_BATCH_SIZE, "succeeded": 30},
        {"attempted": LLM_CLASSIFY_BATCH_SIZE, "succeeded": 30},
        {"attempted": 5, "succeeded": 5},
    ]
    monkeypatch.setattr(
        "app.ingestion.jobs.classify_pending_job", AsyncMock(side_effect=summaries)
    )

    result = await classify_pending_drain_now()

    sleep.assert_not_awaited()
    assert result == {
        "attempted": LLM_CLASSIFY_BATCH_SIZE * 2 + 5,
        "succeeded": 65,
        "passes": 3,
    }
