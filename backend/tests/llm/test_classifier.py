"""Tests for LLM classifier — parse_classification and why_go localization."""

from app.llm.classifier import _parse_classification


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
