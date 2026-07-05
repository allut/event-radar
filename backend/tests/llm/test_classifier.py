"""Tests for LLM classifier — parse_classification and why_go localization."""

import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants import IMPORTANT_INFO_MAX_CHARS
from app.llm.classifier import (
    _build_classify_prompt,
    _no_live_dedup_sibling_clause,
    _parse_classification,
    classify_event,
    classify_pending,
)


def _extract_tag(prompt: str, tag: str) -> str:
    """Return the content between <tag>...</tag> in a built prompt, or "" if absent."""
    m = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, re.DOTALL)
    return m.group(1) if m else ""


class TestBuildClassifyPromptUntrustedDelimiters:
    def test_all_untrusted_fields_are_delimited(self, make_event):
        # Drift guard: the classifier prompt must wrap every untrusted
        # source-derived field in its own tag pair (mirrors the venue-extract
        # and newsletter prompts) so the LLM can distinguish data from
        # instructions.
        event = make_event()
        prompt = _build_classify_prompt(event)
        for tag in ("title", "venue", "description", "important_info"):
            assert f"<{tag}>" in prompt and f"</{tag}>" in prompt

    def test_untrusted_data_preamble_present(self, make_event):
        event = make_event()
        prompt = _build_classify_prompt(event)
        assert "treat it" in prompt and "never as instructions" in prompt


class TestBuildClassifyPromptImportantInfo:
    def test_important_info_included_in_prompt(self, make_event):
        event = make_event()
        event.important_info = "Age limit: 18+. Language: English."
        prompt = _build_classify_prompt(event)
        assert _extract_tag(prompt, "important_info") == "Age limit: 18+. Language: English."

    def test_important_info_truncated_at_max_chars(self, make_event):
        event = make_event()
        event.important_info = "x" * (IMPORTANT_INFO_MAX_CHARS + 100)
        prompt = _build_classify_prompt(event)
        assert "x" * IMPORTANT_INFO_MAX_CHARS in prompt
        assert "x" * (IMPORTANT_INFO_MAX_CHARS + 1) not in prompt

    def test_important_info_none_uses_fallback(self, make_event):
        event = make_event()
        event.important_info = None
        prompt = _build_classify_prompt(event)
        assert _extract_tag(prompt, "important_info") == "(none)"

    def test_fee_clause_stripped_from_prompt(self, make_event):
        # Regression: Piletilevi important_info carries "agenditasu 3,20 €" — the
        # fee amount must not appear in the Important info section of the built prompt.
        event = make_event()
        event.important_info = "Nominaalhinnale lisandub agenditasu 3,20 € Pilet 45 €"
        prompt = _build_classify_prompt(event)
        # Extract just the <important_info> block to avoid a false positive from
        # the template's own example ("agenditasu 3,20 €" appears in the rules section).
        info_block = _extract_tag(prompt, "important_info")
        assert "3,20" not in info_block
        assert "45" in info_block

    def test_service_fee_stripped_from_prompt(self, make_event):
        event = make_event()
        event.important_info = "hinnad sisaldavad teenustasu 1.40€/ pilet"
        prompt = _build_classify_prompt(event)
        info_block = _extract_tag(prompt, "important_info")
        assert "1.40" not in info_block


class TestParseClassificationMalformedTaxonomy:
    def test_nested_list_in_categories_dropped(self):
        raw = {**_BASE_RAW, "categories": [["music"], "theater"]}
        result = _parse_classification(raw)
        assert result["categories"] == ["theater"]

    def test_nested_list_in_vibes_dropped(self):
        raw = {**_BASE_RAW, "vibes": [["intimate"], "niche"]}
        result = _parse_classification(raw)
        assert result["vibes"] == ["niche"]

    def test_non_list_categories_returns_empty(self):
        raw = {**_BASE_RAW, "categories": "music"}
        result = _parse_classification(raw)
        assert result["categories"] == []

    def test_categories_none_returns_empty(self):
        raw = {**_BASE_RAW, "categories": None}
        result = _parse_classification(raw)
        assert result["categories"] == []

    def test_non_list_vibes_returns_empty(self):
        raw = {**_BASE_RAW, "vibes": "intimate"}
        result = _parse_classification(raw)
        assert result["vibes"] == []

    def test_vibes_none_returns_empty(self):
        raw = {**_BASE_RAW, "vibes": None}
        result = _parse_classification(raw)
        assert result["vibes"] == []


class TestParseClassificationWhyGo:
    def test_dict_format_extracts_all_locales(self):
        raw = {
            "categories": ["music"],
            "vibes": ["intimate"],
            "why_go": {
                "en": ["Great DJs", "Late night", "Cool crowd"],
                "et": ["Parimad DJd", "Hiline öö", "Lahe rahvas"],
                "ru": ["Лучшие диджеи", "Поздней ночью", "Крутая публика"],
            },
            "quality": 0.8,
            "language": "en",
        }
        result = _parse_classification(raw)
        assert result["why_go_localized"]["en"] == ["Great DJs", "Late night", "Cool crowd"]
        assert result["why_go_localized"]["et"] == ["Parimad DJd", "Hiline öö", "Lahe rahvas"]
        assert result["why_go_localized"]["ru"] == ["Лучшие диджеи", "Поздней ночью", "Крутая публика"]
        assert result["why_go_bullets"] == ["Great DJs", "Late night", "Cool crowd"]

    def test_list_format_backward_compat(self):
        raw = {
            "categories": ["theater"],
            "vibes": ["niche"],
            "why_go": ["Unique performance", "Short run"],
            "quality": 0.7,
            "language": "et",
        }
        result = _parse_classification(raw)
        assert result["why_go_localized"] is None
        assert result["why_go_bullets"] == ["Unique performance", "Short run"]

    def test_dict_bullets_capped_at_3(self):
        raw = {
            "categories": ["music"],
            "vibes": [],
            "why_go": {
                "en": ["a", "b", "c", "d", "e"],
                "et": ["x"],
                "ru": [],
            },
            "quality": 0.5,
            "language": "en",
        }
        result = _parse_classification(raw)
        assert len(result["why_go_localized"]["en"]) == 3
        assert result["why_go_localized"]["et"] == ["x"]
        assert result["why_go_localized"]["ru"] == []

    def test_missing_locale_in_dict_returns_empty_list(self):
        raw = {
            "categories": ["music"],
            "vibes": [],
            "why_go": {"en": ["Only English"]},
            "quality": 0.5,
            "language": "en",
        }
        result = _parse_classification(raw)
        assert result["why_go_localized"]["et"] == []
        assert result["why_go_localized"]["ru"] == []

    def test_invalid_why_go_type_gives_empty(self):
        raw = {
            "categories": [],
            "vibes": [],
            "why_go": 42,
            "quality": None,
            "language": "en",
        }
        result = _parse_classification(raw)
        assert result["why_go_bullets"] == []
        assert result["why_go_localized"] is None


_BASE_RAW = {"categories": [], "vibes": [], "why_go": [], "quality": None, "language": "en"}


class TestParseClassificationPrice:
    def test_valid_price_min_max_and_currency(self):
        raw = {**_BASE_RAW, "price_min": 10, "price_max": 25, "currency": "EUR"}
        result = _parse_classification(raw)
        assert result["price_min"] == 10.0
        assert result["price_max"] == 25.0
        assert result["currency"] == "EUR"

    def test_negative_price_treated_as_unstated(self):
        raw = {**_BASE_RAW, "price_min": -5, "price_max": -1, "currency": None}
        result = _parse_classification(raw)
        assert result["price_min"] is None
        assert result["price_max"] is None
        assert result["currency"] is None

    def test_non_numeric_price_returns_none(self):
        raw = {**_BASE_RAW, "price_min": "free", "price_max": None, "currency": None}
        result = _parse_classification(raw)
        assert result["price_min"] is None
        assert result["price_max"] is None
        assert result["currency"] is None

    def test_zero_price_is_preserved_and_defaults_currency(self):
        raw = {**_BASE_RAW, "price_min": 0, "price_max": 0, "currency": None}
        result = _parse_classification(raw)
        assert result["price_min"] == 0.0
        assert result["price_max"] == 0.0
        assert result["currency"] == "EUR"

    def test_currency_longer_than_max_len_dropped(self):
        raw = {**_BASE_RAW, "price_min": 10, "price_max": None, "currency": "EUROS"}
        result = _parse_classification(raw)
        assert result["currency"] is None

    def test_missing_price_fields_default_to_none(self):
        result = _parse_classification(dict(_BASE_RAW))
        assert result["price_min"] is None
        assert result["price_max"] is None
        assert result["currency"] is None


class TestClassifyEventPrice:
    @pytest.mark.asyncio
    async def test_writes_price_fields_onto_event(self, mock_db, make_event):
        event = make_event()
        event.price_hint = "10 EUR"
        raw = {**_BASE_RAW, "price_min": 10, "price_max": 20, "currency": "EUR"}
        event.description_orig = "Full price 10 EUR, family ticket 20 EUR."
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min == 10.0
        assert event.price_max == 20.0
        assert event.currency == "EUR"

    @pytest.mark.asyncio
    async def test_invented_price_not_backed_by_text_is_nulled(self, mock_db, make_event):
        """Regression: the classify prompt's own JSON example amounts (10/20)
        must not leak into the answer for an event with no stated price at all —
        an LLM price with no literal match in price_hint/description is nulled."""
        event = make_event()
        event.price_hint = None
        event.description_orig = "A test event with no price information at all."
        raw = {**_BASE_RAW, "price_min": 10, "price_max": 20, "currency": "EUR"}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min is None
        assert event.price_max is None

    @pytest.mark.asyncio
    async def test_has_free_tier_accepted_when_backed_by_text(self, mock_db, make_event):
        event = make_event()
        event.price_hint = None
        event.description_orig = "Adult ticket €14. Members enter free."
        raw = {**_BASE_RAW, "price_min": 14, "price_max": 14, "currency": "EUR", "has_free_tier": True}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min == 14.0
        assert event.has_free_tier is True

    @pytest.mark.asyncio
    async def test_has_free_tier_rejected_without_free_keyword(self, mock_db, make_event):
        """has_free_tier must not survive when the source text has no free
        mention at all — an unenforced LLM claim would otherwise surface a
        'free options available' hint with nothing behind it."""
        event = make_event()
        event.price_hint = None
        event.description_orig = "Adult ticket €14."
        raw = {**_BASE_RAW, "price_min": 14, "price_max": 14, "currency": "EUR", "has_free_tier": True}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min == 14.0
        assert event.has_free_tier is False

    @pytest.mark.asyncio
    async def test_has_free_tier_rejected_when_price_min_nulled(self, mock_db, make_event):
        """has_free_tier=True alongside an invented (unbacked) price_min must
        not survive once that price_min is nulled by validation."""
        event = make_event()
        event.price_hint = None
        event.description_orig = "Members enter free. No further price stated."
        raw = {**_BASE_RAW, "price_min": 14, "price_max": 14, "currency": "EUR", "has_free_tier": True}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min is None
        assert event.has_free_tier is False

    @pytest.mark.asyncio
    async def test_reclassify_without_price_does_not_clobber_existing(self, mock_db, make_event):
        event = make_event()
        event.price_min = 10.0
        event.price_max = 20.0
        event.currency = "EUR"
        raw = dict(_BASE_RAW)
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min == 10.0
        assert event.price_max == 20.0
        assert event.currency == "EUR"

    @pytest.mark.asyncio
    async def test_ingest_price_not_overwritten_by_llm_guess(self, mock_db, make_event):
        """An ingest-set price (e.g. Fienta 'From 28 EUR') survives even when the LLM
        returns its own non-None price — ingest is authoritative."""
        event = make_event()
        event.price_min = 28.0
        event.price_max = None  # open-ended, no listing ceiling
        event.currency = "EUR"
        raw = {**_BASE_RAW, "price_min": 15, "price_max": 30, "currency": "EUR"}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min == 28.0
        assert event.price_max is None
        assert event.currency == "EUR"

    @pytest.mark.asyncio
    async def test_price_hint_net_widens_underreported_max(self, mock_db, make_event):
        """Regression for event-20/KUMU: LLM under-reports price_max (skips the
        €32 'Family' tier) but price_hint literally contains it — the
        deterministic net must widen the envelope to cover it."""
        event = make_event()
        event.price_hint = (
            "Adult: Kumu Art Museum €16, Family: Kumu Art Museum €32, "
            "Discount: Kumu Art Museum €11, Adult ticket with donation: "
            "Art Museum of Estonia €25"
        )
        raw = {**_BASE_RAW, "price_min": 11, "price_max": 25, "currency": "EUR"}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min == 11.0
        assert event.price_max == 32.0
        assert event.currency == "EUR"

    @pytest.mark.asyncio
    async def test_price_hint_net_does_not_shrink_min_from_description(
        self, mock_db, make_event
    ):
        """The net only widens. An LLM-reported price_min lower than any literal
        price_hint amount, but backed by a literal amount in the description
        (e.g. a student discount tier), must survive validation."""
        event = make_event()
        event.price_hint = "Adult €16, Family €32"
        event.description_orig = "Student discount €5 available at the door."
        raw = {**_BASE_RAW, "price_min": 5, "price_max": 32, "currency": "EUR"}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min == 5.0
        assert event.price_max == 32.0
        assert event.currency == "EUR"

    @pytest.mark.asyncio
    async def test_price_hint_net_skipped_for_non_eur_currency(self, mock_db, make_event):
        """A correctly-detected non-EUR price must not be polluted by an
        incidental €/EUR-looking amount elsewhere in price_hint."""
        event = make_event()
        event.price_hint = "Standard ticket 50 USD, donation tier 16 EUR optional"
        raw = {**_BASE_RAW, "price_min": 50, "price_max": 50, "currency": "USD"}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min == 50.0
        assert event.price_max == 50.0
        assert event.currency == "USD"

    @pytest.mark.asyncio
    async def test_price_hint_net_applies_for_lowercase_eur_currency(
        self, mock_db, make_event
    ):
        """normalize_currency() does not uppercase the LLM's raw string, so the
        currency gate must compare case-insensitively — a lowercase 'eur' must
        still trigger the widening net, not silently disable it."""
        event = make_event()
        event.price_hint = "Adult: Kumu Art Museum €16, Family: Kumu Art Museum €32"
        raw = {**_BASE_RAW, "price_min": 16, "price_max": 16, "currency": "eur"}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.price_min == 16.0
        assert event.price_max == 32.0
        assert event.currency == "eur"


class TestParseClassificationExplicit:
    def test_explicit_true(self):
        raw = {**_BASE_RAW, "explicit": True}
        result = _parse_classification(raw)
        assert result["explicit"] is True

    def test_explicit_false(self):
        raw = {**_BASE_RAW, "explicit": False}
        result = _parse_classification(raw)
        assert result["explicit"] is False

    def test_explicit_missing_defaults_to_false(self):
        result = _parse_classification(dict(_BASE_RAW))
        assert result["explicit"] is False


class TestClassifyEventExplicit:
    @pytest.mark.asyncio
    async def test_llm_flags_explicit_sets_is_explicit(self, mock_db, make_event):
        event = make_event()
        assert event.is_explicit is False
        raw = {**_BASE_RAW, "explicit": True}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.is_explicit is True

    @pytest.mark.asyncio
    async def test_pre_flagged_event_stays_flagged_when_llm_says_false(
        self, mock_db, make_event
    ):
        event = make_event()
        event.is_explicit = True
        raw = {**_BASE_RAW, "explicit": False}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.is_explicit is True

    @pytest.mark.asyncio
    async def test_llm_says_not_explicit_leaves_unflagged_event_unflagged(
        self, mock_db, make_event
    ):
        event = make_event()
        raw = {**_BASE_RAW, "explicit": False}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.is_explicit is False


class TestParseClassificationNonEvent:
    def test_non_event_true(self):
        raw = {**_BASE_RAW, "non_event": True}
        result = _parse_classification(raw)
        assert result["non_event"] is True

    def test_non_event_false(self):
        raw = {**_BASE_RAW, "non_event": False}
        result = _parse_classification(raw)
        assert result["non_event"] is False

    def test_non_event_missing_defaults_to_false(self):
        result = _parse_classification(dict(_BASE_RAW))
        assert result["non_event"] is False


class TestClassifyEventNonEvent:
    @pytest.mark.asyncio
    async def test_llm_flags_non_event_sets_is_non_event(self, mock_db, make_event):
        event = make_event()
        assert event.is_non_event is False
        raw = {**_BASE_RAW, "non_event": True}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.is_non_event is True

    @pytest.mark.asyncio
    async def test_pre_flagged_non_event_skips_llm_and_stays_flagged(
        self, mock_db, make_event
    ):
        event = make_event()
        event.is_non_event = True
        event.status = "draft"
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=({}, "groq/llama-3.3-70b-versatile")),
        ) as mock_llm:
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        mock_llm.assert_not_awaited()
        assert event.is_non_event is True
        from app.constants import EVENT_STATUS_CLASSIFIED

        assert event.status == EVENT_STATUS_CLASSIFIED

    @pytest.mark.asyncio
    async def test_llm_says_not_non_event_leaves_unflagged_event_unflagged(
        self, mock_db, make_event
    ):
        event = make_event()
        raw = {**_BASE_RAW, "non_event": False}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.is_non_event is False


class TestParseClassificationInTargetCity:
    def test_in_target_city_false_sets_flag(self):
        raw = {**_BASE_RAW, "in_target_city": False}
        result = _parse_classification(raw)
        assert result["in_target_city"] is False

    def test_in_target_city_true_clears_flag(self):
        raw = {**_BASE_RAW, "in_target_city": True}
        result = _parse_classification(raw)
        assert result["in_target_city"] is True

    def test_in_target_city_missing_defaults_to_true(self):
        result = _parse_classification(dict(_BASE_RAW))
        assert result["in_target_city"] is True


class TestClassifyEventOutOfArea:
    @pytest.mark.asyncio
    async def test_llm_not_in_city_sets_is_out_of_area(self, mock_db, make_event):
        event = make_event()
        assert event.is_out_of_area is False
        raw = {**_BASE_RAW, "in_target_city": False}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.is_out_of_area is True

    @pytest.mark.asyncio
    async def test_llm_in_city_leaves_is_out_of_area_false(self, mock_db, make_event):
        event = make_event()
        raw = {**_BASE_RAW, "in_target_city": True}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.is_out_of_area is False

    @pytest.mark.asyncio
    async def test_llm_field_omitted_defaults_fail_open(self, mock_db, make_event):
        event = make_event()
        raw = dict(_BASE_RAW)  # no in_target_city key
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.is_out_of_area is False


class TestClassifyEventSkipsLLMWhenAlreadyExplicit:
    @pytest.mark.asyncio
    async def test_keyword_flagged_event_skips_llm_call(self, mock_db, make_event):
        event = make_event()
        event.is_explicit = True
        event.status = "draft"
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=({}, "groq/llama-3.3-70b-versatile")),
        ) as mock_llm:
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        mock_llm.assert_not_awaited()
        assert event.is_explicit is True
        from app.constants import EVENT_STATUS_CLASSIFIED

        assert event.status == EVENT_STATUS_CLASSIFIED


class TestClassifyPendingIncludesExplicitRepresentatives:
    @pytest.mark.asyncio
    async def test_dedup_root_flagged_explicit_still_classified(self, mock_db, make_event):
        """A flagged dedup-group representative must still be picked up by
        classify_pending and advanced to `classified` — otherwise the whole
        cluster is permanently stuck in draft (it can never become root)."""
        event = make_event()
        event.is_explicit = True
        event.status = "draft"
        event.dedup_group_id = event.id

        events_result = MagicMock()
        events_result.all.return_value = [event]
        existing_result = MagicMock()
        existing_result.all.return_value = []
        mock_db.scalars.side_effect = [events_result, existing_result]

        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=({}, "groq/llama-3.3-70b-versatile")),
        ) as mock_llm:
            summary = await classify_pending(mock_db)

        mock_llm.assert_not_awaited()
        assert summary["succeeded"] == 1
        from app.constants import EVENT_STATUS_CLASSIFIED

        assert event.status == EVENT_STATUS_CLASSIFIED
        assert event.is_explicit is True


class TestNoLiveDedupSiblingClause:
    """Compiled-SQL check: verified live (VALUES-CTE query against the real DB)
    that a dedup-canonical representative with a still-live sibling correctly
    evaluates NOT EXISTS to False (blocks cancellation), while a solo event
    with no sibling evaluates to True (cancels normally). This test guards the
    query shape that produced those results."""

    def test_compiles_to_not_exists_correlated_on_own_id(self):
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        compiled = str(
            _no_live_dedup_sibling_clause(now).compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        assert "NOT (EXISTS" in compiled or "NOT EXISTS" in compiled
        assert "dedup_group_id" in compiled
        assert "!=" in compiled or "<>" in compiled
        assert "cancelled" in compiled
        assert "2026-06-25" in compiled


class TestClassifyPendingCancelsEndedDrafts:
    @pytest.mark.asyncio
    async def test_ended_drafts_bulk_cancelled_before_batch_select(self, mock_db):
        """A draft whose event already ended can never pass the publish gate
        even once classified — classify_pending must bulk-cancel it up front
        instead of spending a batch slot (or leaving it stuck in draft forever
        once its FIFO position falls behind newer arrivals)."""
        cancel_result = MagicMock()
        cancel_result.rowcount = 3
        mock_db.execute.return_value = cancel_result
        events_result = MagicMock()
        events_result.all.return_value = []
        mock_db.scalars.side_effect = [events_result]

        summary = await classify_pending(mock_db)

        mock_db.execute.assert_awaited_once()
        assert summary["cancelled"] == 3
        assert summary["attempted"] == 0

    @pytest.mark.asyncio
    async def test_no_ended_drafts_reports_zero_cancelled(self, mock_db, make_event):
        cancel_result = MagicMock()
        cancel_result.rowcount = 0
        mock_db.execute.return_value = cancel_result
        event = make_event()
        event.status = "draft"
        events_result = MagicMock()
        events_result.all.return_value = [event]
        existing_result = MagicMock()
        existing_result.all.return_value = []
        mock_db.scalars.side_effect = [events_result, existing_result]

        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(_BASE_RAW, "groq/llama-3.3-70b-versatile")),
        ):
            summary = await classify_pending(mock_db)

        assert summary["cancelled"] == 0
        assert summary["attempted"] == 1


class TestClassifyEventMalformedParse:
    @pytest.mark.asyncio
    async def test_nested_list_categories_dropped_not_crashed(self, mock_db, make_event):
        """Layer-1 fix: a 200 response with a nested-list category (groq
        malformed-shape bug) drops the bad entry and classifies normally —
        does not raise."""
        event = make_event()
        raw = {**_BASE_RAW, "categories": [["music"], "theater"]}
        with patch(
            "app.llm.classifier.llm_json",
            AsyncMock(return_value=(raw, "groq/llama-3.3-70b-versatile")),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is True
        assert event.classification.categories == ["theater"]

    @pytest.mark.asyncio
    async def test_parse_failure_degrades_to_skipped_event(self, mock_db, make_event):
        """Layer-2 defense-in-depth: any future malformed shape that still slips
        past layer 1 and raises inside _parse_classification must degrade to a
        skipped event (return False), not propagate and abort the batch."""
        from app.constants import EVENT_STATUS_DRAFT

        event = make_event()
        event.status = EVENT_STATUS_DRAFT
        with (
            patch(
                "app.llm.classifier.llm_json",
                AsyncMock(return_value=({}, "groq/llama-3.3-70b-versatile")),
            ),
            patch(
                "app.llm.classifier._parse_classification",
                side_effect=TypeError("cannot use 'list' as a set element"),
            ),
        ):
            ok = await classify_event(
                event, mock_db, existing_classification=event.classification, prefetched=True
            )

        assert ok is False
        assert event.status == EVENT_STATUS_DRAFT
