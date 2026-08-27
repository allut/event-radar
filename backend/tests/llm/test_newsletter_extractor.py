"""Unit tests for app.llm.newsletter_extractor.

All tests mock llm_json and the DB session — no real LLM calls, no real DB.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.newsletter_extractor import _is_valid_event, extract_events_from_email


# ---------------------------------------------------------------------------
# _is_valid_event — pure function, no mocking needed
# ---------------------------------------------------------------------------


class TestIsValidEvent:
    def test_dict_with_title_is_valid(self):
        assert _is_valid_event({"title": "Jazz Night"}) is True

    def test_dict_with_empty_title_is_invalid(self):
        assert _is_valid_event({"title": ""}) is False

    def test_dict_without_title_is_invalid(self):
        assert _is_valid_event({"venue_name": "Telliskivi"}) is False

    def test_non_dict_string_is_invalid(self):
        assert _is_valid_event("not a dict") is False

    def test_non_dict_none_is_invalid(self):
        assert _is_valid_event(None) is False

    def test_non_dict_list_is_invalid(self):
        assert _is_valid_event([{"title": "Jazz"}]) is False

    def test_dict_with_none_title_is_invalid(self):
        assert _is_valid_event({"title": None}) is False

    def test_dict_with_extra_fields_and_title_is_valid(self):
        assert _is_valid_event({
            "title": "Concert",
            "starts_at": None,
            "venue_name": None,
            "price_min": 0,
        }) is True


# ---------------------------------------------------------------------------
# extract_events_from_email — async, mocked llm_json + DB
# ---------------------------------------------------------------------------


@pytest.fixture()
def newsletter_db(mock_db):
    """Newsletter-specific DB mock: scalar returns a source, get returns an email_obj."""
    source = MagicMock()
    source.id = 99

    email_obj = MagicMock()
    email_obj.processed_at = None

    mock_db.scalar = AsyncMock(return_value=source)
    mock_db.get = AsyncMock(return_value=email_obj)
    return mock_db


_VALID_EVENTS_RESPONSE = {
    "events": [
        {
            "title": "Jazz Night at Telliskivi",
            "starts_at": "2026-06-01T20:00:00+03:00",
            "venue_name": "Telliskivi Creative City",
            "url": "https://fienta.com/jazz-night",
            "description": "A great jazz evening.",
            "price_min": 10,
        },
        {
            "title": "Photography Workshop",
            "starts_at": None,
            "venue_name": None,
            "url": None,
            "description": None,
            "price_min": None,
        },
    ]
}


@pytest.mark.asyncio
async def test_extract_returns_correct_count(newsletter_db):
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=(_VALID_EVENTS_RESPONSE, "groq/llama-3.3-70b-versatile"))):
        count = await extract_events_from_email(
            newsletter_db, email_id=1, subject="Weekend events", text_body="Some email body"
        )
    assert count == 2


@pytest.mark.asyncio
async def test_extract_adds_raw_events_to_db(newsletter_db):
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=(_VALID_EVENTS_RESPONSE, "groq/llama-3.3-70b-versatile"))):
        await extract_events_from_email(
            newsletter_db, email_id=5, subject="Events", text_body="body"
        )
    assert newsletter_db.add.call_count == 2


@pytest.mark.asyncio
async def test_extract_sets_processed_at(newsletter_db):
    email_obj = newsletter_db.get.return_value
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=(_VALID_EVENTS_RESPONSE, "groq/llama-3.3-70b-versatile"))):
        await extract_events_from_email(
            newsletter_db, email_id=1, subject="s", text_body="b"
        )
    assert email_obj.processed_at is not None
    assert email_obj.processed_at.tzinfo is not None


@pytest.mark.asyncio
async def test_extract_empty_events_list_returns_zero(newsletter_db):
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=({"events": []}, "groq/llama-3.3-70b-versatile"))):
        count = await extract_events_from_email(
            newsletter_db, email_id=2, subject="s", text_body="b"
        )
    assert count == 0
    newsletter_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_extract_missing_events_key_returns_zero(newsletter_db):
    """LLM returns a dict without the 'events' key — treat as no events."""
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=({}, "groq/llama-3.3-70b-versatile"))):
        count = await extract_events_from_email(
            newsletter_db, email_id=3, subject="s", text_body="b"
        )
    assert count == 0


@pytest.mark.asyncio
async def test_extract_non_list_events_returns_zero(newsletter_db):
    """LLM returns 'events' as a string instead of a list."""
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=({"events": "oops"}, "groq/llama-3.3-70b-versatile"))):
        count = await extract_events_from_email(
            newsletter_db, email_id=4, subject="s", text_body="b"
        )
    assert count == 0


@pytest.mark.asyncio
async def test_extract_filters_out_items_without_title(newsletter_db):
    """Items missing 'title' or with null title are skipped."""
    events = {
        "events": [
            {"title": "Valid Event"},
            {"venue_name": "No title here"},   # no title key
            {"title": None},                   # null title
            {"title": ""},                     # empty title
            {"title": "Another Valid"},
        ]
    }
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=(events, "groq/llama-3.3-70b-versatile"))):
        count = await extract_events_from_email(
            newsletter_db, email_id=6, subject="s", text_body="b"
        )
    assert count == 2


@pytest.mark.asyncio
async def test_extract_on_llm_error_returns_zero(newsletter_db):
    """LLM failure (llm_json_or_none → None) — returns 0 and still marks email processed."""
    email_obj = newsletter_db.get.return_value
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=None)):
        count = await extract_events_from_email(
            newsletter_db, email_id=7, subject="s", text_body="b"
        )
    assert count == 0
    assert email_obj.processed_at is not None


@pytest.mark.asyncio
async def test_extract_on_llm_error_does_not_add_events(newsletter_db):
    """On LLM failure, no RawEvent rows are added."""
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=None)):
        await extract_events_from_email(newsletter_db, email_id=8, subject="s", text_body="b")
    newsletter_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_extract_payload_includes_email_id(newsletter_db):
    """Each RawEvent payload must carry the inbound_email_id for traceability."""
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=(_VALID_EVENTS_RESPONSE, "groq/llama-3.3-70b-versatile"))):
        await extract_events_from_email(
            newsletter_db, email_id=42, subject="s", text_body="b"
        )
    added_events = [call.args[0] for call in newsletter_db.add.call_args_list]
    for ev in added_events:
        assert ev.payload["inbound_email_id"] == 42


@pytest.mark.asyncio
async def test_extract_external_id_format(newsletter_db):
    """external_id must follow 'email-{email_id}-{idx}' pattern."""
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=(_VALID_EVENTS_RESPONSE, "groq/llama-3.3-70b-versatile"))):
        await extract_events_from_email(
            newsletter_db, email_id=10, subject="s", text_body="b"
        )
    added_events = [call.args[0] for call in newsletter_db.add.call_args_list]
    assert added_events[0].external_id == "email-10-0"
    assert added_events[1].external_id == "email-10-1"


@pytest.mark.asyncio
async def test_extract_subject_and_body_truncated_to_constants(newsletter_db):
    """Oversized subject/body are truncated before reaching LLM."""
    from app.constants import NEWSLETTER_BODY_MAX_LEN, NEWSLETTER_SUBJECT_MAX_LEN

    captured_prompts: list[str] = []

    async def capturing_llm_json(task, prompt, db, **kwargs):
        captured_prompts.append(prompt)
        return ({"events": []}, "groq/llama-3.3-70b-versatile")

    long_subject = "S" * (NEWSLETTER_SUBJECT_MAX_LEN + 100)
    long_body = "B" * (NEWSLETTER_BODY_MAX_LEN + 100)

    with patch("app.llm.newsletter_extractor.llm_json_or_none", capturing_llm_json):
        await extract_events_from_email(
            newsletter_db, email_id=11, subject=long_subject, text_body=long_body
        )

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "S" * (NEWSLETTER_SUBJECT_MAX_LEN + 1) not in prompt
    assert "B" * (NEWSLETTER_BODY_MAX_LEN + 1) not in prompt


@pytest.mark.asyncio
async def test_extract_email_not_found_does_not_crash(newsletter_db):
    """If db.get returns None for the email, _mark_processed must not raise."""
    newsletter_db.get.return_value = None  # email row missing
    with patch("app.llm.newsletter_extractor.llm_json_or_none", AsyncMock(return_value=({"events": []}, "groq/llama-3.3-70b-versatile"))):
        count = await extract_events_from_email(
            newsletter_db, email_id=99, subject="s", text_body="b"
        )
    assert count == 0
