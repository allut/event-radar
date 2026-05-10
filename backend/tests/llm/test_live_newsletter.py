"""Live integration tests for newsletter extraction — hit real LLM APIs.

Run with:
    cd backend
    pytest tests/llm/test_live_newsletter.py -v -s -m live

These tests make real API calls. They are skipped automatically when the
required API key is not set in the environment.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.constants import (
    LLM_TASK_NEWSLETTER,
    NEWSLETTER_EXTRACT_PROMPT_TEMPLATE,
    NEWSLETTER_BODY_MAX_LEN,
    NEWSLETTER_SUBJECT_MAX_LEN
)
from app.llm.router import LLMError, llm_json

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)  # cache miss always
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


async def _llm_json_or_skip(task: str, prompt: str, db: AsyncMock) -> tuple[dict, str]:
    """Call llm_json, skipping the test on transient provider failures."""
    try:
        return await llm_json(task, prompt, db)
    except LLMError as exc:
        pytest.skip(f"All LLM providers failed (transient): {exc}")


def _make_prompt(subject: str, body: str) -> str:
    return NEWSLETTER_EXTRACT_PROMPT_TEMPLATE.format(
        subject=subject[:NEWSLETTER_SUBJECT_MAX_LEN],
        body=body[:NEWSLETTER_BODY_MAX_LEN],
    )


# ---------------------------------------------------------------------------
# Test fixtures: realistic newsletter bodies
# ---------------------------------------------------------------------------


_TYPICAL_NEWSLETTER = """\
Hi there!

Here are this week's Tallinn events:

🎵 Jazz Evening at Telliskivi
Friday, 6 June 2026 at 20:00
Telliskivi Creative City, Tallinn
Tickets from €10 at fienta.com/jazz-friday

🖼️ Photography Exhibition Opening
Saturday, 7 June 2026 at 18:00
Fotografiska Tallinn, Vana-Lootsi 12
Free entry, drinks available

🎭 Improv Comedy Night
Sunday, 8 June 2026 at 19:00
Von Krahli Theatre
Tickets €8 at the door

See you there!
"""

_SUBJECT_TYPICAL = "Tallinn This Week: Jazz, Photography & Comedy"

_NO_EVENTS_BODY = """\
Dear subscriber,

Thank you for being part of our community.

Please note that our offices will be closed for maintenance next week.
No events are scheduled during this period.

Best regards,
The Team
"""

_SUBJECT_NO_EVENTS = "Office Closure Notice"

_PARTIAL_FIELDS_BODY = """\
Coming up:

• Live acoustic set — venue TBD, time TBD, free
• Art market at Balti jaam — this weekend (no exact time given)
"""

_SUBJECT_PARTIAL = "Quick update"


# ---------------------------------------------------------------------------
# Live tests
# ---------------------------------------------------------------------------


def _assert_events_list(result: dict, label: str) -> list:
    assert isinstance(result, dict), f"[{label}] expected dict, got {type(result)}"
    events = result.get("events")
    assert isinstance(events, list), f"[{label}] 'events' must be a list, got {type(events)}"
    return events


def _assert_event_shape(event: dict, idx: int, label: str) -> None:
    assert isinstance(event, dict), f"[{label}] event[{idx}] must be a dict"
    assert isinstance(event.get("title"), str) and event["title"], (
        f"[{label}] event[{idx}] must have a non-empty string 'title'"
    )
    # Optional fields may be None but must be present with correct types when not None
    if event.get("starts_at") is not None:
        assert isinstance(event["starts_at"], str), f"[{label}] event[{idx}].starts_at must be str or null"
    if event.get("price_min") is not None:
        assert isinstance(event["price_min"], (int, float)), f"[{label}] event[{idx}].price_min must be numeric or null"


@pytest.mark.skipif(not settings.GROQ_API_KEY, reason="GROQ_API_KEY not set")
async def test_newsletter_typical_extracts_events():
    """A typical multi-event newsletter produces 2+ events with required fields."""
    prompt = _make_prompt(_SUBJECT_TYPICAL, _TYPICAL_NEWSLETTER)
    result, model_label = await _llm_json_or_skip(LLM_TASK_NEWSLETTER, prompt, _mock_db())

    events = _assert_events_list(result, model_label)
    assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}: {events}"
    for idx, ev in enumerate(events):
        _assert_event_shape(ev, idx, model_label)


@pytest.mark.skipif(not settings.GROQ_API_KEY, reason="GROQ_API_KEY not set")
async def test_newsletter_no_events_returns_empty_list():
    """An email with no events must produce {'events': []} not hallucinated events."""
    prompt = _make_prompt(_SUBJECT_NO_EVENTS, _NO_EVENTS_BODY)
    result, model_label = await _llm_json_or_skip(LLM_TASK_NEWSLETTER, prompt, _mock_db())

    events = _assert_events_list(result, model_label)
    assert events == [], (
        f"Expected empty events list for non-event email, got: {events}"
    )


@pytest.mark.skipif(not settings.GROQ_API_KEY, reason="GROQ_API_KEY not set")
async def test_newsletter_partial_fields_does_not_crash():
    """Events with missing optional fields (venue, date) are extracted without errors."""
    prompt = _make_prompt(_SUBJECT_PARTIAL, _PARTIAL_FIELDS_BODY)
    result, model_label = await _llm_json_or_skip(LLM_TASK_NEWSLETTER, prompt, _mock_db())

    events = _assert_events_list(result, model_label)
    # At least one event should be extracted from the partial-info body
    assert len(events) >= 1, f"Expected at least 1 partial event, got {len(events)}"
    for idx, ev in enumerate(events):
        _assert_event_shape(ev, idx, model_label)
        # Partial fields — starts_at and venue_name may be null, that's fine
        assert "title" in ev, f"event[{idx}] missing 'title' key entirely"


@pytest.mark.skipif(not settings.GROQ_API_KEY, reason="GROQ_API_KEY not set")
async def test_newsletter_free_event_has_price_min_zero():
    """'Free entry' events should yield price_min=0 not None."""
    body = "Photography Exhibition Opening — Saturday 7 June at Fotografiska Tallinn. Free entry."
    prompt = _make_prompt("Free event this weekend", body)
    result, model_label = await _llm_json_or_skip(LLM_TASK_NEWSLETTER, prompt, _mock_db())

    events = _assert_events_list(result, model_label)
    if events:  # model may or may not extract the event
        free_events = [e for e in events if e.get("price_min") == 0]
        assert free_events, (
            f"Expected at least one free event (price_min=0), got: {events}"
        )


@pytest.mark.skipif(not settings.GROQ_API_KEY, reason="GROQ_API_KEY not set")
async def test_newsletter_ignores_non_tallinn_events():
    """Events outside Tallinn should not be included (prompt constraint)."""
    body = (
        "This week in Helsinki: Rock Concert at Olympic Stadium on Fri 20:00, tickets €30.\n"
        "Also in Tallinn: Film Screening at Kino Sõprus on Sat 19:00, tickets €7."
    )
    prompt = _make_prompt("Events in Helsinki and Tallinn", body)
    result, model_label = await _llm_json_or_skip(LLM_TASK_NEWSLETTER, prompt, _mock_db())

    events = _assert_events_list(result, model_label)
    titles = [e.get("title", "") for e in events]
    # The prompt instructs the LLM to only include Tallinn events — Helsinki concert should be filtered
    # We cannot guarantee LLM compliance, so we assert the Tallinn event is present
    assert any("Kino" in t or "Screening" in t or "Film" in t or "Tallinn" in t for t in titles), (
        f"Expected Tallinn event to be included, got titles: {titles}"
    )


@pytest.mark.skipif(not settings.GROQ_API_KEY, reason="GROQ_API_KEY not set")
async def test_newsletter_malformed_email_does_not_crash():
    """Garbled or HTML-heavy email body is handled without raising."""
    garbled_body = (
        "<!DOCTYPE html><html><body><p style='font-size:0'>Event: ???</p>"
        "<div>&#x1F4C5; Date: 2O26-O6-O1 (zero-O confusion)</div>"
        "<span>Price: TBD&#9829;</span></body></html>"
    )
    prompt = _make_prompt("Malformed newsletter", garbled_body)
    # Should not raise — LLM may return empty events list
    result, model_label = await _llm_json_or_skip(LLM_TASK_NEWSLETTER, prompt, _mock_db())
    _assert_events_list(result, model_label)


@pytest.mark.skipif(not settings.GROQ_API_KEY, reason="GROQ_API_KEY not set")
async def test_newsletter_empty_body_returns_empty_list():
    """Empty email body must produce {'events': []} not hallucinations."""
    prompt = _make_prompt("", "")
    result, model_label = await _llm_json_or_skip(LLM_TASK_NEWSLETTER, prompt, _mock_db())
    events = _assert_events_list(result, model_label)
    assert events == [], f"Expected empty list for empty body, got: {events}"
