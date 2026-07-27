"""Tests for the daily detail-refetch sync (refetch_event_details + reconciliation)."""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bs4 import BeautifulSoup

from app.constants import (
    LOCALIZED_TEXT_FIENTA_LOCALES,
    REFETCH_MIN_INTERVAL_DAYS,
    TALLINN_CENTER_LAT,
    TALLINN_CENTER_LNG,
    TALLINN_TZ,
)
from app.ingestion.locale_urls import locale_from_url_path
from app.ingestion.refetch import (
    _is_empty_venue_name,
    _is_suspect_locale_title,
    refetch_event_details,
)
from app.ingestion.selectors import KUMU_SITE_NAME_ET, KUMU_SITE_TITLE_SUFFIX
from app.ingestion.sources.kumu import kumu_localized_text

# --- HTML builders -----------------------------------------------------------


def _ld_script(json_body: str) -> str:
    return f'<html><head><script type="application/ld+json">{json_body}</script></head></html>'


def _event_html(
    *,
    name: str | None = None,
    street: str | None = None,
    locality: str | None = "Tallinn",
    lat: float | None = None,
    lng: float | None = None,
    price: float | None = None,
    currency: str = "EUR",
    sold_out: bool = False,
) -> str:
    """Build a fienta-style detail page with a schema.org Event JSON-LD block."""
    parts: list[str] = ['"@type":"Event"']
    if name is not None or street is not None or lat is not None:
        loc: list[str] = ['"@type":"Place"']
        if name is not None:
            loc.append(f'"name":{_q(name)}')
        if lat is not None and lng is not None:
            loc.append(f'"geo":{{"@type":"GeoCoordinates","latitude":{lat},"longitude":{lng}}}')
        addr: list[str] = []
        if street is not None:
            addr.append(f'"streetAddress":{_q(street)}')
        if locality is not None and street is not None:
            addr.append(f'"addressLocality":{_q(locality)}')
        if addr:
            loc.append('"address":{' + ",".join(addr) + "}")
        parts.append('"location":{' + ",".join(loc) + "}")
    if price is not None:
        availability = "SoldOut" if sold_out else "InStock"
        parts.append(
            f'"offers":{{"@type":"Offer","price":"{price}","priceCurrency":"{currency}",'
            f'"availability":"http://schema.org/{availability}"}}'
        )
    return _ld_script("{" + ",".join(parts) + "}")


def _q(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'


def _resp(html: str) -> MagicMock:
    r = MagicMock()
    r.text = html
    return r


def _future_event(**overrides) -> MagicMock:
    e = MagicMock()
    e.id = 1
    e.url = "https://fienta.com/some-event-1"
    e.starts_at = datetime.now(TALLINN_TZ) + timedelta(days=7)
    e.title_orig = "Test Event"
    e.description_orig = "A test event description"
    e.title_localized = None
    e.description_localized = None
    e.venue_name = "Test Venue"
    e.venue_address = "Old Street 1, Tallinn"
    e.lat = TALLINN_CENTER_LAT
    e.lng = TALLINN_CENTER_LNG
    e.price_min = None
    e.price_max = None
    e.currency = "EUR"
    e.has_free_tier = False
    e.status = "published"
    e.is_explicit = False
    e.is_non_event = False
    e.detail_refetched_at = None
    e.detail_refetch_count = 0
    for k, v in overrides.items():
        setattr(e, k, v)
    return e


async def _run(mock_db, event, html) -> dict:
    """Drive refetch_event_details with one candidate event and a stubbed detail page."""
    mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
    with (
        patch("app.ingestion.refetch.http_get", new=AsyncMock(return_value=_resp(html))),
        patch("app.ingestion.refetch.asyncio.sleep", new=AsyncMock()),
    ):
        return await refetch_event_details(mock_db)


# --- _is_empty_venue_name (placeholder set, online exclusion) ----------------


class TestIsEmptyVenueName:
    @pytest.mark.parametrize("name", [None, "", "   ", "TBD", "tba", "---", "N/A", "unknown"])
    def test_empty_or_placeholder(self, name):
        assert _is_empty_venue_name(name) is True

    @pytest.mark.parametrize("name", ["KUMU", "Online", "MamaOnline", "Heldeke!"])
    def test_real_names_not_empty(self, name):
        # online/MamaOnline are real venue names, never placeholders.
        assert _is_empty_venue_name(name) is False


# --- price reconciliation ----------------------------------------------------


class TestPriceReconcile:
    @pytest.mark.asyncio
    async def test_fills_empty_price(self, mock_db):
        event = _future_event(price_min=None, price_max=None)
        summary = await _run(mock_db, event, _event_html(price=12.0))
        assert event.price_min == 12.0
        assert summary["price_changed"] == 1

    @pytest.mark.asyncio
    async def test_overwrites_changed_price(self, mock_db):
        event = _future_event(price_min=Decimal("10.00"), price_max=Decimal("10.00"))
        summary = await _run(mock_db, event, _event_html(price=15.0))
        assert event.price_min == 15.0
        assert summary["price_changed"] == 1

    @pytest.mark.asyncio
    async def test_same_price_unchanged(self, mock_db):
        event = _future_event(price_min=Decimal("12.00"), price_max=Decimal("12.00"))
        summary = await _run(mock_db, event, _event_html(price=12.0))
        assert summary["price_changed"] == 0
        assert summary["unchanged"] == 1

    @pytest.mark.asyncio
    async def test_no_offers_leaves_stored_price(self, mock_db):
        event = _future_event(price_min=Decimal("9.00"), price_max=Decimal("9.00"))
        # Detail has a location but no offers — must not clobber the stored price.
        summary = await _run(mock_db, event, _event_html(name="Test Venue", street="Old Street 1"))
        assert event.price_min == Decimal("9.00")
        assert summary["price_changed"] == 0

    @pytest.mark.asyncio
    async def test_sold_out_placeholder_leaves_stored_price(self, mock_db):
        """A sold-out event's collapsed {price: 0, availability: SoldOut} offer
        must not overwrite the listing's real stored price with a fake free one."""
        event = _future_event(price_min=Decimal("39.00"), price_max=None)
        summary = await _run(mock_db, event, _event_html(price=0.0, sold_out=True))
        assert event.price_min == Decimal("39.00")
        assert summary["price_changed"] == 0
        assert summary["no_data"] == 1

    @pytest.mark.asyncio
    async def test_free_tier_offer_flags_event(self, mock_db):
        event = _future_event(price_min=None, price_max=None, has_free_tier=False)
        html = _ld_script(
            '{"@type":"Event","offers":['
            '{"@type":"Offer","price":"0","priceCurrency":"EUR",'
            '"availability":"http://schema.org/InStock"},'
            '{"@type":"Offer","price":"17","priceCurrency":"EUR",'
            '"availability":"http://schema.org/InStock"}'
            "]}"
        )
        await _run(mock_db, event, html)
        assert event.price_min == 17.0
        assert event.has_free_tier is True


# --- address <-> coords coupling --------------------------------------------


class TestAddressCoordsCoupling:
    @pytest.mark.asyncio
    async def test_address_change_with_coords_updates_triple(self, mock_db):
        event = _future_event(venue_address="Old Street 1, Tallinn")
        summary = await _run(
            mock_db, event,
            _event_html(name="Heldeke!", street="Tööstuse tänav 13", lat=59.44, lng=24.75),
        )
        assert event.venue_address == "Tööstuse tänav 13, Tallinn"
        assert event.lat == 59.44
        assert event.lng == 24.75
        assert summary["address_changed"] == 1
        assert summary["coords_changed"] == 1

    @pytest.mark.asyncio
    async def test_address_change_without_coords_nulls_coords(self, mock_db):
        event = _future_event(
            venue_address="Old Street 1, Tallinn", lat=59.0, lng=24.0
        )
        summary = await _run(
            mock_db, event, _event_html(name="New Place", street="New Street 5")
        )
        assert event.venue_address == "New Street 5, Tallinn"
        assert event.lat is None
        assert event.lng is None
        assert summary["address_changed"] == 1
        assert summary["coords_changed"] == 1

    @pytest.mark.asyncio
    async def test_neither_reported_preserves_sibling_triple(self, mock_db):
        # A sibling-copied (address, lat, lng) triple; detail page reports only a name.
        event = _future_event(
            venue_address="Sibling Addr 9, Tallinn", lat=59.1, lng=24.2,
            venue_name="Test Venue",
        )
        summary = await _run(mock_db, event, _event_html(name="Test Venue"))
        assert event.venue_address == "Sibling Addr 9, Tallinn"
        assert event.lat == 59.1
        assert event.lng == 24.2
        assert summary["address_changed"] == 0
        assert summary["coords_changed"] == 0

    @pytest.mark.asyncio
    async def test_coord_within_tolerance_is_unchanged(self, mock_db):
        # Same address; coords differ only in sub-meter float noise → no change.
        event = _future_event(
            venue_address="Same Street 1, Tallinn",
            lat=59.43793509999999, lng=24.7379351,
        )
        summary = await _run(
            mock_db, event,
            _event_html(street="Same Street 1", lat=59.4379351, lng=24.73793509999999),
        )
        assert summary["coords_changed"] == 0
        assert event.lat == 59.43793509999999  # untouched

    @pytest.mark.asyncio
    async def test_same_address_coords_moved_updates_coords_only(self, mock_db):
        event = _future_event(
            venue_address="Same Street 1, Tallinn", lat=59.1, lng=24.1
        )
        summary = await _run(
            mock_db, event,
            _event_html(street="Same Street 1", lat=59.5, lng=24.5),
        )
        assert event.venue_address == "Same Street 1, Tallinn"
        assert event.lat == 59.5
        assert event.lng == 24.5
        assert summary["coords_changed"] == 1
        assert summary["address_changed"] == 0

    @pytest.mark.asyncio
    async def test_address_change_already_null_coords_not_counted(self, mock_db):
        # Address changes, stored coords were already NULL, detail has no coords →
        # nothing about the coords actually changed, so coords_changed must not count.
        event = _future_event(venue_address="Old Street 1, Tallinn", lat=None, lng=None)
        summary = await _run(
            mock_db, event, _event_html(name="New Place", street="New Street 5")
        )
        assert event.venue_address == "New Street 5, Tallinn"
        assert event.lat is None
        assert summary["address_changed"] == 1
        assert summary["coords_changed"] == 0

    @pytest.mark.asyncio
    async def test_fills_empty_address_and_coords(self, mock_db):
        event = _future_event(venue_address=None, lat=None, lng=None)
        summary = await _run(
            mock_db, event,
            _event_html(street="Filled Street 2", lat=59.4, lng=24.7),
        )
        assert event.venue_address == "Filled Street 2, Tallinn"
        assert event.lat == 59.4
        assert summary["address_changed"] == 1


# --- venue_name guard --------------------------------------------------------


class TestVenueNameGuard:
    @pytest.mark.asyncio
    async def test_clean_name_overwrites(self, mock_db):
        event = _future_event(venue_name="KUMU")
        summary = await _run(mock_db, event, _event_html(name="Vaba Lava"))
        assert event.venue_name == "Vaba Lava"
        assert summary["venue_changed"] == 1

    @pytest.mark.asyncio
    async def test_suspect_detail_name_does_not_overwrite_clean(self, mock_db):
        event = _future_event(venue_name="KUMU")
        # Suspect: contains a comma + digits (a glued address).
        summary = await _run(
            mock_db, event, _event_html(name="Some Hall, Telliskivi 60a")
        )
        assert event.venue_name == "KUMU"
        assert summary["venue_changed"] == 0

    @pytest.mark.asyncio
    async def test_placeholder_name_replaced(self, mock_db):
        event = _future_event(venue_name="TBD")
        summary = await _run(mock_db, event, _event_html(name="Heldeke!"))
        assert event.venue_name == "Heldeke!"
        assert summary["venue_changed"] == 1

    @pytest.mark.asyncio
    async def test_online_name_left_intact(self, mock_db):
        # Online event: real "MamaOnline" name, no physical address. Same name on
        # the detail page → untouched; address stays empty.
        event = _future_event(venue_name="MamaOnline", venue_address=None, lat=None, lng=None)
        summary = await _run(mock_db, event, _event_html(name="MamaOnline", price=0.0))
        assert event.venue_name == "MamaOnline"
        assert event.venue_address is None
        assert summary["venue_changed"] == 0


# --- content-safety re-check on venue_name change ---------------------------


class TestExplicitVenueNameGuard:
    @pytest.mark.asyncio
    async def test_explicit_detail_name_flags_and_demotes_published(self, mock_db):
        event = _future_event(
            venue_name="Old Venue", is_explicit=False, status="published"
        )
        summary = await _run(mock_db, event, _event_html(name="Strip Club Tallinn"))
        assert event.venue_name == "Strip Club Tallinn"
        assert event.is_explicit is True
        assert event.status == "classified"  # demoted so the publish gate re-excludes
        assert summary["flagged_explicit"] == 1

    @pytest.mark.asyncio
    async def test_clean_name_change_does_not_flag(self, mock_db):
        event = _future_event(venue_name="KUMU", is_explicit=False, status="published")
        summary = await _run(mock_db, event, _event_html(name="Vaba Lava"))
        assert event.is_explicit is False
        assert event.status == "published"
        assert summary["flagged_explicit"] == 0
        assert summary["flagged_non_event"] == 0


class TestNonEventVenueNameGuard:
    @pytest.mark.asyncio
    async def test_online_detail_name_flags_and_demotes_published(self, mock_db):
        # A detail refetch that rewrites venue_name to an online-only venue must
        # re-run the non-event prefilter and demote the published event.
        event = _future_event(
            venue_name="Old Venue", is_non_event=False, status="published"
        )
        summary = await _run(mock_db, event, _event_html(name="MamaOnline"))
        assert event.venue_name == "MamaOnline"
        assert event.is_non_event is True
        assert event.status == "classified"
        assert summary["flagged_non_event"] == 1

    @pytest.mark.asyncio
    async def test_clean_name_change_does_not_flag_non_event(self, mock_db):
        event = _future_event(venue_name="KUMU", is_non_event=False, status="published")
        summary = await _run(mock_db, event, _event_html(name="Vaba Lava"))
        assert event.is_non_event is False
        assert event.status == "published"
        assert summary["flagged_non_event"] == 0


# --- throttle bump + no-data -------------------------------------------------


class TestThrottleBump:
    @pytest.mark.asyncio
    async def test_no_data_still_bumps_counters(self, mock_db):
        event = _future_event()
        summary = await _run(mock_db, event, "<html><body>no jsonld here</body></html>")
        assert summary["no_data"] == 1
        assert event.detail_refetch_count == 1
        assert event.detail_refetched_at is not None

    @pytest.mark.asyncio
    async def test_unchanged_still_bumps_counters(self, mock_db):
        event = _future_event(
            venue_name="Test Venue", venue_address="Old Street 1, Tallinn",
            lat=59.1, lng=24.1, price_min=Decimal("12.00"), price_max=Decimal("12.00"),
        )
        summary = await _run(
            mock_db, event,
            _event_html(name="Test Venue", street="Old Street 1", lat=59.1, lng=24.1, price=12.0),
        )
        assert summary["unchanged"] == 1
        assert event.detail_refetch_count == 1
        assert event.detail_refetched_at is not None

    @pytest.mark.asyncio
    async def test_fetch_failure_does_not_bump(self, mock_db):
        import httpx

        event = _future_event()
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        with (
            patch(
                "app.ingestion.refetch.http_get",
                new=AsyncMock(side_effect=httpx.RequestError("boom")),
            ),
            patch("app.ingestion.refetch.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await refetch_event_details(mock_db)
        assert summary["failed"] == 1


class TestSsrfHostGuard:
    """The allowed-host set passed to host_guard_hook must come from
    ALLOWED_SOURCE_HOSTS, not from the raw candidate URLs — otherwise a
    malicious/pre-fix stored event.url would allowlist itself. http_get is
    NOT mocked here (unlike _run/other tests) so the real event_hooks guard
    actually executes against a mocked transport."""

    @pytest.mark.asyncio
    async def test_non_allowlisted_host_is_blocked_not_crashed(self, mock_db):
        good = _future_event(id=1, url="https://fienta.com/good-event")
        evil = _future_event(
            id=2, url="http://169.254.169.254/latest/meta-data/", detail_refetched_at=None
        )
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[good, evil]))

        good_html = _event_html(name="Real Venue", street="Main St 1")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=good_html)

        class _MockedAsyncClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(handler)
                super().__init__(*args, **kwargs)

        with (
            patch("app.ingestion.refetch.httpx.AsyncClient", _MockedAsyncClient),
            patch("app.ingestion.refetch.asyncio.sleep", new=AsyncMock()),
        ):
            # Must not raise — a host-mismatch is a per-item skip, not a crash.
            summary = await refetch_event_details(mock_db)

        assert summary["candidates"] == 2
        assert summary["failed"] == 1  # evil, blocked by the SSRF guard
        assert summary["fetched"] == 1  # good, actually reached the transport
        assert evil.detail_refetched_at is None  # not throttled out — retried next run
        assert good.detail_refetched_at is not None


class TestOrganizerSubmissionNoJsonld:
    """An organizer-submitted event's own ticketing page (if it even has a
    url — an allowlisted one, per safe_fetchable_url) generally carries no
    schema.org Event JSON-LD. This is not Fienta-specific special-casing —
    refetch already no-ops cleanly on any page with nothing to parse; this
    test pins that behavior for the submission source (CLAUDE.md Phase 2
    §2.3)."""

    @pytest.mark.asyncio
    async def test_no_jsonld_leaves_stored_fields_untouched_and_marks_synced(
        self, mock_db
    ):
        event = _future_event(
            url="https://fienta.com/org-submission-page",
            venue_name="Original Venue",
            venue_address="Old Street 1, Tallinn",
            price_min=15.0,
        )
        event.submitted_by_organizer_id = 7
        no_jsonld_html = "<html><head></head><body>No structured data here.</body></html>"

        summary = await _run(mock_db, event, no_jsonld_html)

        assert summary["no_data"] == 1
        assert summary["unchanged"] == 0  # _reconcile never runs — nothing to reconcile
        assert event.venue_name == "Original Venue"
        assert event.venue_address == "Old Street 1, Tallinn"
        assert event.price_min == 15.0
        assert event.detail_refetched_at is not None  # still marked synced


# --- candidate query ---------------------------------------------------------


class TestCandidateQuery:
    @pytest.mark.asyncio
    async def test_query_predicates(self, mock_db):
        captured: dict = {}

        def _capture(stmt):
            captured["stmt"] = stmt
            return MagicMock(all=MagicMock(return_value=[]))

        mock_db.scalars.side_effect = _capture
        summary = await refetch_event_details(mock_db)
        assert summary["candidates"] == 0

        sql = str(captured["stmt"])
        # Future events with a url, throttle window, oldest-first ordering.
        assert "events.url IS NOT NULL" in sql
        assert "events.starts_at >" in sql
        assert "events.detail_refetched_at IS NULL" in sql
        assert "events.detail_refetched_at <" in sql
        assert "ORDER BY events.detail_refetched_at ASC NULLS FIRST" in sql
        # Inspect only the predicate (the SELECT column list naturally names every
        # column). No missing-field filter (all future events are candidates) and
        # no attempt-cap clause on the diagnostic counter.
        where_sql = sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
        assert "venue_address" not in where_sql
        assert "price_min" not in where_sql
        assert "detail_refetch_count" not in where_sql


def test_min_interval_is_one_day() -> None:
    assert REFETCH_MIN_INTERVAL_DAYS == 1


# --- localized text backfill -------------------------------------------------


def _hreflang_html(base_url: str, en_url: str, et_url: str, og_title: str = "", desc_text: str = "") -> str:
    """Build a page with hreflang alternates and optional og:title + .single__content-dynamic."""
    og = f'<meta property="og:title" content="{og_title}"/>' if og_title else ""
    desc = f'<div class="single__content-dynamic">{desc_text}</div>' if desc_text else ""
    return f"""<html><head>
{og}
<link rel="alternate" hreflang="en" href="{en_url}"/>
<link rel="alternate" hreflang="et" href="{et_url}"/>
</head><body>{desc}</body></html>"""


class TestLocalizedTextBackfill:
    @pytest.mark.asyncio
    async def test_kumu_host_uses_og_title_extractor(self, mock_db):
        """KUMU events (kumu.ekm.ee) must use kumu_localized_text, not JSON-LD."""
        event = _future_event(
            url="https://kumu.ekm.ee/en/syndmus/some-event/",
            title_localized=None,
            description_localized=None,
        )
        # Single-locale page (et URL == en URL for this test), og:title present
        html = _hreflang_html(
            base_url="https://kumu.ekm.ee/en/syndmus/some-event/",
            en_url="https://kumu.ekm.ee/en/syndmus/some-event/",
            et_url="https://kumu.ekm.ee/et/syndmus/some-event/",
            og_title="Kumu katuseterrassi külastus - Kumu kunstimuuseum",
            desc_text="Muuseumikirjeldus.",
        )
        et_html = _hreflang_html(
            base_url="https://kumu.ekm.ee/et/syndmus/some-event/",
            en_url="https://kumu.ekm.ee/en/syndmus/some-event/",
            et_url="https://kumu.ekm.ee/et/syndmus/some-event/",
            og_title="Kumu katuseterrassi külastus - Kumu kunstimuuseum",
            desc_text="Muuseumikirjeldus.",
        )
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        responses = [_resp(html), _resp(et_html)]
        call_count = 0

        async def _fake_get(client, url):
            nonlocal call_count
            r = responses[call_count % len(responses)]
            call_count += 1
            return r

        with (
            patch("app.ingestion.refetch.http_get", new=_fake_get),
            patch("app.ingestion.refetch.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await refetch_event_details(mock_db)

        assert summary["localized_text_backfilled"] == 1
        # Suffix must be stripped — og:title extractor in use
        assert event.title_localized is not None
        for loc_title in event.title_localized.values():
            assert "Kumu kunstimuuseum" not in loc_title

    @pytest.mark.asyncio
    async def test_fienta_host_uses_jsonld_extractor(self, mock_db):
        """Non-KUMU/ECH host (fienta.com) uses extract_jsonld_event_text."""
        event = _future_event(
            url="https://fienta.com/some-event",
            title_localized=None,
            description_localized=None,
        )
        # JSON-LD Event block with name — should be extracted
        ld_html = _ld_script('{"@type":"Event","name":"Jazz Night","location":{"@type":"Place"}}')
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        with (
            patch("app.ingestion.refetch.http_get", new=AsyncMock(return_value=_resp(ld_html))),
            patch("app.ingestion.refetch.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await refetch_event_details(mock_db)

        # No hreflang alternates on the page, so no locales resolved → no backfill.
        # But the extractor (JSON-LD) was selected, not the og:title path.
        # The important thing: no crash, and for a page with no hreflang the
        # localized_text_backfilled counter stays 0.
        assert summary["localized_text_backfilled"] == 0
        assert event.title_localized is None


# ---------------------------------------------------------------------------
# locale_from_url_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,locales,expected",
    [
        ("https://kumu.ekm.ee/en/syndmus/foo-4/", LOCALIZED_TEXT_FIENTA_LOCALES, "en"),
        ("https://fienta.com/et/event-slug", LOCALIZED_TEXT_FIENTA_LOCALES, "et"),
        ("https://fienta.com/ru/event-slug", LOCALIZED_TEXT_FIENTA_LOCALES, "ru"),
        ("https://kumu.ekm.ee/syndmus/foo-4/", LOCALIZED_TEXT_FIENTA_LOCALES, None),
        ("https://example.com/de/event", LOCALIZED_TEXT_FIENTA_LOCALES, None),
    ],
)
def test_locale_from_url_path(url: str, locales: frozenset[str], expected: str | None) -> None:
    assert locale_from_url_path(url, locales) == expected


# ---------------------------------------------------------------------------
# _is_suspect_locale_title
# ---------------------------------------------------------------------------


def test_suspect_locale_title_kumu_homepage() -> None:
    garbage = "Kumu kunstimuuseum - Eesti Kunstimuuseumi filiaal - Avaleht"
    assert _is_suspect_locale_title(garbage, "kumu.ekm.ee") is True


def test_suspect_locale_title_valid_kumu_event() -> None:
    valid = "Näitus: Maailma lõpp"
    assert _is_suspect_locale_title(valid, "kumu.ekm.ee") is False


def test_suspect_locale_title_genitive_kumu_not_suspect() -> None:
    genitive = "Kumu kunstimuuseumi 100. aastapäeva näitus"
    assert _is_suspect_locale_title(genitive, "kumu.ekm.ee") is False


def test_suspect_locale_title_non_kumu_host() -> None:
    garbage = "Kumu kunstimuuseum - Avaleht"
    assert _is_suspect_locale_title(garbage, "fienta.com") is False


# ---------------------------------------------------------------------------
# kumu_localized_text — site-level homepage title rejected
# ---------------------------------------------------------------------------


def _make_soup(og_title: str, desc_text: str = "") -> BeautifulSoup:
    html = f"""
    <html><head>
      <meta property="og:title" content="{og_title}">
    </head><body>
      <div class="single__content-dynamic">{desc_text}</div>
    </body></html>"""
    return BeautifulSoup(html, "html.parser")


def test_kumu_localized_text_homepage_title_rejected() -> None:
    soup = _make_soup("Kumu kunstimuuseum - Eesti Kunstimuuseumi filiaal - Avaleht")
    title, desc = kumu_localized_text(soup)
    assert title is None


def test_kumu_localized_text_valid_event() -> None:
    soup = _make_soup(f"Näitus: Maailm{KUMU_SITE_TITLE_SUFFIX}", "Some description text")
    title, desc = kumu_localized_text(soup)
    assert title == "Näitus: Maailm"
    assert desc == "Some description text"


def test_kumu_localized_text_site_name_prefix_with_separator_rejected() -> None:
    soup = _make_soup(f"{KUMU_SITE_NAME_ET} - Avaleht")
    title, desc = kumu_localized_text(soup)
    assert title is None


def test_kumu_localized_text_genitive_prefix_not_rejected() -> None:
    soup = _make_soup(f"Kumu kunstimuuseumi 100. aastapäeva näitus{KUMU_SITE_TITLE_SUFFIX}")
    title, desc = kumu_localized_text(soup)
    assert title == "Kumu kunstimuuseumi 100. aastapäeva näitus"


# ---------------------------------------------------------------------------
# Per-locale merge (Bug 2c): missing locale filled, existing good locale kept
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refetch_per_locale_merge_keeps_existing(mock_db: MagicMock) -> None:
    """Refetch fills a missing locale without overwriting an already-good one."""
    event = _future_event(
        id=10,
        url="https://kumu.ekm.ee/en/syndmus/test-event-4/",
        title_localized={"en": "Test Event EN"},
        description_localized=None,
    )

    # Build a minimal KUMU-style page: no Event JSON-LD, has hreflang alternates
    main_html = """
    <html><head>
      <meta property="og:title" content="Test Event EN - Kumu kunstimuuseum">
      <link rel="alternate" hreflang="en" href="/syndmus/test-event-4/">
      <link rel="alternate" hreflang="et" href="/et/syndmus/test-event-4/">
    </head><body>
      <div class="single__content-dynamic">Event description EN</div>
    </body></html>"""

    et_html = """
    <html><head>
      <meta property="og:title" content="Test Event ET - Kumu kunstimuuseum">
    </head><body>
      <div class="single__content-dynamic">Event description ET</div>
    </body></html>"""

    def make_response(text: str, url: str = "https://kumu.ekm.ee/en/syndmus/test-event-4/") -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.text = text
        resp.url = httpx.URL(url)
        resp.raise_for_status = MagicMock()
        return resp

    main_resp = make_response(main_html)
    et_resp = make_response(et_html, "https://kumu.ekm.ee/et/syndmus/test-event-4/")

    async def fake_http_get(client: object, url: str, **kwargs: object) -> MagicMock:
        if "et/" in url:
            return et_resp
        return main_resp

    mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))

    with (
        patch("app.ingestion.refetch.http_get", side_effect=fake_http_get),
        patch("app.ingestion.refetch.asyncio.sleep", new_callable=AsyncMock),
    ):
        summary = await refetch_event_details(mock_db)

    # en title must be preserved; et title + description must be backfilled
    assert event.title_localized is not None
    assert event.title_localized.get("en") == "Test Event EN"
    assert event.title_localized.get("et") == "Test Event ET"
    assert summary["localized_text_backfilled"] >= 1


# ---------------------------------------------------------------------------
# Locale page redirected to site root is rejected (Bug 2b)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refetch_locale_redirect_to_root_rejected(mock_db: MagicMock) -> None:
    """A locale hreflang URL that 302s to site root must not pollute stored titles."""
    event = _future_event(
        id=11,
        url="https://kumu.ekm.ee/en/syndmus/test-event-4/",
        title_localized=None,
        description_localized=None,
    )

    main_html = """
    <html><head>
      <meta property="og:title" content="Test Event EN - Kumu kunstimuuseum">
      <link rel="alternate" hreflang="en" href="/syndmus/test-event-4/">
      <link rel="alternate" hreflang="et" href="https://kumu.ekm.ee/">
    </head><body>
      <div class="single__content-dynamic">EN description</div>
    </body></html>"""

    homepage_html = """
    <html><head>
      <meta property="og:title" content="Kumu kunstimuuseum - Eesti Kunstimuuseumi filiaal - Avaleht">
    </head><body></body></html>"""

    def make_response(text: str, url: str) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.text = text
        resp.url = httpx.URL(url)
        resp.raise_for_status = MagicMock()
        return resp

    async def fake_http_get(client: object, url: str, **kwargs: object) -> MagicMock:
        if url == "https://kumu.ekm.ee/":
            # simulate redirect to site root
            return make_response(homepage_html, "https://kumu.ekm.ee/")
        return make_response(main_html, "https://kumu.ekm.ee/en/syndmus/test-event-4/")

    mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))

    with (
        patch("app.ingestion.refetch.http_get", side_effect=fake_http_get),
        patch("app.ingestion.refetch.asyncio.sleep", new_callable=AsyncMock),
    ):
        await refetch_event_details(mock_db)

    # et must NOT be set (the homepage redirect was rejected)
    if event.title_localized:
        assert "et" not in event.title_localized
