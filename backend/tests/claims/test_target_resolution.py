"""Tests for app/claims/target_resolution.py (#427) — the single
Publisher/Series target-resolution step reused by claim creation, claim
recheck, and verification dispatch. Covers each per-source outcome from the
issue's acceptance criteria."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.claims.piletilevi_promoter import PromoterIdentity
from app.claims.target_resolution import (
    ClaimTarget,
    ClaimTargetError,
    _get_or_create_publisher,
    resolve_claim_target_live,
)
from app.constants import (
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
    SOURCE_SLUG_PILETILEVI,
    SOURCE_SLUG_TELLISKIVI,
)
from tests.claims.conftest import fake_event_source


def _fake_source(*, slug: str, config: dict | None = None, source_id: int = 1) -> MagicMock:
    source = MagicMock()
    source.id = source_id
    source.slug = slug
    source.config = config or {}
    return source


def _nested_cm(*, raises: Exception | None = None) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    if raises is not None:
        cm.__aexit__ = AsyncMock(side_effect=raises)
    else:
        cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestGetOrCreatePublisher:
    @pytest.mark.asyncio
    async def test_returns_existing_when_found(self, mock_db):
        existing = MagicMock(id=5)
        mock_db.scalar = AsyncMock(return_value=existing)

        result = await _get_or_create_publisher(
            mock_db, source_id=1, external_id="42", name="Some Promoter"
        )

        assert result is existing
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_when_not_found(self, mock_db):
        mock_db.scalar = AsyncMock(return_value=None)
        mock_db.begin_nested = MagicMock(return_value=_nested_cm())

        result = await _get_or_create_publisher(
            mock_db, source_id=1, external_id="42", name="Some Promoter"
        )

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args.args[0]
        assert added is result
        assert added.source_id == 1
        assert added.external_id == "42"
        assert added.name == "Some Promoter"

    @pytest.mark.asyncio
    async def test_race_reuses_row_created_by_concurrent_resolution(self, mock_db):
        """A unique-index collision on the savepoint means another request
        already created this Publisher — re-read and reuse it instead of
        raising into the caller's create_claim transaction."""
        winner = MagicMock(id=9)
        mock_db.scalar = AsyncMock(side_effect=[None, winner])
        mock_db.expunge = MagicMock()
        mock_db.begin_nested = MagicMock(
            return_value=_nested_cm(raises=IntegrityError("stmt", "params", Exception("dup")))
        )

        result = await _get_or_create_publisher(
            mock_db, source_id=1, external_id="42", name="Some Promoter"
        )

        assert result is winner
        mock_db.expunge.assert_called_once()


class TestFientaResolution:
    @pytest.mark.asyncio
    async def test_already_stamped_is_trusted_no_network(self, mock_db):
        source = _fake_source(slug=SOURCE_SLUG_FIENTA)
        es = fake_event_source(source=source, publisher_id=99)
        event = MagicMock()

        target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        assert target == ClaimTarget(CLAIM_KIND_PUBLISHER, 99, None)
        mock_db.scalar.assert_not_called()

    @pytest.mark.asyncio
    async def test_unstamped_resolves_via_raw_payload(self, mock_db):
        source = _fake_source(slug=SOURCE_SLUG_FIENTA)
        es = fake_event_source(source=source, publisher_id=None, external_id="200")
        event = MagicMock()
        raw = MagicMock(payload={"organizer_id": 42})
        mock_db.scalar = AsyncMock(return_value=raw)
        publisher = MagicMock(id=77)

        with patch(
            "app.claims.target_resolution._get_or_create_publisher",
            new_callable=AsyncMock,
            return_value=publisher,
        ) as get_or_create:
            target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        get_or_create.assert_awaited_once_with(
            mock_db, source_id=source.id, external_id="42", name="42"
        )
        assert target == ClaimTarget(CLAIM_KIND_PUBLISHER, 77, None)
        assert es.publisher_id == 77
        assert es.publisher is publisher

    @pytest.mark.asyncio
    async def test_unstamped_falls_back_to_live_requery(self, mock_db):
        """No raw_events row (or it predates the organizer_id stamp fix) —
        reuses FientaAdapter.fetch_organizer rather than reimplementing the
        fetch/paginate loop."""
        source = _fake_source(
            slug=SOURCE_SLUG_FIENTA, config={"organizer_ids": [1, 2], "retired_organizer_ids": [3]}
        )
        es = fake_event_source(source=source, publisher_id=None, external_id="200")
        event = MagicMock()
        mock_db.scalar = AsyncMock(return_value=None)  # no raw_events row
        publisher = MagicMock(id=88)

        async def fake_fetch_organizer(client, base_url, org_id, limiter):
            if org_id == 2:
                return [{"id": "200"}]
            return [{"id": "999"}]

        with (
            patch(
                "app.claims.target_resolution.FientaAdapter.fetch_organizer",
                side_effect=fake_fetch_organizer,
            ),
            patch(
                "app.claims.target_resolution._get_or_create_publisher",
                new_callable=AsyncMock,
                return_value=publisher,
            ) as get_or_create,
        ):
            target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        get_or_create.assert_awaited_once_with(
            mock_db, source_id=source.id, external_id="2", name="2"
        )
        assert target == ClaimTarget(CLAIM_KIND_PUBLISHER, 88, None)

    @pytest.mark.asyncio
    async def test_unresolvable_rejected_never_series(self, mock_db):
        """The claim always ends up a Fienta Publisher claim or is rejected
        outright — never silently downgraded to a Series claim."""
        source = _fake_source(slug=SOURCE_SLUG_FIENTA, config={"organizer_ids": []})
        es = fake_event_source(source=source, publisher_id=None, external_id="200")
        event = MagicMock()
        mock_db.scalar = AsyncMock(return_value=None)

        with pytest.raises(ClaimTargetError):
            await resolve_claim_target_live(mock_db, AsyncMock(), event, es)


class TestInstitutionalResolution:
    @pytest.mark.parametrize("slug", [SOURCE_SLUG_KUMU, SOURCE_SLUG_ESTONIA_CONCERT_HALL])
    @pytest.mark.asyncio
    async def test_always_resolves_constant_publisher_even_if_unstamped(self, mock_db, slug):
        source = _fake_source(slug=slug)
        es = fake_event_source(source=source, publisher_id=None)
        event = MagicMock()
        publisher = MagicMock(id=55)
        mock_db.scalar = AsyncMock(return_value=publisher)

        target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        assert target == ClaimTarget(CLAIM_KIND_PUBLISHER, 55, None)
        assert es.publisher_id == 55

    @pytest.mark.asyncio
    async def test_ignores_a_stale_stamped_publisher_id(self, mock_db):
        """Independent of whether the row happens to be stamped — always
        re-resolves the source's one seeded constant Publisher."""
        source = _fake_source(slug=SOURCE_SLUG_KUMU)
        es = fake_event_source(source=source, publisher_id=999)
        event = MagicMock()
        publisher = MagicMock(id=55)
        mock_db.scalar = AsyncMock(return_value=publisher)

        target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        assert target.publisher_id == 55

    @pytest.mark.asyncio
    async def test_no_seeded_publisher_rejected(self, mock_db):
        source = _fake_source(slug=SOURCE_SLUG_KUMU)
        es = fake_event_source(source=source, publisher_id=None)
        event = MagicMock()
        mock_db.scalar = AsyncMock(return_value=None)

        with pytest.raises(ClaimTargetError):
            await resolve_claim_target_live(mock_db, AsyncMock(), event, es)


class TestPiletileviResolution:
    @pytest.mark.asyncio
    async def test_already_stamped_is_trusted_no_network(self, mock_db):
        source = _fake_source(slug=SOURCE_SLUG_PILETILEVI)
        es = fake_event_source(source=source, publisher_id=33)
        event = MagicMock()

        with patch(
            "app.claims.target_resolution.http_get", new_callable=AsyncMock
        ) as http_get_mock:
            target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        http_get_mock.assert_not_awaited()
        assert target == ClaimTarget(CLAIM_KIND_PUBLISHER, 33, None)

    @pytest.mark.asyncio
    async def test_resolving_promoter_always_yields_publisher_target(self, mock_db):
        source = _fake_source(slug=SOURCE_SLUG_PILETILEVI)
        es = fake_event_source(source=source, publisher_id=None)
        event = MagicMock(url="https://www.piletilevi.ee/en/tickets/x/some-event")
        publisher = MagicMock(id=33)
        identity = PromoterIdentity(external_id="https://www.piletilevi.ee/en/promoters/1/x", name="X OÜ")

        with (
            patch(
                "app.claims.target_resolution.http_get",
                new_callable=AsyncMock,
                return_value=MagicMock(text="<html></html>"),
            ),
            patch(
                "app.claims.target_resolution.resolve_promoter_identity", return_value=identity
            ),
            patch(
                "app.claims.target_resolution._get_or_create_publisher",
                new_callable=AsyncMock,
                return_value=publisher,
            ) as get_or_create,
        ):
            target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        get_or_create.assert_awaited_once_with(
            mock_db, source_id=source.id, external_id=identity.external_id, name="X OÜ"
        )
        assert target == ClaimTarget(
            CLAIM_KIND_PUBLISHER, 33, None, event_page_html="<html></html>"
        )

    @pytest.mark.asyncio
    async def test_resolving_promoter_with_no_usable_domain_still_yields_publisher(
        self, mock_db
    ):
        """A resolved promoter id with no usable contact domain still yields
        a Publisher target — only the DNS-TXT verification step (#412) cares
        about the domain, not target resolution."""
        source = _fake_source(slug=SOURCE_SLUG_PILETILEVI)
        es = fake_event_source(source=source, publisher_id=None)
        event = MagicMock(url="https://www.piletilevi.ee/en/tickets/x/some-event")
        publisher = MagicMock(id=34)
        identity = PromoterIdentity(external_id="https://www.piletilevi.ee/en/promoters/2/y", name=None)

        with (
            patch(
                "app.claims.target_resolution.http_get",
                new_callable=AsyncMock,
                return_value=MagicMock(text="<html></html>"),
            ),
            patch(
                "app.claims.target_resolution.resolve_promoter_identity", return_value=identity
            ),
            patch(
                "app.claims.target_resolution._get_or_create_publisher",
                new_callable=AsyncMock,
                return_value=publisher,
            ) as get_or_create,
        ):
            target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        # Falls back to the external_id itself when the promoter node carries no name.
        get_or_create.assert_awaited_once_with(
            mock_db, source_id=source.id, external_id=identity.external_id, name=identity.external_id
        )
        assert target.kind == CLAIM_KIND_PUBLISHER
        assert target.event_page_html == "<html></html>"

    @pytest.mark.asyncio
    async def test_no_url_yields_series_without_fetching(self, mock_db, make_event):
        source = _fake_source(slug=SOURCE_SLUG_PILETILEVI)
        es = fake_event_source(source=source, publisher_id=None)
        event = make_event()
        event.url = None

        with patch(
            "app.claims.target_resolution.http_get", new_callable=AsyncMock
        ) as http_get_mock:
            target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        http_get_mock.assert_not_awaited()
        assert target.kind == CLAIM_KIND_SERIES
        assert target.event_series_key is not None

    @pytest.mark.asyncio
    async def test_non_resolving_promoter_yields_series(self, mock_db, make_event):
        source = _fake_source(slug=SOURCE_SLUG_PILETILEVI)
        es = fake_event_source(source=source, publisher_id=None)
        event = make_event()

        with (
            patch(
                "app.claims.target_resolution.http_get",
                new_callable=AsyncMock,
                return_value=MagicMock(text="<html></html>"),
            ),
            patch(
                "app.claims.target_resolution.resolve_promoter_identity", return_value=None
            ),
        ):
            target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        assert target.kind == CLAIM_KIND_SERIES

    @pytest.mark.asyncio
    async def test_event_page_fetch_failure_yields_series(self, mock_db, make_event):
        source = _fake_source(slug=SOURCE_SLUG_PILETILEVI)
        es = fake_event_source(source=source, publisher_id=None)
        event = make_event()

        with patch(
            "app.claims.target_resolution.http_get",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPError("boom"),
        ):
            target = await resolve_claim_target_live(mock_db, AsyncMock(), event, es)

        assert target.kind == CLAIM_KIND_SERIES


class TestOtherSourceResolution:
    @pytest.mark.asyncio
    async def test_no_resolvable_publisher_rejected_not_downgraded(self, mock_db):
        source = _fake_source(slug=SOURCE_SLUG_TELLISKIVI)
        es = fake_event_source(source=source, publisher_id=None)
        event = MagicMock()

        with pytest.raises(ClaimTargetError):
            await resolve_claim_target_live(mock_db, AsyncMock(), event, es)
