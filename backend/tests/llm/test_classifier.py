"""Tests for LLM classifier — parse_classification and why_go localization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.classifier import _parse_classification, classify_event, classify_pending


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
        raw = {**_BASE_RAW, "price_min": 10, "price_max": 20, "currency": "EUR"}
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
