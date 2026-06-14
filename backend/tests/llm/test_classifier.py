"""Tests for LLM classifier — parse_classification and why_go localization."""

from unittest.mock import AsyncMock, patch

import pytest

from app.llm.classifier import _parse_classification, classify_event


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
