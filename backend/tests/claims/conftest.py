"""Shared helpers for the claims test modules (plain functions, not fixtures)."""

from unittest.mock import MagicMock

from app.constants.ingestion import SOURCE_SLUG_FIENTA


def fake_event_source(
    *,
    source: MagicMock | None = None,
    publisher_id: int | None = None,
    external_id: str = "100",
    source_slug: str = SOURCE_SLUG_FIENTA,
) -> MagicMock:
    """An EventSource stand-in. Pass ``source`` to reuse a prepared Source mock,
    otherwise one is built from ``source_slug``."""
    es = MagicMock()
    es.id = 7
    es.event_id = 10
    es.external_id = external_id
    es.publisher_id = publisher_id
    if source is None:
        source = MagicMock()
        source.slug = source_slug
        source.config = {}
    es.source = source
    if publisher_id is not None:
        publisher = MagicMock()
        publisher.id = publisher_id
        publisher.external_id = "42"
        es.publisher = publisher
    else:
        es.publisher = None
    return es
