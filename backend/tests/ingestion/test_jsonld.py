"""Unit tests for app/ingestion/jsonld.py's organizer extraction (#409/#411)."""

import json

from bs4 import BeautifulSoup

from app.ingestion.jsonld import (
    extract_jsonld_event_organizer,
    organizer_from_jsonld_items,
    parse_jsonld_event_items,
)


def _soup(event: dict) -> BeautifulSoup:
    html = (
        "<html><body>"
        f'<script type="application/ld+json">{json.dumps(event)}</script>'
        "</body></html>"
    )
    return BeautifulSoup(html, "html.parser")


class TestOrganizerFromJsonldItems:
    def test_extracts_id_name_url(self):
        event = {
            "@type": "Event",
            "organizer": {
                "@type": "Organization",
                "@id": "https://www.piletilevi.ee/en/promoters/123/acme",
                "name": "Acme Productions",
                "url": "https://acme.ee",
            },
        }
        soup = _soup(event)
        result = organizer_from_jsonld_items(parse_jsonld_event_items(soup))

        assert result == {
            "external_id": "https://www.piletilevi.ee/en/promoters/123/acme",
            "name": "Acme Productions",
            "url": "https://acme.ee",
        }

    def test_falls_back_to_url_when_no_id(self):
        event = {
            "@type": "Event",
            "organizer": {"@type": "Organization", "name": "Acme", "url": "https://acme.ee"},
        }
        soup = _soup(event)
        result = organizer_from_jsonld_items(parse_jsonld_event_items(soup))

        assert result is not None
        assert result["external_id"] == "https://acme.ee"

    def test_none_when_organizer_absent(self):
        event = {"@type": "Event", "name": "No Organizer"}
        soup = _soup(event)
        assert organizer_from_jsonld_items(parse_jsonld_event_items(soup)) is None

    def test_none_when_organizer_not_a_dict(self):
        event = {"@type": "Event", "organizer": "Acme Productions"}
        soup = _soup(event)
        assert organizer_from_jsonld_items(parse_jsonld_event_items(soup)) is None

    def test_none_when_organizer_has_neither_id_nor_name(self):
        event = {"@type": "Event", "organizer": {"@type": "Organization"}}
        soup = _soup(event)
        assert organizer_from_jsonld_items(parse_jsonld_event_items(soup)) is None

    def test_name_only_no_id_or_url(self):
        event = {"@type": "Event", "organizer": {"@type": "Organization", "name": "Acme"}}
        soup = _soup(event)
        result = organizer_from_jsonld_items(parse_jsonld_event_items(soup))

        assert result == {"external_id": None, "name": "Acme", "url": None}


class TestExtractJsonldEventOrganizer:
    def test_wrapper_matches_items_variant(self):
        event = {
            "@type": "Event",
            "organizer": {"@type": "Organization", "name": "Acme", "@id": "acme-1"},
        }
        soup = _soup(event)
        assert extract_jsonld_event_organizer(soup) == {
            "external_id": "acme-1",
            "name": "Acme",
            "url": None,
        }
