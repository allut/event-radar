"""Unit tests for app.routers.utils.organizer_content."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.utils.organizer_content import (
    fold_legacy_category,
    prepend_organizer_categories,
    replace_organizer_categories,
    validate_categories,
)


class TestPrependOrganizerCategories:
    """Used by organizer_claim_edits.py (#416's prepend-only claim-edit categories)."""

    @pytest.mark.asyncio
    async def test_creates_classification_when_none_exists(self, mock_db):
        mock_db.scalar.return_value = None
        mock_db.add = MagicMock()

        await prepend_organizer_categories(mock_db, 10, ["music", "family"])

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert added.event_id == 10
        assert added.categories == ["music", "family"]

    @pytest.mark.asyncio
    async def test_prepends_several_in_order(self, mock_db):
        classification = MagicMock()
        classification.categories = ["theater"]
        mock_db.scalar.return_value = classification

        await prepend_organizer_categories(mock_db, 10, ["music", "family"])

        assert classification.categories == ["music", "family", "theater"]

    @pytest.mark.asyncio
    async def test_dedupes_against_existing(self, mock_db):
        classification = MagicMock()
        classification.categories = ["music", "theater"]
        mock_db.scalar.return_value = classification

        await prepend_organizer_categories(mock_db, 10, ["family", "music"])

        assert classification.categories == ["family", "music", "theater"]

    @pytest.mark.asyncio
    async def test_all_present_leaves_order_untouched(self, mock_db):
        classification = MagicMock()
        classification.categories = ["music", "theater"]
        mock_db.scalar.return_value = classification

        await prepend_organizer_categories(mock_db, 10, ["theater"])

        assert classification.categories == ["music", "theater"]


class TestPrependOrganizerCategoriesCap:
    @pytest.mark.asyncio
    async def test_over_total_cap_rejected_and_untouched(self, mock_db):
        classification = MagicMock()
        classification.categories = ["music", "theater"]
        mock_db.scalar.return_value = classification

        with pytest.raises(HTTPException) as exc:
            await prepend_organizer_categories(
                mock_db, 10, ["family", "comedy"], max_total=3
            )

        assert exc.value.status_code == 422
        assert classification.categories == ["music", "theater"]

    @pytest.mark.asyncio
    async def test_exactly_at_cap_allowed(self, mock_db):
        classification = MagicMock()
        classification.categories = ["music", "theater"]
        mock_db.scalar.return_value = classification

        await prepend_organizer_categories(mock_db, 10, ["family"], max_total=3)

        assert classification.categories == ["family", "music", "theater"]

    @pytest.mark.asyncio
    async def test_already_present_picks_do_not_count(self, mock_db):
        classification = MagicMock()
        classification.categories = ["music", "theater", "family"]
        mock_db.scalar.return_value = classification

        await prepend_organizer_categories(mock_db, 10, ["music"], max_total=3)

        assert classification.categories == ["music", "theater", "family"]

    @pytest.mark.asyncio
    async def test_event_over_cap_cannot_gain(self, mock_db):
        classification = MagicMock()
        classification.categories = ["a", "b", "c", "d"]
        mock_db.scalar.return_value = classification

        with pytest.raises(HTTPException):
            await prepend_organizer_categories(mock_db, 10, ["music"], max_total=3)


class TestReplaceOrganizerCategories:
    """Used by organizer_events.py (own-submission create + edit)."""

    @pytest.mark.asyncio
    async def test_creates_classification_when_none_exists(self, mock_db):
        mock_db.scalar.return_value = None
        mock_db.add = MagicMock()

        await replace_organizer_categories(mock_db, 10, ["music", "family"])

        added = mock_db.add.call_args[0][0]
        assert added.event_id == 10
        assert added.categories == ["music", "family"]

    @pytest.mark.asyncio
    async def test_replaces_llm_set(self, mock_db):
        classification = MagicMock()
        classification.categories = ["theater", "comedy"]
        mock_db.scalar.return_value = classification

        await replace_organizer_categories(mock_db, 10, ["music", "family"])

        assert classification.categories == ["music", "family"]


class TestValidateCategories:
    def test_none_passes_through(self):
        assert validate_categories(None) is None

    def test_dedupes_keeping_order(self):
        assert validate_categories(["music", "family", "music"]) == ["music", "family"]

    def test_invalid_slug_rejected(self):
        with pytest.raises(ValueError, match="invalid category"):
            validate_categories(["music", "nope"])

    def test_over_cap_rejected(self):
        with pytest.raises(ValueError, match="at most"):
            validate_categories(["music", "family", "theater", "comedy"])

    def test_duplicates_do_not_count_toward_cap(self):
        assert validate_categories(["music", "music", "family", "theater"]) == [
            "music",
            "family",
            "theater",
        ]


class TestFoldLegacyCategory:
    def test_folds_into_categories(self):
        assert fold_legacy_category({"title": "x", "category": "music"}) == {
            "title": "x",
            "categories": ["music"],
        }

    def test_explicit_categories_win(self):
        assert fold_legacy_category({"category": "music", "categories": ["family"]}) == {
            "categories": ["family"]
        }

    def test_null_legacy_dropped(self):
        assert fold_legacy_category({"category": None}) == {}

    def test_non_dict_untouched(self):
        assert fold_legacy_category("x") == "x"


class TestOrganizerSharedHelpers:
    def test_validate_time_ordering(self):
        from app.routers.utils.organizer_content import validate_time_ordering

        early = datetime(2026, 6, 1, 18, tzinfo=timezone.utc)
        late = datetime(2026, 6, 1, 20, tzinfo=timezone.utc)
        validate_time_ordering(early, late)
        validate_time_ordering(early, None)
        validate_time_ordering(None, early)
        with pytest.raises(ValueError, match="ends_at must not be before starts_at"):
            validate_time_ordering(late, early)

    def test_localized_dict_drops_blank_and_absent_locales(self):
        from app.routers.utils.organizer_content import localized_dict

        assert localized_dict("et", "en", None) == {"et": "et", "en": "en"}
        assert localized_dict("et", "  ", "") == {"et": "et"}
        assert localized_dict(None, None, None) is None

    def test_merged_localized_keeps_existing_and_overrides_set_fields(self):
        from types import SimpleNamespace

        from app.routers.utils.organizer_content import merged_localized

        body = SimpleNamespace(title_en="New EN", title_ru=None)
        existing = {"et": "old", "en": "Old EN", "ru": "Old RU"}

        # only en is in fields_set: ru keeps its existing value
        assert merged_localized(existing, "Uus", body, {"title_en"}, "title") == {
            "et": "Uus",
            "en": "New EN",
            "ru": "Old RU",
        }
        # ru explicitly cleared (None in fields_set) drops the locale
        assert merged_localized(existing, "Uus", body, {"title_ru"}, "title") == {
            "et": "Uus",
            "en": "Old EN",
        }

    def test_merged_localized_applies_sanitizer_to_request_values_only(self):
        from types import SimpleNamespace

        from app.routers.utils.organizer_content import merged_localized

        body = SimpleNamespace(description_en="<b>x</b>", description_ru=None)
        result = merged_localized(
            {"ru": "<i>kept</i>"},
            "et",
            body,
            {"description_en"},
            "description",
            sanitize=str.upper,
        )
        assert result == {"et": "et", "en": "<B>X</B>", "ru": "<i>kept</i>"}

    def test_apply_price_edit_fills_default_currency_for_price_only_patch(self, make_event):
        from types import SimpleNamespace

        from app._generated.shared_constants import DEFAULT_CURRENCY
        from app.routers.utils.organizer_content import apply_price_edit

        event = make_event(price_min=None)
        event.price_max = None
        event.currency = None
        body = SimpleNamespace(price_min=5.0, price_max=None, currency=None)

        apply_price_edit(event, body, {"price_min"})

        assert event.price_min == 5.0
        assert event.currency == DEFAULT_CURRENCY

    def test_apply_price_edit_zero_price_still_counts_as_priced(self, make_event):
        """Numeric-truthiness rule: a free (0) price is a price."""
        from types import SimpleNamespace

        from app._generated.shared_constants import DEFAULT_CURRENCY
        from app.routers.utils.organizer_content import apply_price_edit

        event = make_event(price_min=None)
        event.price_max = None
        event.currency = None
        body = SimpleNamespace(price_min=0.0, price_max=None, currency=None)

        apply_price_edit(event, body, {"price_min"})

        assert event.currency == DEFAULT_CURRENCY

    def test_apply_moderation_flags_sets_flags_and_reports_change(self, make_event):
        from app.routers.utils.organizer_content import apply_moderation_flags

        event = make_event(title="Nice concert")
        event.is_explicit = False
        event.is_non_event = False
        with patch("app.routers.utils.organizer_content.content_flags", return_value=(True, False)):
            assert apply_moderation_flags(event, "Hall", "extra") is True

        assert event.is_explicit is True
        assert event.is_non_event is False

    def test_apply_moderation_flags_clean_event_returns_false(self, make_event):
        from app.routers.utils.organizer_content import apply_moderation_flags

        event = make_event(title="Nice concert")
        event.is_explicit = False
        event.is_non_event = False
        assert apply_moderation_flags(event, "Hall") is False
        assert event.is_explicit is False

    def test_apply_moderation_flags_scans_localized_text(self, make_event):
        """OWASP audit M-5: explicit text hidden only in EN/RU fields is caught."""
        from app.routers.utils.organizer_content import apply_moderation_flags

        event = make_event(title="Nice concert")
        event.is_explicit = False
        event.is_non_event = False
        event.title_localized = {"en": "Nice concert", "ru": "xxx porn night"}
        event.description_localized = None
        event.important_info_localized = None
        event.important_info = None
        assert apply_moderation_flags(event, "Hall") is True
        assert event.is_explicit is True
