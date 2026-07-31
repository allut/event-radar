"""Tests for the shared ingestion helper modules (http_client, sanitize, pricing, jsonld, adapter)."""

import http
import socket
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup
from tenacity import RetryCallState

from app.constants import (
    HTTP_RETRY_AFTER_MAX_SECONDS,
    SOURCE_KIND_API,
    SOURCE_KIND_USER_SUBMISSION,
    TALLINN_TZ,
)
from app.ingestion.adapter import (
    NormalizedEvent,
    SourceAdapter,
    coords_in_estonia,
    coords_in_tallinn,
    insert_normalized_event,
)
from app.ingestion.content_filters import is_explicit_text, is_non_event_text
from app.ingestion.http_client import (
    AsyncRateLimiter,
    _retry_wait,
    host_is_allowed,
    resolves_to_private_ip,
    retry_after_seconds,
    safe_fetchable_url,
)
from app.ingestion.jsonld import (
    extract_jsonld_event_location,
    extract_jsonld_event_offers,
)
from app.ingestion.pricing import (
    eur_amounts_from_text,
    eur_price_bounds_from_text,
    parse_price_from_string,
    price_context_digest,
    strip_fee_amounts,
)
from app.ingestion.sources.fienta import address_city, is_target_city


def _addrinfo(*ips: str) -> list:
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips
    ]


class TestHostIsAllowed:
    def test_exact_match(self):
        assert host_is_allowed("fienta.com") is True

    def test_case_insensitive(self):
        assert host_is_allowed("Fienta.COM") is True

    def test_subdomain_match(self):
        assert host_is_allowed("en.fienta.com") is True

    def test_unrelated_host_rejected(self):
        assert host_is_allowed("evil.com") is False

    def test_lookalike_suffix_not_matched(self):
        # "notfienta.com" ends with "fienta.com" as a raw string but is not a
        # subdomain of it — must not match.
        assert host_is_allowed("notfienta.com") is False

    def test_none_rejected(self):
        assert host_is_allowed(None) is False

    def test_empty_string_rejected(self):
        assert host_is_allowed("") is False


class TestResolvesToPrivateIp:
    def test_public_ip_is_not_private(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
            assert resolves_to_private_ip("example.com") is False

    def test_loopback_is_private(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
            assert resolves_to_private_ip("localhost") is True

    def test_link_local_metadata_ip_is_private(self):
        # 169.254.169.254 — cloud metadata endpoint, the canonical SSRF target.
        with patch("socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")):
            assert resolves_to_private_ip("evil.example") is True

    def test_rfc1918_is_private(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo("10.0.0.5")):
            assert resolves_to_private_ip("internal.example") is True

    def test_dns_failure_treated_as_private(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("no such host")):
            assert resolves_to_private_ip("nonexistent.invalid") is True

    def test_any_public_address_among_many_is_allowed(self):
        with patch(
            "socket.getaddrinfo", return_value=_addrinfo("10.0.0.5", "93.184.216.34")
        ):
            assert resolves_to_private_ip("mixed.example") is False


class TestSafeFetchableUrl:
    @pytest.mark.asyncio
    async def test_allowed_host_public_ip_passes(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
            result = await safe_fetchable_url("https://fienta.com/e/123", "fienta")
        assert result == "https://fienta.com/e/123"

    @pytest.mark.asyncio
    async def test_non_allowlisted_host_rejected(self):
        result = await safe_fetchable_url("https://evil.com/e/123", "fienta")
        assert result is None

    @pytest.mark.asyncio
    async def test_private_ip_rejected_even_on_allowlisted_host(self):
        # DNS-rebinding scenario: hostname passes the allowlist but resolves
        # to a private/metadata address.
        with patch("socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")):
            result = await safe_fetchable_url("https://fienta.com/e/123", "fienta")
        assert result is None

    @pytest.mark.asyncio
    async def test_non_http_scheme_rejected_before_dns_lookup(self):
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            result = await safe_fetchable_url("javascript:alert(1)", "fienta")
        assert result is None
        mock_getaddrinfo.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_url_returns_none(self):
        assert await safe_fetchable_url(None, "fienta") is None


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

    def test_checks_important_info_part(self):
        # important_info (e.g. Piletilevi's age/content-warning section) must
        # be scanned the same as title/description/venue — it's where a
        # detail page's only explicit signal sometimes lives.
        assert is_explicit_text("Friday night", None, None, "Striptease show") is True

    def test_none_parts_are_ignored(self):
        assert is_explicit_text(None, None, None) is False

    def test_empty_string_is_not_explicit(self):
        assert is_explicit_text("") is False

    # Kink/BDSM (added after event 563 audit — "Butt Stuff Workshop")
    def test_positive_strap_on_fisting_description(self):
        assert is_explicit_text(
            "Butt Stuff Workshop",
            "Talking about anal pleasure, strap-on play and fisting.",
        ) is True

    def test_positive_femdom_party_title(self):
        assert is_explicit_text("Kultus FemDom party: Crossdress & Sissyfication") is True

    def test_positive_bdsm_keyword(self):
        assert is_explicit_text("Intro to BDSM for beginners") is True

    def test_positive_anal_sex_phrase(self):
        assert is_explicit_text("Workshop", "A night about anal sex and pleasure.") is True

    def test_negative_swing_jazz_concert(self):
        assert is_explicit_text("Swing Jazz Night at the Hall") is False

    def test_negative_analysis_word_boundary(self):
        assert is_explicit_text("Financial analysis workshop") is False

    def test_negative_kink_bare_word_not_flagged(self):
        # Bare "kink"/"kinky" dropped after false-positiving on a nonsexual
        # cuddle-party event whose host bio says "sex and kink coach" —
        # Layer-1 flags skip the LLM call entirely, so there's no backstop
        # for a Layer-1 false positive.
        assert is_explicit_text(
            "Cuddle party", "Hosted by a sex and kink coach. Nonsexual touch only."
        ) is False

    def test_negative_fetish_bare_word_not_flagged(self):
        # Bare "fetish"/"fetiš" dropped after false-positiving on a
        # dance-theater piece referencing the "fetish dance scene".
        assert is_explicit_text(
            "Flex", "The artist works in the club, fetish, and pole dance scene."
        ) is False

    def test_positive_multiword_phrase_across_literal_newline(self):
        # Multi-word keywords ("anal sex", "sissy play", ...) must still
        # match when the two words are split by a literal newline or run of
        # whitespace within a single text node, not just an HTML tag break.
        assert is_explicit_text("Workshop", "A night about anal\nsex and pleasure.") is True


class TestIsNonEventText:
    # Title keywords (gift cards / vouchers / donations / webinars)
    def test_estonian_gift_card_title(self):
        assert is_non_event_text("Kellerteater kinkekaart", "Kellerteater") is True

    def test_english_gift_card_title(self):
        assert is_non_event_text("PoCo gift card", "PoCo Museum") is True

    def test_russian_gift_ticket_title(self):
        assert is_non_event_text("Подарочный билет на экскурсию!", "Tallinn") is True

    def test_russian_webinar_title(self):
        assert is_non_event_text("Запись вебинара «Ожоги»", "Lastekohvik Domino") is True

    def test_webinar_english_title(self):
        assert is_non_event_text("Marketing webinar for founders", None) is True

    # Venue keywords (online-only listings)
    def test_mamaonline_venue(self):
        assert is_non_event_text("Как пережить болезни малыша?", "MamaOnline") is True

    def test_mamaonline_domain_venue(self):
        assert is_non_event_text("Онлайн-курс «Подготовка к родам»", "mamaonline.eu") is True

    def test_online_venue_with_url(self):
        assert is_non_event_text("Расслабляющий массаж", "Онлайн, https://example.eu") is True

    def test_plain_online_venue(self):
        assert is_non_event_text("Режим питания ребенка", "online") is True

    # Negatives
    def test_normal_concert_not_flagged(self):
        assert is_non_event_text("Techno night at Hall club", "Hall") is False

    def test_raamatute_title_not_flagged(self):
        # "raamat" is deliberately NOT a keyword — book-themed events are real events.
        assert is_non_event_text(
            "Pokudel külas: haridusprogramm Edgar Valteri raamatute ainetel",
            "Südalinna Teater",
        ) is False

    def test_annetuskontsert_compound_not_flagged(self):
        # Word boundary: "annetus" must not match inside a compound title.
        assert is_non_event_text("Annetuskontsert lastele", "Estonia") is False

    def test_in_person_koolitus_not_flagged(self):
        assert is_non_event_text(
            "Vaimse tervise esmaabi koolitus Tallinnas", "Peaasjad MTÜ"
        ) is False

    def test_gift_card_in_description_scope_note(self):
        # Only title/venue are scanned — the function takes no description arg,
        # so a "gift cards available" mention in a description can never flag.
        assert is_non_event_text("Jazz evening", "Philly Joe's") is False

    def test_none_inputs_not_flagged(self):
        assert is_non_event_text(None, None) is False


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
            ("10 EUR", (10.0, 10.0, "EUR", False)),
            ("From 28 EUR", (28.0, None, "EUR", False)),
            ("From 6 EUR, free", (6.0, None, "EUR", True)),
            ("40 EUR, free", (40.0, 40.0, "EUR", True)),
            ("Free", (0.0, 0.0, None, False)),
            (None, (None, None, None, False)),
            ("", (None, None, None, False)),
            ("From 9.50 EUR", (9.5, None, "EUR", False)),
            ("From 3,08 EUR", (3.08, None, "EUR", False)),  # comma decimal defensiveness
            ("From 20 CHF", (20.0, None, "CHF", False)),
            ("18 PLN", (18.0, 18.0, "PLN", False)),
            ("sold out", (None, None, None, False)),  # unparseable, not free
        ],
    )
    def test_grammar_table(self, value, expected):
        assert parse_price_from_string(value) == expected

    def test_currency_uppercased(self):
        assert parse_price_from_string("12 eur")[2] == "EUR"


class TestEurPriceBoundsFromText:
    def test_multi_tier_string(self):
        text = (
            "Adult: Kumu Art Museum €16, Family: Kumu Art Museum €32, "
            "Discount: Kumu Art Museum €11, Adult ticket with donation: "
            "Art Museum of Estonia €25"
        )
        assert eur_price_bounds_from_text(text) == (11.0, 32.0)

    @pytest.mark.parametrize(
        "text",
        ["€16", "16 €", "16€", "EUR 16", "16 EUR"],
    )
    def test_both_amount_orders_and_symbols(self, text):
        assert eur_price_bounds_from_text(text) == (16.0, 16.0)

    def test_european_decimal(self):
        assert eur_price_bounds_from_text("€12,50") == (12.5, 12.5)

    def test_no_currency_text_returns_none_tuple(self):
        assert eur_price_bounds_from_text("45 min") == (None, None)
        assert eur_price_bounds_from_text("1990s") == (None, None)

    @pytest.mark.parametrize(
        "text",
        ["16 European tour", "16EURO ticket charge"],
    )
    def test_eur_substring_false_positives_ignored(self, text):
        # "European"/"EURO" must not be mistaken for the EUR currency code
        # adjacent to an unrelated number.
        assert eur_price_bounds_from_text(text) == (None, None)

    def test_none_returns_none_tuple(self):
        assert eur_price_bounds_from_text(None) == (None, None)

    def test_empty_string_returns_none_tuple(self):
        assert eur_price_bounds_from_text("") == (None, None)


class TestEurAmountsFromText:
    def test_returns_all_amounts_with_duplicates(self):
        assert eur_amounts_from_text("€10, €10, €20") == [10.0, 10.0, 20.0]

    def test_none_returns_empty_list(self):
        assert eur_amounts_from_text(None) == []

    def test_no_currency_returns_empty_list(self):
        assert eur_amounts_from_text("45 minutes long") == []


class TestPriceContextDigest:
    def test_keeps_only_price_bearing_lines(self):
        html = (
            "<p>Welcome to the show.</p>"
            "<p>Full price €15<br>Discount €11</p>"
            "<p>Doors open at 19:00, no prices here.</p>"
        )
        digest = price_context_digest(html)
        assert "€15" in digest
        assert "€11" in digest
        assert "Welcome to the show" not in digest
        assert "Doors open" not in digest

    def test_combines_multiple_texts(self):
        digest = price_context_digest("<p>Adult €16</p>", "<p>Family €32</p>")
        assert "€16" in digest
        assert "€32" in digest

    def test_strips_fee_clauses(self):
        digest = price_context_digest("<p>agenditasu 3,20 €, Pilet 45 €</p>")
        assert "45" in digest
        assert "3,20" not in digest

    def test_empty_inputs_return_empty_string(self):
        assert price_context_digest(None, "") == ""

    def test_caps_at_price_context_max_chars(self):
        long_html = "<p>" + "".join(f"Tier {i} €{i}<br>" for i in range(200)) + "</p>"
        digest = price_context_digest(long_html)
        from app.constants import PRICE_CONTEXT_MAX_CHARS

        assert len(digest) <= PRICE_CONTEXT_MAX_CHARS

    def test_truncation_never_cuts_a_line_mid_amount(self):
        """The cap must drop whole trailing lines, never slice a kept line —
        otherwise a price literal like '€199' could survive as '€19'."""
        long_html = "<p>" + "".join(f"Tier {i} €{100 + i}<br>" for i in range(200)) + "</p>"
        digest = price_context_digest(long_html)
        for line in digest.splitlines():
            assert line == line.strip()
            # every kept line must end on a complete "€<digits>" amount, not a
            # truncated one (e.g. never ends in a bare digit run cut short of
            # the next expected digit).
            assert eur_amounts_from_text(line)


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
        assert extract_jsonld_event_offers(_soup(html)) == (15.0, 15.0, "EUR", False)

    def test_multiple_offers_min_max(self):
        html = _ld_script(
            '{"@type":"Event","offers":['
            '{"@type":"Offer","price":"28","priceCurrency":"EUR"},'
            '{"@type":"Offer","price":"75","priceCurrency":"EUR"}'
            "]}"
        )
        result = extract_jsonld_event_offers(_soup(html))
        assert result == (28.0, 75.0, "EUR", False)

    def test_free_tier_zero_price(self):
        """A €0 in-stock offer (e.g. Member/Companion) alongside a paid offer
        bounds price_min/max to the PAID amount and flags has_free_tier."""
        html = _ld_script(
            '{"@type":"Event","offers":['
            '{"@type":"Offer","price":"0","priceCurrency":"EUR",'
            '"availability":"http://schema.org/InStock"},'
            '{"@type":"Offer","price":"10","priceCurrency":"EUR",'
            '"availability":"http://schema.org/InStock"}'
            "]}"
        )
        assert extract_jsonld_event_offers(_soup(html)) == (10.0, 10.0, "EUR", True)

    def test_all_free_offers_no_paid(self):
        html = _ld_script(
            '{"@type":"Event","offers":['
            '{"@type":"Offer","price":"0","priceCurrency":"EUR",'
            '"availability":"http://schema.org/InStock"}'
            "]}"
        )
        assert extract_jsonld_event_offers(_soup(html)) == (0.0, 0.0, None, False)

    def test_sold_out_placeholder_ignored(self):
        """A sold-out event collapsed to a single {price: 0, availability:
        SoldOut} offer (Fienta's pattern) must not be read as a real free
        price — it should yield nothing usable."""
        html = _ld_script(
            '{"@type":"Event","offers":{"@type":"Offer","price":"0.00",'
            '"priceCurrency":"EUR","availability":"http://schema.org/SoldOut"}}'
        )
        assert extract_jsonld_event_offers(_soup(html)) == (None, None, None, False)

    def test_sold_out_placeholder_does_not_mask_paid_offer(self):
        html = _ld_script(
            '{"@type":"Event","offers":['
            '{"@type":"Offer","price":"0.00","priceCurrency":"EUR",'
            '"availability":"http://schema.org/SoldOut"},'
            '{"@type":"Offer","price":"17","priceCurrency":"EUR",'
            '"availability":"http://schema.org/InStock"}'
            "]}"
        )
        assert extract_jsonld_event_offers(_soup(html)) == (17.0, 17.0, "EUR", False)

    def test_no_offers_returns_none_tuple(self):
        html = _ld_script('{"@type":"Event"}')
        assert extract_jsonld_event_offers(_soup(html)) == (None, None, None, False)

    def test_no_event_returns_none_tuple(self):
        html = _ld_script('{"@type":"Organization"}')
        assert extract_jsonld_event_offers(_soup(html)) == (None, None, None, False)

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


class TestCoordsInTallinn:
    def test_tallinn_centre_inside(self):
        assert coords_in_tallinn(59.437, 24.753) is True

    def test_parnu_outside(self):
        assert coords_in_tallinn(58.38, 24.5) is False


def _http_status_error(status_code, headers=None):
    request = httpx.Request("GET", "https://example.com/x")
    response = httpx.Response(status_code, headers=headers or {}, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


class TestRetryAfterSeconds:
    def test_numeric_seconds(self):
        exc = _http_status_error(http.HTTPStatus.TOO_MANY_REQUESTS, {"Retry-After": "5"})
        assert retry_after_seconds(exc) == 5.0

    def test_http_date_form(self):
        future = time.time() + 10
        from email.utils import formatdate

        header = formatdate(future, usegmt=True)
        exc = _http_status_error(
            http.HTTPStatus.TOO_MANY_REQUESTS, {"Retry-After": header}
        )
        result = retry_after_seconds(exc)
        assert result is not None
        assert 8 <= result <= 11  # small tolerance for formatdate's 1s resolution

    def test_missing_header(self):
        exc = _http_status_error(http.HTTPStatus.TOO_MANY_REQUESTS)
        assert retry_after_seconds(exc) is None

    def test_non_429_status_returns_none(self):
        exc = _http_status_error(
            http.HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "5"}
        )
        assert retry_after_seconds(exc) is None

    def test_non_http_status_error_returns_none(self):
        assert retry_after_seconds(httpx.ConnectError("boom")) is None

    def test_capped_at_max_seconds(self):
        exc = _http_status_error(
            http.HTTPStatus.TOO_MANY_REQUESTS, {"Retry-After": "99999"}
        )
        assert retry_after_seconds(exc) == HTTP_RETRY_AFTER_MAX_SECONDS

    def test_unparseable_header_returns_none(self):
        exc = _http_status_error(
            http.HTTPStatus.TOO_MANY_REQUESTS, {"Retry-After": "garbage"}
        )
        assert retry_after_seconds(exc) is None


def _retry_state(exc, attempt_number=1):
    state = MagicMock(spec=RetryCallState)
    state.attempt_number = attempt_number
    state.outcome = MagicMock()
    state.outcome.failed = True
    state.outcome.exception.return_value = exc
    return state


class TestRetryWait:
    def test_429_with_retry_after_uses_header_value(self):
        exc = _http_status_error(http.HTTPStatus.TOO_MANY_REQUESTS, {"Retry-After": "7"})
        assert _retry_wait(_retry_state(exc)) == 7.0

    def test_non_429_falls_back_to_jittered_exponential(self):
        exc = _http_status_error(http.HTTPStatus.SERVICE_UNAVAILABLE)
        wait = _retry_wait(_retry_state(exc, attempt_number=1))
        # attempt 1 -> base exponential wait == HTTP_RETRY_WAIT_MIN (2), plus jitter [0, 1]
        assert 2.0 <= wait <= 3.0

    def test_429_without_retry_after_falls_back_to_exponential(self):
        exc = _http_status_error(http.HTTPStatus.TOO_MANY_REQUESTS)
        wait = _retry_wait(_retry_state(exc, attempt_number=1))
        assert 2.0 <= wait <= 3.0


class TestAsyncRateLimiter:
    @pytest.mark.asyncio
    async def test_spaces_acquisitions_by_interval(self):
        limiter = AsyncRateLimiter(0.05)
        start = time.monotonic()
        for _ in range(3):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.1  # 2 gaps of >= 0.05s between 3 acquisitions

    @pytest.mark.asyncio
    async def test_first_acquire_does_not_wait(self):
        limiter = AsyncRateLimiter(10.0)
        start = time.monotonic()
        await limiter.acquire()
        assert time.monotonic() - start < 0.1

    @pytest.mark.asyncio
    async def test_backoff_extends_next_acquire(self):
        limiter = AsyncRateLimiter(0.01)
        await limiter.acquire()
        limiter.backoff(0.1)
        start = time.monotonic()
        await limiter.acquire()
        assert time.monotonic() - start >= 0.08

    @pytest.mark.asyncio
    async def test_backoff_does_not_shorten_existing_wait(self):
        limiter = AsyncRateLimiter(0.2)
        await limiter.acquire()
        limiter.backoff(0.001)  # shorter than the existing min-interval gap
        start = time.monotonic()
        await limiter.acquire()
        assert time.monotonic() - start >= 0.15

    def test_boston_outside(self):
        assert coords_in_tallinn(42.36, -71.06) is False


class _FakeAdapter(SourceAdapter):
    """Minimal SourceAdapter for exercising run()'s control flow in isolation."""

    def __init__(self, source, fetch_result=None, fetch_exc=None):
        super().__init__(source)
        self._fetch_result = fetch_result if fetch_result is not None else []
        self._fetch_exc = fetch_exc
        self.fetch_raw_called_with: set[str] | None = None
        self.fetch_raw_call_order: int | None = None

    async def fetch_raw(self, known_ids):
        self.fetch_raw_called_with = known_ids
        if self._fetch_exc is not None:
            raise self._fetch_exc
        return self._fetch_result

    def normalize(self, raw):
        return None


class TestSourceAdapterRun:
    """run() must release the connection (commit, not rollback — see base.py
    comment) before fetch_raw()'s crawl and only touch the DB again afterward."""

    @pytest.mark.asyncio
    async def test_known_ids_passed_and_connection_released_before_crawl(self, mock_db):
        source = MagicMock(id=1)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=["known-1"]))
        adapter = _FakeAdapter(source, fetch_result=[{"id": "x"}])

        run = await adapter.run(mock_db)

        assert adapter.fetch_raw_called_with == {"known-1"}
        mock_db.commit.assert_awaited_once()
        mock_db.rollback.assert_not_awaited()
        assert run.raw_count == 1
        assert run.error is None

    @pytest.mark.asyncio
    async def test_recently_rejected_raw_event_id_is_skipped(self, mock_db):
        """A raw_events row fetched within INGEST_REJECT_RECHECK_DAYS with no
        event_sources row (a recent reject) still ends up in known_ids."""
        source = MagicMock(id=1)
        mock_db.scalars.side_effect = [
            MagicMock(all=MagicMock(return_value=[])),  # existing_external_ids
            MagicMock(all=MagicMock(return_value=["rejected-1"])),  # recent raw_events
        ]
        adapter = _FakeAdapter(source, fetch_result=[])

        await adapter.run(mock_db)

        assert adapter.fetch_raw_called_with == {"rejected-1"}

    @pytest.mark.asyncio
    async def test_stale_rejected_raw_event_id_is_not_skipped(self, mock_db):
        """A raw_events row older than INGEST_REJECT_RECHECK_DAYS is outside the
        recheck window, so it's eligible for re-fetch (not in known_ids)."""
        source = MagicMock(id=1)
        mock_db.scalars.side_effect = [
            MagicMock(all=MagicMock(return_value=[])),  # existing_external_ids
            MagicMock(all=MagicMock(return_value=[])),  # recent raw_events filter excludes it
        ]
        adapter = _FakeAdapter(source, fetch_result=[])

        await adapter.run(mock_db)

        assert adapter.fetch_raw_called_with == set()

    @pytest.mark.asyncio
    async def test_run_row_inserted_after_fetch_raw_with_started_at_set(self, mock_db):
        source = MagicMock(id=1)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        adapter = _FakeAdapter(source, fetch_result=[])

        run = await adapter.run(mock_db)

        # started_at must be stamped explicitly (pre-crawl), not left to the
        # server_default — by the time db.add(run) fires, fetch_raw already ran.
        assert run.started_at is not None

    @pytest.mark.asyncio
    async def test_fetch_raw_failure_before_persist_still_records_run_error(self, mock_db):
        source = MagicMock(id=1)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        adapter = _FakeAdapter(source, fetch_exc=RuntimeError("crawl exploded"))

        with pytest.raises(RuntimeError, match="crawl exploded"):
            await adapter.run(mock_db)

        added_runs = [c.args[0] for c in mock_db.add.call_args_list]
        assert len(added_runs) == 1
        assert added_runs[0].error == "crawl exploded"
        assert source.last_status == "error"


class _NormalizingFakeAdapter(SourceAdapter):
    """SourceAdapter whose normalize() returns a real NormalizedEvent, so run()'s
    known-external-id skip branch (base.py ~:976-985) is actually exercised — unlike
    _FakeAdapter above, whose normalize() always returns None and short-circuits
    before that branch."""

    def __init__(self, source, fetch_result, normalized_external_id):
        super().__init__(source)
        self._fetch_result = fetch_result
        self._normalized_external_id = normalized_external_id

    async def fetch_raw(self, known_ids):
        return self._fetch_result

    def normalize(self, raw):
        return NormalizedEvent(
            external_id=self._normalized_external_id,
            title="Test Event",
            starts_at=datetime(2026, 6, 1, 18, 0, tzinfo=TALLINN_TZ),
        )


class TestSourceAdapterRunKnownIdSkip:
    """P1-2 fix: a raw item whose external_id is already in known_ids must be skipped
    via an in-memory check, never a per-item SELECT EventSource — see base.py's
    known_ids in-memory check, which replaced a query previously issued once per raw
    item (N+1 on a large crawl)."""

    @pytest.mark.asyncio
    async def test_known_external_id_skipped_without_a_db_query(self, mock_db):
        source = MagicMock(id=1, slug="test-source")
        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=["dup-1"])
        )  # known_ids will contain "dup-1"
        adapter = _NormalizingFakeAdapter(
            source, fetch_result=[{"id": "dup-1"}], normalized_external_id="dup-1"
        )

        run = await adapter.run(mock_db)

        # The whole point of the fix: zero SELECTs issued for the skipped item.
        mock_db.scalar.assert_not_awaited()
        # Still marked processed and not counted as new, matching pre-fix behavior.
        added_raw_events = [
            c.args[0] for c in mock_db.add.call_args_list if hasattr(c.args[0], "processed_at")
        ]
        assert len(added_raw_events) == 1
        assert added_raw_events[0].processed_at is not None
        assert run.new_count in (0, None)

    @pytest.mark.asyncio
    async def test_unknown_external_id_not_skipped(self, mock_db):
        """Sanity check the fixture actually distinguishes the two cases: an
        external_id NOT in known_ids proceeds past the skip branch (no false-skip) —
        still with zero per-item SELECTs (the fix removed the query entirely, not just
        for the skip case)."""
        source = MagicMock(id=1, slug="test-source")
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        nested_cm = MagicMock()
        nested_cm.__aenter__ = AsyncMock(return_value=None)
        nested_cm.__aexit__ = AsyncMock(return_value=False)
        mock_db.begin_nested = MagicMock(return_value=nested_cm)
        adapter = _NormalizingFakeAdapter(
            source, fetch_result=[{"id": "new-1"}], normalized_external_id="new-1"
        )

        await adapter.run(mock_db)

        raw_events = [
            c.args[0] for c in mock_db.add.call_args_list if hasattr(c.args[0], "processed_at")
        ]
        assert len(raw_events) == 1
        # processed_at set by the post-insert path (line ~1063), not by the skip
        # branch — but either way, never via a per-item SELECT.
        assert raw_events[0].processed_at is not None
        assert mock_db.scalar.await_count == 0  # still never queries the DB per-item


class TestNormalizedEventAddressGate:
    """Coords without an address are orphan data — see base.py:__post_init__."""

    def test_coords_dropped_when_no_address(self):
        event = NormalizedEvent(
            external_id="x",
            title="Test",
            starts_at=datetime.now(TALLINN_TZ),
            venue_address=None,
            lat=59.43,
            lng=24.75,
        )
        assert event.lat is None
        assert event.lng is None

    def test_coords_preserved_when_address_present(self):
        event = NormalizedEvent(
            external_id="x",
            title="Test",
            starts_at=datetime.now(TALLINN_TZ),
            venue_address="Telliskivi 60a, 10412 Tallinn, Harjumaa",
            lat=59.43,
            lng=24.75,
        )
        assert event.lat == 59.43
        assert event.lng == 24.75


class TestInsertNormalizedEvent:
    """insert_normalized_event() is the shared write path extracted from
    SourceAdapter._insert_event (P1 organizer-submission refactor) — used by
    every scraper adapter *and* the organizer direct-submission router, which
    has no adapter/normalize() step of its own."""

    def _nested_cm(self, mock_db):
        nested_cm = MagicMock()
        nested_cm.__aenter__ = AsyncMock(return_value=None)
        nested_cm.__aexit__ = AsyncMock(return_value=False)
        mock_db.begin_nested = MagicMock(return_value=nested_cm)
        return nested_cm

    @pytest.mark.asyncio
    async def test_returns_event_on_success(self, mock_db):
        self._nested_cm(mock_db)
        source = MagicMock(id=1, slug="test-source")
        normalized = NormalizedEvent(
            external_id="ext-1",
            title="Test Event",
            starts_at=datetime(2026, 6, 1, 18, 0, tzinfo=TALLINN_TZ),
        )

        result = await insert_normalized_event(mock_db, source, normalized)

        assert result is not None
        assert result.title_orig == "Test Event"
        mock_db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_returns_none_on_slug_collision(self, mock_db):
        from sqlalchemy.exc import IntegrityError

        self._nested_cm(mock_db)
        mock_db.flush.side_effect = IntegrityError("stmt", {}, Exception("dup key"))
        source = MagicMock(id=1, slug="test-source")
        normalized = NormalizedEvent(
            external_id="ext-1",
            title="Test Event",
            starts_at=datetime(2026, 6, 1, 18, 0, tzinfo=TALLINN_TZ),
        )

        result = await insert_normalized_event(mock_db, source, normalized)

        assert result is None

    @pytest.mark.asyncio
    async def test_source_adapter_insert_event_delegates(self, mock_db):
        """SourceAdapter._insert_event now delegates to insert_normalized_event
        bound to self.source, preserving the pre-refactor call site's behavior."""
        self._nested_cm(mock_db)
        source = MagicMock(id=1, slug="test-source")

        class _FakeAdapterForInsert(SourceAdapter):
            async def fetch_raw(self, known_ids):
                return []

            def normalize(self, raw):
                return None

        adapter = _FakeAdapterForInsert(source)
        normalized = NormalizedEvent(
            external_id="ext-2",
            title="Delegate Test",
            starts_at=datetime(2026, 6, 1, 18, 0, tzinfo=TALLINN_TZ),
        )

        result = await adapter._insert_event(mock_db, normalized)

        assert result is not None
        assert result.title_orig == "Delegate Test"

    @pytest.mark.asyncio
    async def test_user_submission_kind_keeps_arbitrary_host_url(self, mock_db):
        """A user_submission source's url is never server-fetched (refetch.py
        excludes organizer submissions), so it only needs the scheme-only
        safe_external_url check — an off-allowlist host is kept."""
        self._nested_cm(mock_db)
        source = MagicMock(id=1, slug="user_submission", kind=SOURCE_KIND_USER_SUBMISSION)
        normalized = NormalizedEvent(
            external_id="ext-3",
            title="Organizer Event",
            starts_at=datetime(2026, 6, 1, 18, 0, tzinfo=TALLINN_TZ),
            url="https://mytheatre.ee/tickets/42",
        )

        result = await insert_normalized_event(mock_db, source, normalized)

        assert result is not None
        assert result.url == "https://mytheatre.ee/tickets/42"

    @pytest.mark.asyncio
    async def test_adapter_kind_drops_arbitrary_host_url(self, mock_db):
        """An adapter-kind source keeps the host-pinned safe_fetchable_url
        guard: the same off-allowlist host that a user_submission source
        keeps is dropped to None here."""
        self._nested_cm(mock_db)
        source = MagicMock(id=1, slug="test-source", kind=SOURCE_KIND_API)
        normalized = NormalizedEvent(
            external_id="ext-4",
            title="Scraped Event",
            starts_at=datetime(2026, 6, 1, 18, 0, tzinfo=TALLINN_TZ),
            url="https://mytheatre.ee/tickets/42",
        )

        result = await insert_normalized_event(mock_db, source, normalized)

        assert result is not None
        assert result.url is None


class TestStripFeeAmounts:
    def test_event_1501_agent_fee_stripped_real_price_survives(self):
        # "agenditasu 3,20 € Pilet 45 €" — fee 3.20 stripped, real 45 survives.
        text = "Nominaalhinnale lisandub agenditasu 3,20 € Pilet 45 €"
        result = strip_fee_amounts(text)
        assert result is not None
        assert "45" in result
        assert "3,20" not in result

    def test_event_1551_service_fee_only_stripped(self):
        # "teenustasu 1.40€/ pilet" — fee-only string, 1.40 stripped.
        text = "hinnad sisaldavad teenustasu 1.40€/ pilet"
        result = strip_fee_amounts(text)
        assert result is not None
        assert "1.40" not in result

    def test_no_keyword_noop(self):
        text = "Täispilet 18 €, Õpilane 12 €"
        assert strip_fee_amounts(text) == text

    def test_none_returns_none(self):
        assert strip_fee_amounts(None) is None

    def test_empty_string_returns_empty(self):
        assert strip_fee_amounts("") == ""

    def test_english_service_fee_stripped(self):
        text = "Price includes service fee 2.50 EUR. Ticket 20 EUR."
        result = strip_fee_amounts(text)
        assert result is not None
        assert "2.50" not in result
        assert "20" in result

    def test_english_booking_fee_stripped(self):
        text = "booking fee 1.99€ applies. Entry 15 €."
        result = strip_fee_amounts(text)
        assert result is not None
        assert "1.99" not in result
        assert "15" in result

    def test_comma_decimal_stripped(self):
        text = "agenditasu 3,20 € pilet"
        result = strip_fee_amounts(text)
        assert result is not None
        assert "3,20" not in result

    def test_dot_decimal_stripped(self):
        text = "teenustasu 1.40€"
        result = strip_fee_amounts(text)
        assert result is not None
        assert "1.40" not in result

    def test_eur_suffix_stripped(self):
        text = "käsitlustasu 2 EUR pilet 30 EUR"
        result = strip_fee_amounts(text)
        assert result is not None
        assert "2 EUR" not in result
        assert "30 EUR" in result
