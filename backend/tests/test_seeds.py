"""Unit tests for source seeding (app/seeds.py) — organizer retirement survival."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.ingestion import (
    PUBLISHER_NAME_ESTONIA_CONCERT_HALL,
    PUBLISHER_NAME_KUMU,
    PUBLISHER_STATUS_ACTIVE,
    SOURCE_KIND_API,
    SOURCE_KIND_HTML_SCRAPE,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
)
from app.models.models import Publisher, Source
from app.seeds import _upsert_fienta, seed_publishers


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
    with patch("app.seeds.settings") as mock_settings:
        mock_settings.FIENTA_BASE_URL = "https://fienta.com/api/v1/public/events"
        mock_settings.FIENTA_ORGANIZER_IDS = [42, 99]  # 99 still hardcoded in config.py
        mock_settings.FIENTA_ORGANIZER_NAMES = {"42": "Org A", "99": "Retired Org"}

        await _upsert_fienta(mock_db, existing)

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
    with patch("app.seeds.settings") as mock_settings:
        mock_settings.FIENTA_BASE_URL = "https://fienta.com/api/v1/public/events"
        mock_settings.FIENTA_ORGANIZER_IDS = [42]
        mock_settings.FIENTA_ORGANIZER_NAMES = {"42": "Org A"}

        await _upsert_fienta(mock_db, existing)

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
    with patch("app.seeds.settings") as mock_settings:
        mock_settings.FIENTA_BASE_URL = "https://fienta.com/api/v1/public/events"
        mock_settings.FIENTA_ORGANIZER_IDS = [42]
        mock_settings.FIENTA_ORGANIZER_NAMES = {"42": "Org A"}

        await _upsert_fienta(mock_db, existing)

    assert existing.config["retired_organizer_ids"] == [99]
    assert existing.config["stale_since"] == {"7": "2026-01-01T00:00:00+02:00"}


# ---------------------------------------------------------------------------
# seed_publishers (#409/#411) — the KUMU/Estonia Concert Hall constant
# Publisher rows (external_id NULL).
# ---------------------------------------------------------------------------


def _kumu_source(id_: int) -> Source:
    return Source(
        id=id_, slug=SOURCE_SLUG_KUMU, kind=SOURCE_KIND_HTML_SCRAPE, config={}, enabled=True
    )


def _ech_source(id_: int) -> Source:
    return Source(
        id=id_,
        slug=SOURCE_SLUG_ESTONIA_CONCERT_HALL,
        kind=SOURCE_KIND_HTML_SCRAPE,
        config={},
        enabled=True,
    )


def _nested_cm(mock_db) -> MagicMock:
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    mock_db.begin_nested = MagicMock(return_value=nested_cm)
    return nested_cm


@pytest.mark.asyncio
async def test_seed_publishers_creates_both_constant_rows(mock_db):
    _nested_cm(mock_db)
    kumu = _kumu_source(1)
    ech = _ech_source(2)
    mock_db.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=[kumu, ech])),  # sources lookup
        MagicMock(all=MagicMock(return_value=[])),  # existing publishers lookup
    ]

    await seed_publishers(mock_db)

    added = [c.args[0] for c in mock_db.add.call_args_list]
    assert len(added) == 2
    by_source_id = {p.source_id: p for p in added}
    assert by_source_id[1].name == PUBLISHER_NAME_KUMU
    assert by_source_id[1].external_id is None
    assert by_source_id[1].status == PUBLISHER_STATUS_ACTIVE
    assert by_source_id[2].name == PUBLISHER_NAME_ESTONIA_CONCERT_HALL
    assert by_source_id[2].external_id is None


@pytest.mark.asyncio
async def test_seed_publishers_idempotent_when_already_seeded(mock_db):
    kumu = _kumu_source(1)
    existing_publisher = Publisher(
        source_id=1, external_id=None, name=PUBLISHER_NAME_KUMU, status=PUBLISHER_STATUS_ACTIVE
    )
    mock_db.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=[kumu])),
        MagicMock(all=MagicMock(return_value=[existing_publisher])),
    ]

    await seed_publishers(mock_db)

    assert mock_db.add.call_args_list == []


@pytest.mark.asyncio
async def test_seed_publishers_noop_when_sources_not_seeded_yet(mock_db):
    """seed_sources() must have already run this startup — no source rows
    means nothing to attach a Publisher to yet."""
    mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

    await seed_publishers(mock_db)

    assert mock_db.add.call_args_list == []


@pytest.mark.asyncio
async def test_seed_publishers_tolerates_concurrent_seed_race(mock_db, caplog):
    """ix_publishers_source_null_external (migration 0042): a concurrent
    startup (e.g. an overlapping rolling deploy) inserting the same
    source's constant row first must not crash this one — the savepoint
    rolls back only that insert."""
    _nested_cm(mock_db)
    from sqlalchemy.exc import IntegrityError

    mock_db.flush.side_effect = IntegrityError("stmt", {}, Exception("dup key"))
    kumu = _kumu_source(1)
    mock_db.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=[kumu])),
        MagicMock(all=MagicMock(return_value=[])),
    ]

    await seed_publishers(mock_db)  # must not raise
