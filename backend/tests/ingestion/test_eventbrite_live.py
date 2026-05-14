"""Live Eventbrite API integration tests — hits real API, skip if key absent.

Run with:
    cd backend
    pytest tests/ingestion/test_eventbrite_live.py -v -s -m live

Findings from 2026-05-14:
  - API key is valid: GET /v3/users/me/ returns 200.
  - GET /v3/events/search/ returns 404 — this endpoint was deprecated for
    non-partner accounts. The adapter now handles this gracefully (returns []).
  - Until Eventbrite restores partner access or we switch to another source,
    the adapter produces zero events. This test suite documents that behavior.
"""
import http

import httpx
import pytest

from app.config import settings
from app.ingestion.sources.eventbrite import EventbriteAdapter

pytestmark = pytest.mark.live

_EVENTBRITE_USERS_ME = "https://www.eventbriteapi.com/v3/users/me/"
_EVENTBRITE_SEARCH = "https://www.eventbriteapi.com/v3/events/search/"


def _adapter() -> EventbriteAdapter:
    from unittest.mock import MagicMock
    source = MagicMock()
    source.slug = "eventbrite"
    source.config = {}  # forces fallback to settings.EVENTBRITE_API_KEY
    return EventbriteAdapter(source)


@pytest.mark.skipif(not settings.EVENTBRITE_API_KEY, reason="EVENTBRITE_API_KEY not set")
async def test_api_key_is_valid():
    """API key authenticates successfully against /v3/users/me/."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            _EVENTBRITE_USERS_ME,
            headers={"Authorization": f"Bearer {settings.EVENTBRITE_API_KEY}"},
        )
    assert resp.status_code == http.HTTPStatus.OK, (
        f"Expected 200 from /v3/users/me/, got {resp.status_code}: {resp.text[:200]}"
    )
    data = resp.json()
    assert "id" in data, "Response missing 'id' field"
    emails = data.get("emails", [])
    assert any("@" in e.get("email", "") for e in emails), "Response missing valid email in 'emails' list"


@pytest.mark.skipif(not settings.EVENTBRITE_API_KEY, reason="EVENTBRITE_API_KEY not set")
async def test_search_endpoint_status():
    """Documents the current status of the /v3/events/search/ endpoint.

    As of 2026-05-14 this endpoint returns 404 for non-partner API keys.
    The test asserts we get either 200 (if endpoint access is restored) or
    404 (confirming the known deprecation). Any other status is a failure.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            _EVENTBRITE_SEARCH,
            params={
                "location.address": "Tallinn, Estonia",
                "location.within": "10km",
                "page_size": 5,
                "page": 1,
                "sort_by": "date",
                "expand": "venue,ticket_classes",
            },
            headers={"Authorization": f"Bearer {settings.EVENTBRITE_API_KEY}"},
        )

    assert resp.status_code in {
        http.HTTPStatus.OK,
        http.HTTPStatus.NOT_FOUND,
    }, f"Unexpected status {resp.status_code}: {resp.text[:200]}"

    if resp.status_code == http.HTTPStatus.NOT_FOUND:
        pytest.xfail(
            "Eventbrite /v3/events/search/ returns 404 — endpoint deprecated for non-partner keys. "
            "Adapter returns all_events gracefully. Restore partner access to fix."
        )

    # If we get 200, validate the response shape
    data = resp.json()
    assert "events" in data, "Expected 'events' key in search response"
    assert "pagination" in data, "Expected 'pagination' key in search response"


@pytest.mark.skipif(not settings.EVENTBRITE_API_KEY, reason="EVENTBRITE_API_KEY not set")
async def test_fetch_raw_returns_empty_on_404_gracefully():
    """EventbriteAdapter.fetch_raw() returns [] without crashing when endpoint is 404."""
    adapter = _adapter()
    result = await adapter.fetch_raw()
    # Either [] (404 gracefully handled) or a list of events (if endpoint works)
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    # If we get events, validate each has required fields
    for event in result:
        assert "id" in event, f"Event missing 'id': {list(event.keys())}"
        assert "name" in event, f"Event missing 'name': {list(event.keys())}"
        assert "start" in event, f"Event missing 'start': {list(event.keys())}"


@pytest.mark.skipif(not settings.EVENTBRITE_API_KEY, reason="EVENTBRITE_API_KEY not set")
async def test_normalize_on_live_data_if_available():
    """If fetch_raw returns events, normalize() produces valid NormalizedEvent objects."""
    adapter = _adapter()
    raw_events = await adapter.fetch_raw()

    if not raw_events:
        pytest.skip("fetch_raw() returned no events (endpoint 404 or no Tallinn events found)")

    normalized_count = 0
    skipped_count = 0
    for raw in raw_events[:10]:  # sample first 10
        result = adapter.normalize(raw)
        if result is None:
            skipped_count += 1
            continue
        normalized_count += 1
        assert result.external_id, "external_id must be non-empty"
        assert result.title, "title must be non-empty"
        assert result.starts_at is not None, "starts_at must be set"
        assert result.starts_at.tzinfo is not None, "starts_at must be tz-aware"

    assert normalized_count > 0, (
        f"All {len(raw_events[:10])} events failed normalization — check adapter logic"
    )
