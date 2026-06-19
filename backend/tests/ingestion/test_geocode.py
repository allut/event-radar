"""Tests for Nominatim geocoding (geocode_address, geocode_pending, normalize_address_for_geocoding)."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.ingestion.geocode import (
    _is_suspect_venue_name,
    canonical_venue_name,
    copy_venue_from_siblings,
    extract_address_from_venue_name,
    geocode_address,
    geocode_pending,
    normalize_address_for_geocoding,
)


def _mock_response(json_data):
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = json_data
    return resp


class TestNormalizeAddressForGeocoding:
    def test_tanav_stripped(self):
        result = normalize_address_for_geocoding("Telliskivi tänav 60a, 10412 Tallinn")
        assert "tänav" not in result
        assert "tn" not in result
        assert "Telliskivi 60a" in result

    def test_maantee_stripped(self):
        result = normalize_address_for_geocoding("Narva maantee 63, Tallinn")
        assert "maantee" not in result
        assert "mnt" not in result
        assert "Narva 63" in result

    def test_puiestee_stripped(self):
        result = normalize_address_for_geocoding("Estonia puiestee 4, Tallinn")
        assert "puiestee" not in result
        assert "pst" not in result
        assert "Estonia 4" in result

    def test_tee_preserved_not_stripped(self):
        """'tee' is an inseparable part of many Tallinn street names (Mustamäe tee)
        — stripping it would collapse to a district-centroid match, so it stays."""
        result = normalize_address_for_geocoding("Mustamäe tee 25, 10621 Tallinn")
        assert "Mustamäe tee 25" in result

    def test_leading_initial_stripped(self):
        result = normalize_address_for_geocoding("A. Weizenbergi 26, 10127 Tallinn")
        assert "Weizenbergi 26" in result
        assert "A." not in result

    def test_leading_initial_no_space_stripped(self):
        result = normalize_address_for_geocoding("L.Koidula 12a, Tallinn")
        assert "Koidula 12a" in result
        assert "L." not in result

    def test_unit_suffix_stripped_slash_9(self):
        result = normalize_address_for_geocoding("Telliskivi tänav 60a/9, 10412 Tallinn")
        assert "/9" not in result
        assert "60a" in result

    def test_unit_suffix_stripped_space_slash_space(self):
        result = normalize_address_for_geocoding("Telliskivi tänav 60a / 9, Tallinn")
        assert "/ 9" not in result

    def test_unit_suffix_stripped_slash_space(self):
        result = normalize_address_for_geocoding("Telliskivi tänav 60a/ 9, Tallinn")
        assert "/ 9" not in result

    def test_all_three_unit_variants_normalize_to_same_string(self):
        base = "Telliskivi tänav 60a, 10412 Tallinn, Harju maakond"
        v1 = normalize_address_for_geocoding("Telliskivi tänav 60a/9, 10412 Tallinn, Harju maakond")
        v2 = normalize_address_for_geocoding("Telliskivi tänav 60a/ 9, 10412 Tallinn, Harju maakond")
        v3 = normalize_address_for_geocoding("Telliskivi tänav 60a / 9, 10412 Tallinn, Harju maakond")
        expected = normalize_address_for_geocoding(base)
        assert v1 == expected
        assert v2 == expected
        assert v3 == expected

    def test_county_harju_maakond_stripped(self):
        result = normalize_address_for_geocoding("Narva mnt 63, Tallinn, Harju maakond")
        assert "maakond" not in result
        assert "Harju" not in result

    def test_county_harjumaa_stripped(self):
        result = normalize_address_for_geocoding("Telliskivi 60a, Tallinn, Harjumaa")
        assert "Harjumaa" not in result

    def test_floor_stripped(self):
        result = normalize_address_for_geocoding("Pärnu mnt 10, Tallinn, II korrus")
        assert "korrus" not in result

    def test_english_secondary_unit_fragments_stripped(self):
        """English ", building X" / ", Nth floor" fragments break Nominatim — strip them."""
        result = normalize_address_for_geocoding(
            "Mäealuse street 2/4, building A, 3rd floor, 12618 Tallinn, Harju County"
        )
        assert result == "Mäealuse 2, 12618 Tallinn, Estonia"

    def test_secondary_unit_strip_is_comma_segment_bounded(self):
        """The building/floor strip is confined to one comma segment — it removes the
        annotation segment but never consumes the trailing city token across a comma."""
        result = normalize_address_for_geocoding("Narva mnt 5, Old Building, Tallinn")
        assert "Building" not in result
        assert result == "Narva 5, Tallinn, Estonia"

    def test_estonia_suffix_appended(self):
        result = normalize_address_for_geocoding("Narva mnt 63, Tallinn")
        assert result.endswith(", Estonia")

    def test_estonia_suffix_not_duplicated(self):
        result = normalize_address_for_geocoding("Narva mnt 63, Tallinn, Estonia")
        assert result.count("Estonia") == 1

    def test_case_insensitive_street_type(self):
        result = normalize_address_for_geocoding("Narva Maantee 63, Tallinn")
        assert "Maantee" not in result
        assert "Narva 63" in result


class TestGeocodeAddress:
    @pytest.mark.asyncio
    async def test_returns_lat_lng_from_first_result(self):
        with patch("app.ingestion.geocode.http_get") as mock_get:
            mock_get.return_value = _mock_response([{"lat": "59.437", "lon": "24.745"}])
            result = await geocode_address(MagicMock(), "Some Address, Tallinn")
        assert result == (59.437, 24.745)

    @pytest.mark.asyncio
    async def test_empty_results_returns_none_and_logs_warning(self, caplog):
        with patch("app.ingestion.geocode.http_get") as mock_get:
            mock_get.return_value = _mock_response([])
            with caplog.at_level(logging.WARNING, logger="app.ingestion.geocode"):
                result = await geocode_address(MagicMock(), "Nowhere tn 1, Estonia", original="Nowhere tänav 1")
        assert result is None
        assert "no match" in caplog.text

    @pytest.mark.asyncio
    async def test_non_json_response_returns_none(self):
        resp = MagicMock(spec=httpx.Response)
        resp.json.side_effect = ValueError("Expecting value: line 1 column 1")
        with patch("app.ingestion.geocode.http_get") as mock_get:
            mock_get.return_value = resp
            result = await geocode_address(MagicMock(), "Some Address, Tallinn")
        assert result is None


class TestGeocodePending:
    @pytest.mark.asyncio
    async def test_no_pending_events_returns_zero_summary(self, mock_db):
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        with patch(
            "app.ingestion.geocode.copy_venue_from_siblings",
            new=AsyncMock(return_value=0),
        ):
            summary = await geocode_pending(mock_db)
        assert summary == {"pending": 0, "geocoded": 0, "failed": 0, "copied": 0, "extracted": 0}

    @pytest.mark.asyncio
    async def test_geocodes_events_and_reuses_cached_address(self, mock_db, make_event):
        event1 = make_event(event_id=1)
        event1.venue_address = "Address A"
        event1.lat = None
        event1.lng = None

        event2 = make_event(event_id=2)
        event2.venue_address = "Address B"
        event2.lat = None
        event2.lng = None

        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[event1, event2])
        )
        # "Address B" was already geocoded on a different event -> seeds the cache
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(return_value=[("Address B", 59.1, 24.1)])
        )

        with (
            patch(
                "app.ingestion.geocode.copy_venue_from_siblings",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "app.ingestion.geocode.geocode_address",
                new=AsyncMock(return_value=(59.5, 24.5)),
            ) as mock_geo,
            patch("app.ingestion.geocode.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await geocode_pending(mock_db)

        assert summary == {"pending": 2, "geocoded": 2, "failed": 0, "copied": 0, "extracted": 0}
        assert (event1.lat, event1.lng) == (59.5, 24.5)
        assert (event2.lat, event2.lng) == (59.1, 24.1)
        mock_geo.assert_called_once()  # only "Address A" needed a Nominatim call

    @pytest.mark.asyncio
    async def test_format_variants_of_one_venue_cost_single_nominatim_call(self, mock_db, make_event):
        """Three address variants that normalize identically → one geocode call."""
        event1 = make_event(event_id=1)
        event1.venue_address = "Telliskivi tänav 60a/9, 10412 Tallinn, Harju maakond"
        event1.lat = None
        event1.lng = None

        event2 = make_event(event_id=2)
        event2.venue_address = "Telliskivi tänav 60a/ 9, 10412 Tallinn, Harju maakond"
        event2.lat = None
        event2.lng = None

        event3 = make_event(event_id=3)
        event3.venue_address = "Telliskivi tänav 60a / 9, 10412 Tallinn, Harju maakond"
        event3.lat = None
        event3.lng = None

        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[event1, event2, event3])
        )
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        with (
            patch(
                "app.ingestion.geocode.copy_venue_from_siblings",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "app.ingestion.geocode.geocode_address",
                new=AsyncMock(return_value=(59.44, 24.72)),
            ) as mock_geo,
            patch("app.ingestion.geocode.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await geocode_pending(mock_db)

        assert summary == {"pending": 3, "geocoded": 3, "failed": 0, "copied": 0, "extracted": 0}
        mock_geo.assert_called_once()  # normalized key collision → 1 call for 3 events

    @pytest.mark.asyncio
    async def test_donor_seeded_from_normalized_variant_not_raw_match(
        self, mock_db, make_event
    ):
        """A pending event's raw address differs from an already-geocoded event's
        raw address, but both normalize to the same query (spelling/unit variant)
        — the donor must seed the cache so zero Nominatim calls are made."""
        pending_event = make_event(event_id=1)
        pending_event.venue_address = "Telliskivi 60a/9, 10412 Tallinn, Harjumaa"
        pending_event.lat = None
        pending_event.lng = None

        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[pending_event])
        )
        # Donor is a different event (not in `pending`), with a raw address that
        # does NOT string-equal the pending event's raw address.
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[
                    (
                        "Telliskivi tänav 60a/9, 10412 Tallinn, Harju maakond",
                        59.4381936,
                        24.7286398,
                    )
                ]
            )
        )

        with (
            patch(
                "app.ingestion.geocode.copy_venue_from_siblings",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "app.ingestion.geocode.geocode_address", new=AsyncMock()
            ) as mock_geo,
            patch("app.ingestion.geocode.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await geocode_pending(mock_db)

        assert summary == {"pending": 1, "geocoded": 1, "failed": 0, "copied": 0, "extracted": 0}
        assert (pending_event.lat, pending_event.lng) == (59.4381936, 24.7286398)
        mock_geo.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_geocode_counts_as_failed_and_leaves_coords_unset(
        self, mock_db, make_event
    ):
        event1 = make_event(event_id=1)
        event1.venue_address = "Unknown Place"
        event1.lat = None
        event1.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event1]))
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        with (
            patch(
                "app.ingestion.geocode.copy_venue_from_siblings",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "app.ingestion.geocode.geocode_address", new=AsyncMock(return_value=None)
            ),
            patch("app.ingestion.geocode.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await geocode_pending(mock_db)

        assert summary == {"pending": 1, "geocoded": 0, "failed": 1, "copied": 0, "extracted": 0}
        assert event1.lat is None
        assert event1.lng is None


class TestCopyVenueFromSiblings:
    @pytest.mark.asyncio
    async def test_copies_from_single_distinct_sibling(self, mock_db, make_event):
        """An address-less event inherits address+coords from its same-name sibling."""
        target = make_event(event_id=1)
        target.venue_name = "Kai Art Center"
        target.venue_address = None
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[("Kai Art Center", "Peetri 12, Tallinn", 59.44, 24.78)]
            )
        )

        copied = await copy_venue_from_siblings(mock_db)

        assert copied == 1
        assert target.venue_address == "Peetri 12, Tallinn"
        assert (target.lat, target.lng) == (59.44, 24.78)

    @pytest.mark.asyncio
    async def test_skips_venue_with_conflicting_sibling_addresses(
        self, mock_db, make_event, caplog
    ):
        """A venue_name mapping to >1 distinct address is ambiguous → skipped + logged."""
        target = make_event(event_id=1)
        target.venue_name = "Club"
        target.venue_address = None
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[
                    ("Club", "Street A 1, Tallinn", 59.1, 24.1),
                    ("Club", "Street B 2, Tallinn", 59.2, 24.2),
                ]
            )
        )

        with caplog.at_level(logging.WARNING, logger="app.ingestion.geocode"):
            copied = await copy_venue_from_siblings(mock_db)

        assert copied == 0
        assert target.venue_address is None
        assert "venue copy skipped" in caplog.text

    @pytest.mark.asyncio
    async def test_no_targets_returns_zero_without_donor_query(self, mock_db):
        """No address-less events → returns 0 and never runs the donor query."""
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        copied = await copy_venue_from_siblings(mock_db)

        assert copied == 0
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_target_without_matching_sibling_is_untouched(
        self, mock_db, make_event
    ):
        """An address-less event whose venue has no address-bearing sibling stays null."""
        target = make_event(event_id=1)
        target.venue_name = "Orphan Venue"
        target.venue_address = None
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        copied = await copy_venue_from_siblings(mock_db)

        assert copied == 0
        assert target.venue_address is None
        assert target.lat is None

    @pytest.mark.asyncio
    async def test_copies_from_parens_suffix_donor(self, mock_db, make_event):
        """Donor "… (STL)" with 3 address spellings at one coord copies onto the
        bare-name target; the representative address is deterministic (lex tie-break)."""
        target = make_event(event_id=1)
        target.venue_name = "Sõltumatu Tantsu Lava"
        target.venue_address = None
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[
                    ("Sõltumatu Tantsu Lava (STL)", "Telliskivi tänav 60a/9, Tallinn", 59.4381936, 24.7286398),
                    ("Sõltumatu Tantsu Lava (STL)", "Telliskivi tänav 60a, Tallinn", 59.4381936, 24.7286398),
                    ("Sõltumatu Tantsu Lava (STL)", "Telliskivi 60a/9, Harjumaa", 59.4381936, 24.7286398),
                ]
            )
        )

        copied = await copy_venue_from_siblings(mock_db)

        assert copied == 1
        assert (target.lat, target.lng) == (59.4381936, 24.7286398)
        # All three addresses are distinct → tie on count → smallest lexicographically.
        assert target.venue_address == "Telliskivi 60a/9, Harjumaa"

    @pytest.mark.asyncio
    async def test_copies_from_bare_donor_for_address_tail_target(
        self, mock_db, make_event
    ):
        """A target whose venue_name has a glued-on address tail still matches the
        bare donor once both are canonicalized."""
        target = make_event(event_id=1)
        target.venue_name = "Kalamaja muuseum, Kotzebue tänav, Tallinn, Eesti"
        target.venue_address = None
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[("Kalamaja muuseum", "Kotzebue 16, Tallinn", 59.45, 24.74)]
            )
        )

        copied = await copy_venue_from_siblings(mock_db)

        assert copied == 1
        assert target.venue_address == "Kotzebue 16, Tallinn"
        assert (target.lat, target.lng) == (59.45, 24.74)

    @pytest.mark.asyncio
    async def test_copies_when_multiple_spellings_share_one_coord(
        self, mock_db, make_event
    ):
        """Regression guard for the coord-vs-tuple fix: several distinct address
        strings at a single coord are NOT treated as ambiguous."""
        target = make_event(event_id=1)
        target.venue_name = "Paavli Kultuurivabrik, Paavli tänav, Tallinn, Eesti"
        target.venue_address = None
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[
                    ("Paavli Kultuurivabrik", "Paavli tänav 4, Tallinn", 59.4476026, 24.7049754),
                    ("Paavli Kultuurivabrik", "Paavli 4, Tallinn", 59.4476026, 24.7049754),
                ]
            )
        )

        copied = await copy_venue_from_siblings(mock_db)

        assert copied == 1
        assert (target.lat, target.lng) == (59.4476026, 24.7049754)

    @pytest.mark.asyncio
    async def test_float_split_coords_treated_as_one_venue(
        self, mock_db, make_event
    ):
        """Fix 1: one physical coord stored as two sub-meter-apart doubles
        (59.43793509999999 vs 59.4379351) must round to a single distinct coord →
        copy succeeds, and a real unrounded donor coord is written (not the key)."""
        target = make_event(event_id=1)
        target.venue_name = "Sõltumatu Tantsu Lava"
        target.venue_address = None
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[
                    ("Sõltumatu Tantsu Lava (STL)", "Telliskivi 60a, Tallinn", 59.43793509999999, 24.7286398),
                    ("Sõltumatu Tantsu Lava (STL)", "Telliskivi 60a, Tallinn", 59.4379351, 24.7286398),
                ]
            )
        )

        copied = await copy_venue_from_siblings(mock_db)

        assert copied == 1
        assert target.venue_address == "Telliskivi 60a, Tallinn"
        # An actual (unrounded) donor coord is written, not the rounded distinct key.
        assert target.lat in (59.43793509999999, 59.4379351)
        assert target.lng == 24.7286398

    @pytest.mark.asyncio
    async def test_event_with_coords_only_gains_address(self, mock_db, make_event):
        """Fix 2: a target that already has coords (set at ingest) but no address
        keeps its coords and only backfills venue_address from a sibling."""
        target = make_event(event_id=1)
        target.venue_name = "Sõltumatu Tantsu Lava"
        target.venue_address = None
        target.lat = 59.4380000
        target.lng = 24.7290000

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[
                    ("Sõltumatu Tantsu Lava (STL)", "Telliskivi 60a, Tallinn", 59.4381936, 24.7286398),
                ]
            )
        )

        copied = await copy_venue_from_siblings(mock_db)

        assert copied == 1
        assert target.venue_address == "Telliskivi 60a, Tallinn"
        # Ingest coords preserved — not overwritten by the donor's.
        assert (target.lat, target.lng) == (59.4380000, 24.7290000)

    @pytest.mark.asyncio
    async def test_junk_address_no_coords_inherits_sibling_address(
        self, mock_db, make_event
    ):
        """Fix 2: a target with a street-only junk address but no coords inherits the
        house-numbered sibling address (overwriting the junk) plus its coords."""
        target = make_event(event_id=1)
        target.venue_name = "Kalamaja muuseum"
        target.venue_address = "Kotzebue tänav, Tallinn, Eesti"  # street-only, never geocoded
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[
                    ("Kalamaja muuseum", "Kotzebue tänav 16, 10411 Tallinn, Harju maakond", 59.4485, 24.7400),
                ]
            )
        )

        copied = await copy_venue_from_siblings(mock_db)

        assert copied == 1
        assert target.venue_address == "Kotzebue tänav 16, 10411 Tallinn, Harju maakond"
        assert (target.lat, target.lng) == (59.4485, 24.7400)

    @pytest.mark.asyncio
    async def test_skips_when_matched_donors_span_distinct_coords(
        self, mock_db, make_event, caplog
    ):
        """Two donors that both fuzzy-match the target but sit at different coords →
        ambiguous → skipped + logged (distinct-coordinate guard)."""
        target = make_event(event_id=1)
        target.venue_name = "Sõltumatu Tantsu Lava"
        target.venue_address = None
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[
                    ("Sõltumatu Tantsu Lava (STL)", "Telliskivi 60a, Tallinn", 59.4381936, 24.7286398),
                    ("Sõltumatu Tantsu Lava", "Other 1, Tallinn", 59.5, 24.8),
                ]
            )
        )

        with caplog.at_level(logging.WARNING, logger="app.ingestion.geocode"):
            copied = await copy_venue_from_siblings(mock_db)

        assert copied == 0
        assert target.venue_address is None
        assert "venue copy skipped" in caplog.text
        assert "distinct locations" in caplog.text

    @pytest.mark.asyncio
    async def test_dissimilar_names_below_threshold_no_copy(self, mock_db, make_event):
        """A donor whose canonical name is below VENUE_RATIO_THRESHOLD never copies."""
        target = make_event(event_id=1)
        target.venue_name = "Comedy Estonia"
        target.venue_address = None
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[("Jazz Club", "Vana 2, Tallinn", 59.43, 24.75)]
            )
        )

        copied = await copy_venue_from_siblings(mock_db)

        assert copied == 0
        assert target.venue_address is None

    @pytest.mark.asyncio
    async def test_virtual_venue_skipped_via_skip_set(
        self, mock_db, make_event, caplog
    ):
        """A virtual target ("MamaOnline") gets no copy because its only fuzzy donor
        ("online") is dropped by NON_GEOCODABLE_VENUE_NAMES — and no warning fires."""
        target = make_event(event_id=1)
        target.venue_name = "MamaOnline"
        target.venue_address = None
        target.lat = None
        target.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[target]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(
                return_value=[("online", "10614 Tallinn", 59.43, 24.75)]
            )
        )

        with caplog.at_level(logging.WARNING, logger="app.ingestion.geocode"):
            copied = await copy_venue_from_siblings(mock_db)

        assert copied == 0
        assert target.venue_address is None
        assert "venue copy skipped" not in caplog.text


class TestCanonicalVenueName:
    def test_strips_parenthetical_suffix(self):
        assert canonical_venue_name("Sõltumatu Tantsu Lava (STL)") == "sõltumatu tantsu lava"

    def test_drops_address_tail_after_first_comma(self):
        assert (
            canonical_venue_name("Kalamaja muuseum, Kotzebue tänav, Tallinn, Eesti")
            == "kalamaja muuseum"
        )

    def test_collapses_whitespace_and_lowercases(self):
        assert canonical_venue_name("  Paavli   Kultuurivabrik  ") == "paavli kultuurivabrik"

    def test_parens_and_tail_combined(self):
        assert canonical_venue_name("Foo (Bar), Some Street 1") == "foo"

    def test_empty_when_only_parens(self):
        assert canonical_venue_name("(STL)") == ""


class TestIsSuspectVenueName:
    def test_digit_flags_suspect(self):
        assert _is_suspect_venue_name("Kopli 116") is True

    def test_comma_flags_suspect(self):
        assert _is_suspect_venue_name("Viljandi padel, Ranna pst 3") is True

    def test_direction_keyword_algus_flags_suspect(self):
        assert _is_suspect_venue_name("Algus Hildegardi aias Tornide väljakul") is True

    def test_direction_keyword_kõrval_flags_suspect(self):
        assert _is_suspect_venue_name("Katharienthal Kohviku kõrval") is True

    def test_long_name_flags_suspect(self):
        assert _is_suspect_venue_name("A" * 41) is True

    def test_clean_short_name_not_suspect(self):
        assert _is_suspect_venue_name("KUMU") is False

    def test_parens_suffix_not_suspect(self):
        assert _is_suspect_venue_name("Sõltumatu Tantsu Lava (STL)") is False

    def test_exactly_max_len_not_suspect(self):
        from app.constants import VENUE_NAME_SUSPECT_MAX_LEN
        assert _is_suspect_venue_name("A" * VENUE_NAME_SUSPECT_MAX_LEN) is False

    def test_meeting_point_en_flags_suspect(self):
        assert _is_suspect_venue_name("Meeting point Baltic station") is True

    def test_in_front_of_flags_suspect(self):
        assert _is_suspect_venue_name("in front of the town hall") is True


class TestExtractAddressFromVenueName:
    """Tests for the LLM venue-address extraction pass."""

    def _make_event(self, event_id: int, venue_name: str) -> MagicMock:
        e = MagicMock()
        e.id = event_id
        e.venue_name = venue_name
        e.venue_address = None
        return e

    @pytest.mark.asyncio
    async def test_no_llm_available_returns_zero(self, mock_db):
        with patch("app.ingestion.geocode.llm_available", return_value=False):
            result = await extract_address_from_venue_name(mock_db)
        assert result == 0
        mock_db.scalars.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_candidates_returns_zero(self, mock_db):
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        with patch("app.ingestion.geocode.llm_available", return_value=True):
            result = await extract_address_from_venue_name(mock_db)
        assert result == 0

    @pytest.mark.asyncio
    async def test_clean_name_skipped_no_llm_call(self, mock_db):
        event = self._make_event(1, "KUMU")
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        with (
            patch("app.ingestion.geocode.llm_available", return_value=True),
            patch("app.ingestion.geocode.llm_json") as mock_llm,
        ):
            result = await extract_address_from_venue_name(mock_db)
        assert result == 0
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_bare_street_number_nulls_name_sets_address(self, mock_db):
        event = self._make_event(1, "Kopli 116")
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        llm_response = {"venue_name": None, "venue_address": "Kopli 116"}
        with (
            patch("app.ingestion.geocode.llm_available", return_value=True),
            patch("app.ingestion.geocode.llm_json", new=AsyncMock(return_value=(llm_response, "groq/llama"))),
        ):
            result = await extract_address_from_venue_name(mock_db)

        assert result == 1
        assert event.venue_name is None
        assert event.venue_address == "Kopli 116"

    @pytest.mark.asyncio
    async def test_comma_tail_keeps_venue_name_sets_address(self, mock_db):
        event = self._make_event(1, "Viljandi tennise- ja padelikeskuse padeli väliväljakud, Ranna pst 3")
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        llm_response = {
            "venue_name": "Viljandi tennise- ja padelikeskuse padeli väliväljakud",
            "venue_address": "Ranna pst 3",
        }
        with (
            patch("app.ingestion.geocode.llm_available", return_value=True),
            patch("app.ingestion.geocode.llm_json", new=AsyncMock(return_value=(llm_response, "groq/llama"))),
        ):
            result = await extract_address_from_venue_name(mock_db)

        assert result == 1
        assert event.venue_name == "Viljandi tennise- ja padelikeskuse padeli väliväljakud"
        assert event.venue_address == "Ranna pst 3"

    @pytest.mark.asyncio
    async def test_no_address_extracted_leaves_venue_name_unchanged(self, mock_db):
        """When the LLM mines no address, venue_name is left intact (Fix 3): rewriting
        the name with no address payoff only risks breaking canonical sibling matching."""
        original = "Algus Hildegardi aias Tornide väljakul"
        event = self._make_event(1, original)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        # LLM proposes a shortened name but no address — must be ignored.
        llm_response = {"venue_name": "Hildegardi aed", "venue_address": None}
        with (
            patch("app.ingestion.geocode.llm_available", return_value=True),
            patch("app.ingestion.geocode.llm_json", new=AsyncMock(return_value=(llm_response, "groq/llama"))),
        ):
            result = await extract_address_from_venue_name(mock_db)

        assert result == 0
        assert event.venue_name == original
        assert event.venue_address is None

    @pytest.mark.asyncio
    async def test_cached_decision_applied_without_fresh_call(self, mock_db):
        from app.constants import LLM_VENUE_EXTRACT_PROMPT_TEMPLATE
        from app.llm.router import content_hash as ch

        name = "Kopli 116"
        prompt = LLM_VENUE_EXTRACT_PROMPT_TEMPLATE.format(venue=name)
        cached_hash = ch(prompt)
        cached_response = {"venue_name": None, "venue_address": "Kopli 116"}

        event = self._make_event(1, name)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(return_value=[(cached_hash, cached_response)])
        )

        with (
            patch("app.ingestion.geocode.llm_available", return_value=True),
            patch("app.ingestion.geocode.llm_json") as mock_llm,
        ):
            result = await extract_address_from_venue_name(mock_db)

        assert result == 1
        mock_llm.assert_not_called()
        assert event.venue_address == "Kopli 116"

    @pytest.mark.asyncio
    async def test_fresh_call_budget_defers_excess(self, mock_db):
        from app.constants import VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN

        events = [self._make_event(i, f"Kopli {i}") for i in range(VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN + 2)]
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=events))
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        llm_response = {"venue_name": None, "venue_address": "Some Street 1"}
        call_count = 0

        async def counting_llm_json(task, prompt, db, **kwargs):
            nonlocal call_count
            call_count += 1
            return (llm_response, "groq/llama")

        with (
            patch("app.ingestion.geocode.llm_available", return_value=True),
            patch("app.ingestion.geocode.llm_json", new=counting_llm_json),
        ):
            await extract_address_from_venue_name(mock_db)

        assert call_count == VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN

    @pytest.mark.asyncio
    async def test_malformed_llm_response_skipped(self, mock_db):
        event = self._make_event(1, "Algus Raevangla ees")
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        with (
            patch("app.ingestion.geocode.llm_available", return_value=True),
            patch("app.ingestion.geocode.llm_json", new=AsyncMock(return_value=(None, "groq/llama"))),
        ):
            result = await extract_address_from_venue_name(mock_db)

        assert result == 0
        assert event.venue_name == "Algus Raevangla ees"
        assert event.venue_address is None

    @pytest.mark.asyncio
    async def test_llm_error_skips_gracefully(self, mock_db):
        from app.llm.router import LLMError

        event = self._make_event(1, "Kopli 116")
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        with (
            patch("app.ingestion.geocode.llm_available", return_value=True),
            patch("app.ingestion.geocode.llm_json", new=AsyncMock(side_effect=LLMError("all providers failed"))),
        ):
            result = await extract_address_from_venue_name(mock_db)

        assert result == 0
        assert event.venue_name == "Kopli 116"
        assert event.venue_address is None

    @pytest.mark.asyncio
    async def test_geocode_pending_summary_includes_extracted(self, mock_db):
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        with (
            patch("app.ingestion.geocode.extract_address_from_venue_name", new=AsyncMock(return_value=3)),
            patch("app.ingestion.geocode.copy_venue_from_siblings", new=AsyncMock(return_value=1)),
        ):
            summary = await geocode_pending(mock_db)
        assert summary["extracted"] == 3
        assert summary["copied"] == 1
