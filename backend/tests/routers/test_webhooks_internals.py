"""Unit tests for webhooks helper branches not exercised via the HTTP endpoint:
timestamp parse failure, Svix secret validation, and _run_extraction."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers import webhooks
from app.routers.webhooks import (
    _run_extraction,
    _timestamp_within_tolerance,
    _verify_svix_signature,
)


def test_timestamp_within_tolerance_non_numeric_is_false():
    assert _timestamp_within_tolerance("not-a-number") is False


def test_verify_svix_signature_rejects_bad_prefix():
    assert (
        _verify_svix_signature("nope_key", "id", "123", b"body", "v1,sig") is False
    )


def test_verify_svix_signature_rejects_undecodable_key():
    # "whsec_" prefix present but the remainder is not valid base64.
    assert (
        _verify_svix_signature("whsec_!!!not-base64!!!", "id", "123", b"body", "v1,x")
        is False
    )


def _session_factory(db):
    @asynccontextmanager
    async def _ctx():
        yield db

    return MagicMock(side_effect=lambda: _ctx())


@pytest.mark.asyncio
async def test_run_extraction_commits_on_success(mock_db, monkeypatch):
    monkeypatch.setattr(webhooks, "AsyncSessionLocal", _session_factory(mock_db))
    monkeypatch.setattr(
        webhooks, "extract_events_from_email", AsyncMock(return_value=2)
    )

    await _run_extraction(email_id=7, subject="Hi", text_body="Body")

    mock_db.commit.assert_awaited_once()
    mock_db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_extraction_rolls_back_on_error(mock_db, monkeypatch):
    monkeypatch.setattr(webhooks, "AsyncSessionLocal", _session_factory(mock_db))
    monkeypatch.setattr(
        webhooks,
        "extract_events_from_email",
        AsyncMock(side_effect=RuntimeError("llm down")),
    )

    await _run_extraction(email_id=7, subject="Hi", text_body="Body")

    mock_db.rollback.assert_awaited_once()
    mock_db.commit.assert_not_awaited()
