"""Unit tests for source seeding (app/seeds.py) — organizer retirement survival."""

from unittest.mock import patch

import pytest

from app.constants import SOURCE_KIND_API, SOURCE_SLUG_FIENTA
from app.models.models import Source
from app.seeds import _upsert_fienta


def _existing_source(config: dict) -> Source:
    return Source(
        slug=SOURCE_SLUG_FIENTA, kind=SOURCE_KIND_API, config=config, enabled=True
    )


@pytest.mark.asyncio
async def test_retired_organizer_not_resurrected_by_seed_union(mock_db):
    """A hardcoded settings.FIENTA_ORGANIZER_IDS entry that organizer_sync has
    since retired must not reappear in organizer_ids after re-seeding."""
    existing = _existing_source(
        {
            "organizer_ids": [42, 99],
            "organizer_names": {"42": "Org A", "99": "Retired Org"},
            "retired_organizer_ids": [99],
        }
    )
    mock_db.scalar.return_value = existing

    with patch("app.seeds.settings") as mock_settings:
        mock_settings.FIENTA_BASE_URL = "https://fienta.com/api/v1/public/events"
        mock_settings.FIENTA_ORGANIZER_IDS = [42, 99]  # 99 still hardcoded in config.py
        mock_settings.FIENTA_ORGANIZER_NAMES = {"42": "Org A", "99": "Retired Org"}

        await _upsert_fienta(mock_db)

    assert 99 not in existing.config["organizer_ids"]
    assert existing.config["organizer_ids"] == [42]


@pytest.mark.asyncio
async def test_auto_discovered_organizer_preserved_across_reseed(mock_db):
    """Non-retired auto-discovered IDs already in DB survive the union."""
    existing = _existing_source(
        {
            "organizer_ids": [42, 555],
            "organizer_names": {"42": "Org A", "555": "Auto-discovered Org"},
        }
    )
    mock_db.scalar.return_value = existing

    with patch("app.seeds.settings") as mock_settings:
        mock_settings.FIENTA_BASE_URL = "https://fienta.com/api/v1/public/events"
        mock_settings.FIENTA_ORGANIZER_IDS = [42]
        mock_settings.FIENTA_ORGANIZER_NAMES = {"42": "Org A"}

        await _upsert_fienta(mock_db)

    assert set(existing.config["organizer_ids"]) == {42, 555}


@pytest.mark.asyncio
async def test_retirement_metadata_survives_reseed(mock_db):
    """stale_since / retired_organizer_ids keys are preserved through the merge."""
    existing = _existing_source(
        {
            "organizer_ids": [42],
            "organizer_names": {"42": "Org A"},
            "retired_organizer_ids": [99],
            "stale_since": {"7": "2026-01-01T00:00:00+02:00"},
        }
    )
    mock_db.scalar.return_value = existing

    with patch("app.seeds.settings") as mock_settings:
        mock_settings.FIENTA_BASE_URL = "https://fienta.com/api/v1/public/events"
        mock_settings.FIENTA_ORGANIZER_IDS = [42]
        mock_settings.FIENTA_ORGANIZER_NAMES = {"42": "Org A"}

        await _upsert_fienta(mock_db)

    assert existing.config["retired_organizer_ids"] == [99]
    assert existing.config["stale_since"] == {"7": "2026-01-01T00:00:00+02:00"}
