"""Tests for routers/organizer_claim_search.py (#414) — claimable-event search and
onboarding suggestions, exercised by calling the endpoint functions directly
against a mocked db."""

import http
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


def _make_source(event_id: int = 42, source_id: int = 1, publisher_id: int | None = 99) -> MagicMock:
    es = MagicMock()
    es.id = source_id
    es.event_id = event_id
    es.publisher_id = publisher_id
    return es


class TestSearchClaimableEvents(object):
    @pytest.mark.asyncio
    async def test_query_too_short_rejected(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claim_search import search_claimable_events

        with pytest.raises(HTTPException) as exc:
            await search_claimable_events(
                make_request(method="GET", path="/organizer/claims/search"),
                q="a",
                current_organizer=make_organizer(),
                db=mock_db,
                locale=None,
            )
        assert exc.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_publisher_claimed_events_excluded_in_sql(self, mock_db, make_event, make_request, make_organizer):
        """An event whose Publisher already has an *approved* claim (#441)
        is excluded by the candidate query itself (NOT EXISTS), so the
        LIMIT window is never spent on already-claimed rows."""
        from app.routers.organizer_claim_search import search_claimable_events

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = []
        claim_keys_result = MagicMock()
        claim_keys_result.all.return_value = []
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        await search_claimable_events(
            make_request(method="GET", path="/organizer/claims/search"),
            q="jazz",
            current_organizer=make_organizer(),
            db=mock_db,
            locale=None,
        )

        from sqlalchemy.dialects import postgresql

        compiled = str(
            mock_db.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect())
        )
        assert "NOT (EXISTS" in compiled
        assert "claims.publisher_id = event_sources.publisher_id" in compiled
        # The lowest-id-source subquery must be correlated to the outer event
        # (an uncorrelated EXISTS would hide every event once any claim exists).
        assert "event_sources_1.event_id = events.id" in compiled
        assert "FROM events \nWHERE event_sources" not in compiled
        assert "claims.status" in compiled

    @pytest.mark.asyncio
    async def test_excludes_series_claimed_event(self, mock_db, make_event, make_request, make_organizer):
        """A publisher-less event whose Series key has an approved claim is
        filtered in Python (the key uses the resolved venue name)."""
        from app.claims.lifecycle import resolve_claim_target
        from app.routers.organizer_claim_search import search_claimable_events

        claimed_event = make_event(event_id=1, title="Jazz Night")
        claimed_event.sources = [_make_source(event_id=1, publisher_id=None)]
        open_event = make_event(event_id=2, title="Jazz Brunch")
        open_event.sources = [_make_source(event_id=2, publisher_id=None)]
        key = resolve_claim_target(claimed_event, claimed_event.sources[0]).event_series_key

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [claimed_event, open_event]
        claim_keys_result = MagicMock()
        claim_keys_result.all.return_value = [MagicMock(event_series_key=key)]
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        result = await search_claimable_events(
            make_request(method="GET", path="/organizer/claims/search"),
            q="jazz",
            current_organizer=make_organizer(),
            db=mock_db,
            locale=None,
        )

        assert [e["id"] for e in result["events"]] == [2]

    @pytest.mark.asyncio
    async def test_includes_pending_only_claim_event(self, mock_db, make_event, make_request, make_organizer):
        """(#441) A Publisher target with only a *pending* claim must still
        surface in search — a rival claimant needs a product path to start
        proving ownership."""
        from app.routers.organizer_claim_search import search_claimable_events

        pending_event = make_event(event_id=1, title="Jazz Night")
        pending_event.sources = [_make_source(event_id=1, publisher_id=99)]

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [pending_event]
        claim_keys_result = MagicMock()
        # The DB-side query itself filters to approved claims only, so a
        # pending-only Publisher never appears in this row set.
        claim_keys_result.all.return_value = []
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        result = await search_claimable_events(
            make_request(method="GET", path="/organizer/claims/search"),
            q="jazz",
            current_organizer=make_organizer(),
            db=mock_db,
            locale=None,
        )

        assert [e["id"] for e in result["events"]] == [1]

    @pytest.mark.asyncio
    async def test_event_with_no_source_excluded(self, mock_db, make_event, make_request, make_organizer):
        """An organizer's own direct submission (no EventSource at all) has
        nothing to claim against and must not appear."""
        from app.routers.organizer_claim_search import search_claimable_events

        event = make_event(event_id=1)
        event.sources = []

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [event]
        claim_keys_result = MagicMock()
        claim_keys_result.all.return_value = []
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        result = await search_claimable_events(
            make_request(method="GET", path="/organizer/claims/search"),
            q="jazz",
            current_organizer=make_organizer(),
            db=mock_db,
            locale=None,
        )

        assert result["events"] == []

    @pytest.mark.asyncio
    async def test_locale_param_localizes_result_titles(
        self, mock_db, make_event, make_request, make_organizer
    ):
        """(#454) locale=ru must localize a candidate's title regardless of
        the organizer's stored locale."""
        from app.routers.organizer_claim_search import search_claimable_events

        event = make_event(event_id=1, title="Jazz Night")
        event.title_localized = {"ru": "Джазовая ночь"}
        event.sources = [_make_source(event_id=1, publisher_id=99)]

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [event]
        claim_keys_result = MagicMock()
        claim_keys_result.all.return_value = []
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        result = await search_claimable_events(
            make_request(method="GET", path="/organizer/claims/search"),
            q="jazz",
            locale="ru",
            current_organizer=make_organizer(organizer_id=5, locale="en"),
            db=mock_db,
        )

        assert result["events"][0]["title"] == "Джазовая ночь"


class TestSuggestedClaimableEvents:
    @pytest.mark.asyncio
    async def test_free_email_domain_returns_no_suggestions(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claim_search import suggested_claimable_events

        organizer = make_organizer()
        organizer.email = "promoter@gmail.com"

        result = await suggested_claimable_events(
            make_request(method="GET", path="/organizer/claims/suggestions"),
            current_organizer=organizer,
            db=mock_db,
            locale=None,
        )

        assert result["events"] == []
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_matches_event_url_domain(self, mock_db, make_event, make_request, make_organizer):
        from app.routers.organizer_claim_search import suggested_claimable_events

        organizer = make_organizer()
        organizer.email = "team@example-promoter.example"

        matching = make_event(event_id=1, title="Their show")
        matching.url = "https://tickets.example-promoter.example/event/1"
        matching.sources = [_make_source(event_id=1, publisher_id=1)]

        decoy = make_event(event_id=2, title="Someone else's show")
        decoy.url = "https://notexample-promoter.example/event/2"
        decoy.sources = [_make_source(event_id=2, publisher_id=2)]

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [matching, decoy]
        claim_keys_result = MagicMock()
        claim_keys_result.all.return_value = []
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        result = await suggested_claimable_events(
            make_request(method="GET", path="/organizer/claims/suggestions"),
            current_organizer=organizer,
            db=mock_db,
            locale=None,
        )

        assert [e["id"] for e in result["events"]] == [1]

    @pytest.mark.asyncio
    async def test_locale_param_localizes_result_titles(
        self, mock_db, make_event, make_request, make_organizer
    ):
        """(#454) locale=ru must localize a suggestion's title regardless of
        the organizer's stored locale."""
        from app.routers.organizer_claim_search import suggested_claimable_events

        organizer = make_organizer(organizer_id=5, locale="en")
        organizer.email = "team@example-promoter.example"

        matching = make_event(event_id=1, title="Their show")
        matching.title_localized = {"ru": "Их шоу"}
        matching.url = "https://tickets.example-promoter.example/event/1"
        matching.sources = [_make_source(event_id=1, publisher_id=1)]

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [matching]
        claim_keys_result = MagicMock()
        claim_keys_result.all.return_value = []
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        result = await suggested_claimable_events(
            make_request(method="GET", path="/organizer/claims/suggestions"),
            locale="ru",
            current_organizer=organizer,
            db=mock_db,
        )

        assert result["events"][0]["title"] == "Их шоу"
