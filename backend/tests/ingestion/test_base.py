"""Tests for shared ingestion helpers in app.ingestion.base."""

import pytest
from bs4 import BeautifulSoup

from app.ingestion.base import (
    address_city,
    coords_in_estonia,
    extract_jsonld_event_location,
    extract_jsonld_event_offers,
    is_explicit_text,
    is_target_city,
    parse_price_from_string,
)


class TestIsExplicitText:
    def test_positive_english_title(self):
        assert is_explicit_text("Striptease Night") is True

    def test_positive_mixed_case(self):
        assert is_explicit_text("PORN star live") is True

    def test_positive_russian(self):
        assert is_explicit_text("стриптиз шоу в клубе") is True

    def test_positive_estonian(self):
        assert is_explicit_text("Suur striptiis õhtu") is True

    def test_negative_sussex_does_not_match_sex(self):
        assert is_explicit_text("Sussex Quartet live concert") is False

    def test_negative_essex_street_jazz(self):
        assert is_explicit_text("Essex Street Jazz Night") is False

    def test_negative_comic_strip_does_not_match_strip(self):
        assert is_explicit_text("Comic strip workshop for kids") is False

    def test_negative_normal_nightlife_title(self):
        assert is_explicit_text("Techno night at Hall club") is False

    def test_checks_all_provided_parts(self):
        assert is_explicit_text("Friday night", None, "Brothel Bar") is True

    def test_none_parts_are_ignored(self):
        assert is_explicit_text(None, None, None) is False

    def test_empty_string_is_not_explicit(self):
        assert is_explicit_text("") is False


class TestAddressCity:
    def test_extracts_tallinn(self):
        assert address_city("Narva maantee 63, 10152 Tallinn, Harju maakond") == "Tallinn"

    def test_extracts_tartu(self):
        assert address_city("Ülikooli 18, 51003 Tartu, Tartumaa") == "Tartu"

    def test_extracts_parnu(self):
        assert address_city("Rüütli 40, 80010 Pärnu, Pärnumaa") == "Pärnu"

    def test_no_postal_code_returns_none(self):
        assert address_city("Vanaturu kael 3") is None

    def test_none_returns_none(self):
        assert address_city("") is None


class TestIsTargetCity:
    def test_tallinn_address_is_target(self):
        assert is_target_city("Narva maantee 63, 10152 Tallinn, Harju maakond") is True

    def test_tartu_address_is_not_target(self):
        assert is_target_city("Ülikooli 18, 51003 Tartu, Tartumaa") is False

    def test_parnu_address_is_not_target(self):
        assert is_target_city("Rüütli 40, 80010 Pärnu, Pärnumaa") is False

    def test_city_less_address_kept(self):
        assert is_target_city("Vanaturu kael 3") is True

    def test_none_address_kept(self):
        assert is_target_city(None) is True

    # Allowlist regression: these cities were ABSENT from the old denylist and
    # leaked through. Under the allowlist (city != Tallinn → drop) they must fail.
    def test_small_estonian_town_kardla_dropped(self):
        assert is_target_city("Posti 13, 92411 Kärdla, Hiiumaa") is False

    def test_small_estonian_town_korgessaare_dropped(self):
        assert is_target_city("Kõpu tee 1, 92201 Kõrgessaare") is False

    def test_foreign_city_angers_dropped(self):
        assert is_target_city("Rue Bressigny 1, 49000 Angers, France") is False

    def test_foreign_city_gent_dropped(self):
        assert is_target_city("Korenmarkt 1, 9000 Gent, Belgium") is False

    def test_foreign_city_dusseldorf_dropped(self):
        assert is_target_city("Königsallee 1, 40212 Düsseldorf, Germany") is False

    def test_foreign_city_warszawa_dropped(self):
        assert is_target_city("Marszałkowska 1, 00-661 Warszawa, Poland") is False


class TestParsePriceFromString:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("10 EUR", (10.0, 10.0, "EUR")),
            ("From 28 EUR", (28.0, None, "EUR")),
            ("From 6 EUR, free", (0.0, None, "EUR")),
            ("40 EUR, free", (0.0, 40.0, "EUR")),
            ("Free", (0.0, 0.0, None)),
            (None, (None, None, None)),
            ("", (None, None, None)),
            ("From 9.50 EUR", (9.5, None, "EUR")),
            ("From 3,08 EUR", (3.08, None, "EUR")),  # comma decimal defensiveness
            ("From 20 CHF", (20.0, None, "CHF")),
            ("18 PLN", (18.0, 18.0, "PLN")),
            ("sold out", (None, None, None)),  # unparseable, not free
        ],
    )
    def test_grammar_table(self, value, expected):
        assert parse_price_from_string(value) == expected

    def test_currency_uppercased(self):
        assert parse_price_from_string("12 eur")[2] == "EUR"


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _ld_script(json_body: str) -> str:
    return f'<script type="application/ld+json">{json_body}</script>'


class TestExtractJsonldEventLocation:
    def test_geo_coordinates_from_location_geo(self):
        html = _ld_script(
            '{"@type":"Event","location":{"@type":"Place","name":"Vaba Lava",'
            '"geo":{"@type":"GeoCoordinates","latitude":59.437,"longitude":24.753},'
            '"address":{"streetAddress":"Telliskivi 60a","addressLocality":"Tallinn"}}}'
        )
        result = extract_jsonld_event_location(_soup(html))
        assert result is not None
        assert result["lat"] == pytest.approx(59.437)
        assert result["lng"] == pytest.approx(24.753)
        assert result["venue_name"] == "Vaba Lava"
        assert "Tallinn" in (result["venue_address"] or "")

    def test_direct_lat_lng_fallback(self):
        html = _ld_script(
            '{"@type":"Event","location":{"@type":"Place","latitude":59.4,"longitude":24.7}}'
        )
        result = extract_jsonld_event_location(_soup(html))
        assert result is not None
        assert result["lat"] == pytest.approx(59.4)
        assert result["lng"] == pytest.approx(24.7)

    def test_no_event_returns_none(self):
        html = _ld_script('{"@type":"Organization","name":"Fienta"}')
        assert extract_jsonld_event_location(_soup(html)) is None

    def test_no_jsonld_returns_none(self):
        assert extract_jsonld_event_location(_soup("<html></html>")) is None


class TestExtractJsonldEventOffers:
    def test_single_offer(self):
        html = _ld_script(
            '{"@type":"Event","offers":{"@type":"Offer","price":"15","priceCurrency":"EUR"}}'
        )
        assert extract_jsonld_event_offers(_soup(html)) == (15.0, 15.0, "EUR")

    def test_multiple_offers_min_max(self):
        html = _ld_script(
            '{"@type":"Event","offers":['
            '{"@type":"Offer","price":"28","priceCurrency":"EUR"},'
            '{"@type":"Offer","price":"75","priceCurrency":"EUR"}'
            "]}"
        )
        result = extract_jsonld_event_offers(_soup(html))
        assert result == (28.0, 75.0, "EUR")

    def test_free_tier_zero_price(self):
        html = _ld_script(
            '{"@type":"Event","offers":['
            '{"@type":"Offer","price":"0","priceCurrency":"EUR"},'
            '{"@type":"Offer","price":"10","priceCurrency":"EUR"}'
            "]}"
        )
        assert extract_jsonld_event_offers(_soup(html)) == (0.0, 10.0, "EUR")

    def test_no_offers_returns_none_tuple(self):
        html = _ld_script('{"@type":"Event"}')
        assert extract_jsonld_event_offers(_soup(html)) == (None, None, None)

    def test_no_event_returns_none_tuple(self):
        html = _ld_script('{"@type":"Organization"}')
        assert extract_jsonld_event_offers(_soup(html)) == (None, None, None)

    def test_currency_uppercased(self):
        html = _ld_script(
            '{"@type":"Event","offers":{"@type":"Offer","price":"10","priceCurrency":"eur"}}'
        )
        assert extract_jsonld_event_offers(_soup(html))[2] == "EUR"


class TestCoordsInEstonia:
    def test_tallinn_coords_in_estonia(self):
        assert coords_in_estonia(59.437, 24.753) is True

    def test_tartu_coords_in_estonia(self):
        assert coords_in_estonia(58.378, 26.729) is True

    def test_helsinki_outside_estonia(self):
        assert coords_in_estonia(60.169, 24.935) is False

    def test_riga_outside_estonia(self):
        assert coords_in_estonia(56.946, 24.106) is False

    def test_bbox_south_edge(self):
        assert coords_in_estonia(57.5, 25.0) is True

    def test_below_south_edge(self):
        assert coords_in_estonia(57.4, 25.0) is False
