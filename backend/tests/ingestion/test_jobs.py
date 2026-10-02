"""Tests for app.ingestion.jobs: ingest_source, ingest_all_enabled, _run_db_job,
the thin scheduler-job wrappers, and the pure backlog/aggregate helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.constants import LLM_CLASSIFY_BATCH_SIZE
from app.ingestion import jobs
from app import db as app_db
from tests.conftest import session_factory as _session_factory


def _make_source(slug="fienta", enabled=True, kind="api"):
    src = MagicMock()
    src.slug = slug
    src.enabled = enabled
    src.kind = kind
    return src


# ---------------------------------------------------------------------------
# ingest_source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_source_unknown_slug_raises(mock_db, monkeypatch):
    mock_db.scalar.return_value = None
    monkeypatch.setattr(jobs, "AsyncSessionLocal", _session_factory(mock_db))

    with pytest.raises(ValueError, match="Unknown source slug"):
        await jobs.ingest_source("nope")


@pytest.mark.asyncio
async def test_ingest_source_disabled_skips(mock_db, monkeypatch):
    mock_db.scalar.return_value = _make_source(enabled=False)
    monkeypatch.setattr(jobs, "AsyncSessionLocal", _session_factory(mock_db))

    result = await jobs.ingest_source("fienta")

    assert result == {"slug": "fienta", "skipped": True, "reason": "disabled"}


@pytest.mark.asyncio
async def test_ingest_source_no_adapter_raises(mock_db, monkeypatch):
    mock_db.scalar.return_value = _make_source(slug="fienta")
    monkeypatch.setattr(jobs, "AsyncSessionLocal", _session_factory(mock_db))
    monkeypatch.setattr(jobs, "ADAPTER_REGISTRY", {})

    with pytest.raises(ValueError, match="No adapter registered"):
        await jobs.ingest_source("fienta")


@pytest.mark.asyncio
async def test_ingest_source_success(mock_db, monkeypatch):
    source = _make_source(slug="fienta")
    mock_db.scalar.return_value = source

    run = MagicMock(raw_count=12, new_count=3)
    adapter = MagicMock()
    adapter.run = AsyncMock(return_value=run)
    adapter_cls = MagicMock(return_value=adapter)

    monkeypatch.setattr(jobs, "AsyncSessionLocal", _session_factory(mock_db))
    monkeypatch.setattr(jobs, "ADAPTER_REGISTRY", {"fienta": adapter_cls})

    result = await jobs.ingest_source("fienta")

    assert result == {"slug": "fienta", "raw_count": 12, "new_count": 3}
    adapter_cls.assert_called_once_with(source)
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_source_error_commits_and_reraises(mock_db, monkeypatch):
    """On adapter failure, the run record must persist: commit (not rollback)."""
    mock_db.scalar.return_value = _make_source(slug="fienta")

    adapter = MagicMock()
    adapter.run = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(jobs, "AsyncSessionLocal", _session_factory(mock_db))
    monkeypatch.setattr(jobs, "ADAPTER_REGISTRY", {"fienta": MagicMock(return_value=adapter)})

    with pytest.raises(RuntimeError, match="boom"):
        await jobs.ingest_source("fienta")

    mock_db.commit.assert_awaited_once()
    mock_db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_source_error_commit_fails_falls_back_to_rollback(mock_db, monkeypatch):
    mock_db.scalar.return_value = _make_source(slug="fienta")
    mock_db.commit.side_effect = RuntimeError("commit-failed")

    adapter = MagicMock()
    adapter.run = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(jobs, "AsyncSessionLocal", _session_factory(mock_db))
    monkeypatch.setattr(jobs, "ADAPTER_REGISTRY", {"fienta": MagicMock(return_value=adapter)})

    with pytest.raises(RuntimeError, match="boom"):
        await jobs.ingest_source("fienta")

    mock_db.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# ingest_all_enabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_all_enabled_filters_and_captures(mock_db, monkeypatch):
    known = _make_source(slug="fienta")
    unknown = _make_source(slug="mystery")
    scalars_result = MagicMock()
    scalars_result.all.return_value = [known, unknown]
    mock_db.scalars.return_value = scalars_result

    monkeypatch.setattr(jobs, "AsyncSessionLocal", _session_factory(mock_db))
    monkeypatch.setattr(jobs, "ADAPTER_REGISTRY", {"fienta": MagicMock()})

    async def fake_ingest(slug):
        if slug == "fienta":
            return {"slug": slug, "raw_count": 1, "new_count": 0}
        raise ValueError("should not run for unknown")

    monkeypatch.setattr(jobs, "ingest_source", AsyncMock(side_effect=fake_ingest))

    results = await jobs.ingest_all_enabled()

    # unknown slug is filtered out before ingest_source is called
    assert results == [{"slug": "fienta", "raw_count": 1, "new_count": 0}]


@pytest.mark.asyncio
async def test_ingest_all_enabled_records_per_source_error(mock_db, monkeypatch):
    src = _make_source(slug="fienta")
    scalars_result = MagicMock()
    scalars_result.all.return_value = [src]
    mock_db.scalars.return_value = scalars_result

    monkeypatch.setattr(jobs, "AsyncSessionLocal", _session_factory(mock_db))
    monkeypatch.setattr(jobs, "ADAPTER_REGISTRY", {"fienta": MagicMock()})
    monkeypatch.setattr(
        jobs, "ingest_source", AsyncMock(side_effect=RuntimeError("kaboom"))
    )

    results = await jobs.ingest_all_enabled()

    assert results == [{"slug": "fienta", "error": "kaboom"}]


# ---------------------------------------------------------------------------
# _run_db_job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_db_job_commits_on_success(mock_db, monkeypatch):
    # _run_db_job delegates the actual session handling to the shared
    # run_in_session() (app/db.py), which owns its own
    # AsyncSessionLocal import — patch that one, not jobs'.
    monkeypatch.setattr(app_db, "AsyncSessionLocal", _session_factory(mock_db))
    func = AsyncMock(return_value={"ok": 1})

    result = await jobs._run_db_job("label", func)

    assert result == {"ok": 1}
    func.assert_awaited_once_with(mock_db)
    mock_db.commit.assert_awaited_once()
    mock_db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_db_job_rolls_back_and_reraises(mock_db, monkeypatch):
    monkeypatch.setattr(app_db, "AsyncSessionLocal", _session_factory(mock_db))
    func = AsyncMock(side_effect=RuntimeError("nope"))

    with pytest.raises(RuntimeError, match="nope"):
        await jobs._run_db_job("label", func)

    mock_db.rollback.assert_awaited_once()
    mock_db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# thin scheduler-job wrappers delegate to _run_db_job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "job_name",
    [
        "dedup_pass",
        "classify_pending_job",
        "publish_pending_job",
        "geocode_pending_job",
        "backfill_publisher_ids_job",
        "refetch_event_details_job",
    ],
)
async def test_job_wrappers_delegate_to_run_db_job(monkeypatch, job_name):
    captured = {}

    async def fake_run_db_job(label, func):
        captured["label"] = label
        captured["func"] = func
        return {"done": True}

    monkeypatch.setattr(jobs, "_run_db_job", fake_run_db_job)

    result = await getattr(jobs, job_name)()

    assert result == {"done": True}
    assert captured["label"]
    assert callable(captured["func"])


# ---------------------------------------------------------------------------
# pure predicate / aggregate helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "summary,expected",
    [
        ({"deferred_pairs": 0}, False),
        ({"deferred_pairs": 3}, True),
        ({}, False),
    ],
)
def test_dedup_has_backlog(summary, expected):
    assert jobs._dedup_has_backlog(summary) is expected


@pytest.mark.parametrize(
    "summary,expected",
    [
        ({"attempted": LLM_CLASSIFY_BATCH_SIZE, "succeeded": 1}, True),
        ({"attempted": LLM_CLASSIFY_BATCH_SIZE, "succeeded": 0}, False),
        ({"attempted": LLM_CLASSIFY_BATCH_SIZE - 1, "succeeded": 1}, False),
        ({}, False),
    ],
)
def test_classify_has_backlog(summary, expected):
    assert jobs._classify_has_backlog(summary) is expected


def test_aggregate_summaries_skips_non_numeric_and_bool():
    """bools and non-numeric values are excluded; only int/float aggregate."""
    summaries = [
        {"attempted": 10, "flag": True, "label": "x", "updated": 2},
        {"attempted": 5, "flag": False, "label": "y", "updated": 3},
    ]

    result = jobs._aggregate_summaries(summaries)

    assert result["attempted"] == 15
    assert result["updated"] == 5
    assert result["passes"] == 2
    assert "flag" not in result
    assert "label" not in result
