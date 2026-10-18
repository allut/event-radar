"""The classifier's `promotion_restriction` field (#612): set the way `explicit`
is, never feeding the publish gate or organic listing."""

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.promotions import PROMOTION_RESTRICTIONS
from app.llm.classifier import classify_event
from app.llm.prompts import (
    LLM_CLASSIFY_PROMPT_TEMPLATE,
    LLM_PROMOTION_RESTRICTION_PROMPT_TEMPLATE,
)

_RAW = {"categories": [], "vibes": [], "why_go": [], "quality": None, "language": "en"}


async def _classify(event, mock_db, **extra):
    raw = {**_RAW, **extra}
    with patch(
        "app.llm.classifier.llm_json_or_none",
        AsyncMock(return_value=(raw, "groq/openai/gpt-oss-120b")),
    ):
        return await classify_event(
            event, mock_db, existing_classification=event.classification, prefetched=True
        )


@pytest.mark.asyncio
async def test_classification_sets_restriction_without_touching_gate_flags(mock_db, make_event):
    event = make_event()
    assert await _classify(event, mock_db, promotion_restriction="gambling") is True
    assert event.promotion_restriction == "gambling"
    assert (event.is_explicit, event.is_non_event, event.is_out_of_area) == (False, False, False)


@pytest.mark.asyncio
async def test_reclassify_can_clear_a_false_positive(mock_db, make_event):
    event = make_event()
    event.promotion_restriction = "alcohol"
    await _classify(event, mock_db, promotion_restriction="none")
    assert event.promotion_restriction == "none"


@pytest.mark.asyncio
async def test_missing_or_bad_answer_keeps_previous_value(mock_db, make_event):
    event = make_event()
    event.promotion_restriction = "tobacco"
    await _classify(event, mock_db, promotion_restriction="banana")
    assert event.promotion_restriction == "tobacco"
    await _classify(event, mock_db)
    assert event.promotion_restriction == "tobacco"


def test_prompts_name_every_restriction():
    for template in (LLM_CLASSIFY_PROMPT_TEMPLATE, LLM_PROMOTION_RESTRICTION_PROMPT_TEMPLATE):
        for value in PROMOTION_RESTRICTIONS:
            assert f'"{value}"' in template
