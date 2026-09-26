"""Tests for routers/organizer_claim_edits.py (#416) — the claim-editing
surface's GET (load) and PATCH (save) endpoints. Exercised the same way as
test_organizer_claims.py: calling the endpoint functions directly against a
mocked db, with the heavier collaborators (own_claim_or_404,
claim_event_for_id, fetch_fresh_price, publish_pending,
apply_organizer_category) patched at the module namespace."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.claims.lifecycle import ClaimError
from app.claims.pinning import FreshPrice
from app.constants import (
    CLAIM_KIND_PUBLISHER,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_PENDING,
    ERROR_CLAIM_DORMANT,
    ERROR_CLAIM_EDIT_URL_DOMAIN,
    ERROR_CLAIM_NOT_GRANTED,
    ERROR_DAILY_CLAIM_EDIT_LIMIT,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    ORGANIZER_DAILY_CLAIM_EDIT_CAP,
)

MODULE = "app.routers.organizer_claim_edits"


def _fake_claim(**overrides) -> MagicMock:
    c = MagicMock()
    c.id = 1
    c.kind = CLAIM_KIND_PUBLISHER
    c.publisher_id = 99
    c.status = CLAIM_STATUS_APPROVED
    c.dormant = False
    c.verification_domain = None
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def _patched(**kwargs):
    """Context manager stacking the standard collaborator patches; kwargs
    override individual return/side-effect values."""
    defaults = {
        "own_claim_or_404": AsyncMock(return_value=_fake_claim()),
        "claim_event_for_id": AsyncMock(),
        "fetch_fresh_price": AsyncMock(return_value=None),
        "publish_pending": AsyncMock(return_value={"published": 1}),
        "apply_organizer_category": AsyncMock(),
    }
    defaults.update(kwargs)
    from contextlib import ExitStack

    stack = ExitStack()
    mocks = {}
    for name, mock in defaults.items():
        mocks[name] = stack.enter_context(patch(f"{MODULE}.{name}", mock))
    return stack, mocks


class TestGetClaimEvent:
    @pytest.mark.asyncio
    async def test_locked_until_granted(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claim_edits import get_claim_event

        organizer = make_organizer(organizer_id=5)
        stack, mocks = _patched(
            own_claim_or_404=AsyncMock(return_value=_fake_claim(status=CLAIM_STATUS_PENDING))
        )
        with stack:
            with pytest.raises(HTTPException) as exc:
                await get_claim_event(
                    1,
                    make_request(method="GET", path="/organizer/claims/1/event"),
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.CONFLICT
        assert exc.value.detail == ERROR_CLAIM_NOT_GRANTED

    @pytest.mark.asyncio
    async def test_locked_while_dormant(self, mock_db, make_request, make_organizer):
        """#422: a granted claim that has since gone dormant (lost a dedup
        collision to another claimed duplicate) must lock editing too, not
        just a not-yet-granted one."""
        from app.routers.organizer_claim_edits import get_claim_event

        organizer = make_organizer(organizer_id=5)
        stack, mocks = _patched(
            own_claim_or_404=AsyncMock(
                return_value=_fake_claim(status=CLAIM_STATUS_APPROVED, dormant=True)
            )
        )
        with stack:
            with pytest.raises(HTTPException) as exc:
                await get_claim_event(
                    1,
                    make_request(method="GET", path="/organizer/claims/1/event"),
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.CONFLICT
        assert exc.value.detail == ERROR_CLAIM_DORMANT

    @pytest.mark.asyncio
    async def test_claim_not_found_propagates_404(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claim_edits import get_claim_event

        organizer = make_organizer(organizer_id=5)
        stack, mocks = _patched(
            own_claim_or_404=AsyncMock(side_effect=ClaimError(http.HTTPStatus.NOT_FOUND, "x"))
        )
        with stack:
            with pytest.raises(HTTPException) as exc:
                await get_claim_event(
                    1,
                    make_request(method="GET", path="/organizer/claims/1/event"),
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_returns_pinned_fields_and_mismatch(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import get_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event()
        event.pinned_fields = ["title:et"]
        event.title_localized = {"et": "Pealkiri", "en": "Title"}
        event.description_localized = None
        fresh = FreshPrice(price_min=99.0, price_max=None, currency="EUR", has_free_tier=False)
        stack, mocks = _patched(
            claim_event_for_id=AsyncMock(return_value=event),
            fetch_fresh_price=AsyncMock(return_value=fresh),
        )
        with stack:
            result = await get_claim_event(
                1,
                make_request(method="GET", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        assert result["pinned_fields"] == ["title:et"]
        assert result["price_mismatch"]["price_min"] == 99.0
        assert result["title_localized"] == {"et": "Pealkiri", "en": "Title"}
        assert result["description_localized"] is None

    @pytest.mark.asyncio
    async def test_no_resolvable_event_is_404(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claim_edits import get_claim_event

        organizer = make_organizer(organizer_id=5)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=None))
        with stack:
            with pytest.raises(HTTPException) as exc:
                await get_claim_event(
                    1,
                    make_request(method="GET", path="/organizer/claims/1/event"),
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_event_id_for_covered_event_succeeds(
        self, mock_db, make_request, make_organizer, make_event
    ):
        """#437: an explicit event_id covered by the claim loads that event
        (never the always-returns-something claim_event_for_id mock, wired
        here to prove the id actually reaches the collaborator)."""
        from app.routers.organizer_claim_edits import get_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event(event_id=42)
        event.pinned_fields = []
        event.title_localized = None
        event.description_localized = None
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            result = await get_claim_event(
                1,
                make_request(method="GET", path="/organizer/claims/1/event"),
                event_id=42,
                current_organizer=organizer,
                db=mock_db,
            )
        mocks["claim_event_for_id"].assert_awaited_once()
        assert mocks["claim_event_for_id"].await_args.args[-1] == 42
        assert result["id"] == 42

    @pytest.mark.asyncio
    async def test_event_id_not_covered_by_claim_is_404(
        self, mock_db, make_request, make_organizer
    ):
        """An event outside the claim's scope 404s — matching the router's
        existing not-found convention rather than leaking whether the event
        exists at all."""
        from app.routers.organizer_claim_edits import get_claim_event

        organizer = make_organizer(organizer_id=5)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=None))
        with stack:
            with pytest.raises(HTTPException) as exc:
                await get_claim_event(
                    1,
                    make_request(method="GET", path="/organizer/claims/1/event"),
                    event_id=999,
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND


class TestUpdateClaimEvent:
    def _mock_db_for_save(self, mock_db, *, edits_today=0, final_status=EVENT_STATUS_PUBLISHED):
        reloaded = MagicMock()
        reloaded.id = 10
        reloaded.pinned_fields = []
        mock_db.scalar.side_effect = [edits_today, final_status, reloaded]
        return reloaded

    @pytest.mark.asyncio
    async def test_locked_until_granted(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        stack, mocks = _patched(
            own_claim_or_404=AsyncMock(return_value=_fake_claim(status=CLAIM_STATUS_PENDING))
        )
        with stack:
            with pytest.raises(HTTPException) as exc:
                await update_claim_event(
                    1,
                    PatchClaimEventBody(title="New title"),
                    make_request(method="PATCH", path="/organizer/claims/1/event"),
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.CONFLICT
        assert exc.value.detail == ERROR_CLAIM_NOT_GRANTED
        mocks["publish_pending"].assert_not_called()

    @pytest.mark.asyncio
    async def test_save_locked_while_dormant(
        self, mock_db, make_request, make_organizer
    ):
        """#422: PATCH must lock the same way GET does once the claim goes
        dormant — otherwise a save here would just get silently reverted by
        the next refetch pass."""
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        stack, mocks = _patched(
            own_claim_or_404=AsyncMock(
                return_value=_fake_claim(status=CLAIM_STATUS_APPROVED, dormant=True)
            )
        )
        with stack:
            with pytest.raises(HTTPException) as exc:
                await update_claim_event(
                    1,
                    PatchClaimEventBody(title="New title"),
                    make_request(method="PATCH", path="/organizer/claims/1/event"),
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.CONFLICT
        assert exc.value.detail == ERROR_CLAIM_DORMANT
        mocks["publish_pending"].assert_not_called()

    @pytest.mark.asyncio
    async def test_daily_edit_cap_returns_429(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event()
        event.pinned_fields = []
        mock_db.scalar.side_effect = [ORGANIZER_DAILY_CLAIM_EDIT_CAP]
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            with pytest.raises(HTTPException) as exc:
                await update_claim_event(
                    1,
                    PatchClaimEventBody(title="New title"),
                    make_request(method="PATCH", path="/organizer/claims/1/event"),
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.TOO_MANY_REQUESTS
        assert exc.value.detail == ERROR_DAILY_CLAIM_EDIT_LIMIT
        mocks["publish_pending"].assert_not_called()

    @pytest.mark.asyncio
    async def test_attempt_is_committed_before_a_later_404_can_roll_it_back(
        self, mock_db, make_request, make_organizer
    ):
        """The attempt row must survive even when the request 404s right
        after it — get_db's session has no commit-on-exit, so an eager
        commit is the only thing standing between this and a cap that never
        actually triggers for failing requests."""
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        mock_db.scalar.side_effect = [0]
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=None))
        with stack:
            with pytest.raises(HTTPException) as exc:
                await update_claim_event(
                    1,
                    PatchClaimEventBody(title="New title"),
                    make_request(method="PATCH", path="/organizer/claims/1/event"),
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    def test_blank_title_rejected(self):
        from app.routers.organizer_claim_edits import PatchClaimEventBody

        with pytest.raises(ValidationError):
            PatchClaimEventBody(title="   ")

    @pytest.mark.asyncio
    async def test_title_only_edit_never_fetches_source_price(
        self, mock_db, make_request, make_organizer, make_event
    ):
        """A save that has nothing to do with price must not pay for an
        outbound fetch of the event's third-party detail page."""
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event()
        event.pinned_fields = []
        self._mock_db_for_save(mock_db)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            await update_claim_event(
                1,
                PatchClaimEventBody(title="New title"),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        mocks["fetch_fresh_price"].assert_not_called()

    @pytest.mark.asyncio
    async def test_title_edit_pins_only_estonian_locale(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event()
        event.pinned_fields = []
        self._mock_db_for_save(mock_db)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            await update_claim_event(
                1,
                PatchClaimEventBody(title="Uus pealkiri"),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        assert event.pinned_fields == ["title:et"]
        assert event.title_orig == "Uus pealkiri"

    @pytest.mark.asyncio
    async def test_english_title_edit_pins_only_english_locale(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event()
        event.pinned_fields = []
        self._mock_db_for_save(mock_db)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            await update_claim_event(
                1,
                PatchClaimEventBody(title_en="New title"),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        assert event.pinned_fields == ["title:en"]

    @pytest.mark.asyncio
    async def test_unpin_removes_pin_without_touching_value(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event(title="Original title")
        event.pinned_fields = ["title:et", "url"]
        self._mock_db_for_save(mock_db)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            await update_claim_event(
                1,
                PatchClaimEventBody(unpin=["url"]),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        assert event.pinned_fields == ["title:et"]
        assert event.title_orig == "Original title"

    @pytest.mark.asyncio
    async def test_categories_prepend_only_delegates_to_shared_helper(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event(event_id=77)
        event.pinned_fields = []
        self._mock_db_for_save(mock_db)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            await update_claim_event(
                1,
                PatchClaimEventBody(category="music"),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        mocks["apply_organizer_category"].assert_awaited_once_with(mock_db, 77, "music")
        # Categories never pin.
        assert event.pinned_fields == []

    @pytest.mark.asyncio
    async def test_url_off_verified_domain_rejected(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event()
        event.pinned_fields = []
        claim = _fake_claim(verification_domain="fienta.ee")
        stack, mocks = _patched(
            own_claim_or_404=AsyncMock(return_value=claim),
            claim_event_for_id=AsyncMock(return_value=event),
        )
        mock_db.scalar.side_effect = [0]
        with stack:
            with pytest.raises(HTTPException) as exc:
                await update_claim_event(
                    1,
                    PatchClaimEventBody(url="https://evil.example.com/tickets"),
                    make_request(method="PATCH", path="/organizer/claims/1/event"),
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.BAD_REQUEST
        assert exc.value.detail == ERROR_CLAIM_EDIT_URL_DOMAIN

    @pytest.mark.asyncio
    async def test_url_on_verified_domain_accepted_and_pinned(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event()
        event.pinned_fields = []
        claim = _fake_claim(verification_domain="fienta.ee")
        self._mock_db_for_save(mock_db)
        stack, mocks = _patched(
            own_claim_or_404=AsyncMock(return_value=claim),
            claim_event_for_id=AsyncMock(return_value=event),
        )
        with stack:
            await update_claim_event(
                1,
                PatchClaimEventBody(url="https://fienta.ee/e/my-event"),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        assert event.url == "https://fienta.ee/e/my-event"
        assert "url" in event.pinned_fields

    @pytest.mark.asyncio
    async def test_event_id_for_covered_event_saves_and_pins(
        self, mock_db, make_request, make_organizer, make_event
    ):
        """#437: editing a specific covered event via event_id keeps the
        existing pinned-field behavior unchanged."""
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event(event_id=42)
        event.pinned_fields = []
        self._mock_db_for_save(mock_db)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            await update_claim_event(
                1,
                PatchClaimEventBody(event_id=42, title="New title"),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        mocks["claim_event_for_id"].assert_awaited_once()
        assert mocks["claim_event_for_id"].await_args.args[-1] == 42
        assert event.title_orig == "New title"
        assert "title:et" in event.pinned_fields

    @pytest.mark.asyncio
    async def test_event_id_not_covered_by_claim_is_404(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=None))
        mock_db.scalar.side_effect = [0]
        with stack:
            with pytest.raises(HTTPException) as exc:
                await update_claim_event(
                    1,
                    PatchClaimEventBody(event_id=999, title="New title"),
                    make_request(method="PATCH", path="/organizer/claims/1/event"),
                    current_organizer=organizer,
                    db=mock_db,
                )
        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_starts_at_edit_always_reruns_publish_gate(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from datetime import datetime, timezone

        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event(event_id=55)
        event.pinned_fields = []
        self._mock_db_for_save(mock_db, final_status=EVENT_STATUS_CLASSIFIED)
        new_starts_at = datetime(2026, 12, 1, 20, 0, tzinfo=timezone.utc)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            result = await update_claim_event(
                1,
                PatchClaimEventBody(starts_at=new_starts_at),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        assert event.starts_at == new_starts_at
        assert event.status == EVENT_STATUS_CLASSIFIED  # reset before the gate re-runs
        mocks["publish_pending"].assert_awaited_once_with(
            mock_db, event_ids=[55], diagnostics=False
        )
        # A failing edit stays at 'classified' in the response.
        assert result["status"] == EVENT_STATUS_CLASSIFIED

    @pytest.mark.asyncio
    async def test_passing_edit_flips_back_to_published(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event(event_id=55)
        event.pinned_fields = []
        self._mock_db_for_save(mock_db, final_status=EVENT_STATUS_PUBLISHED)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            result = await update_claim_event(
                1,
                PatchClaimEventBody(description="A new description"),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        assert result["status"] == EVENT_STATUS_PUBLISHED

    @pytest.mark.asyncio
    async def test_price_fields_never_pin(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event()
        event.pinned_fields = []
        self._mock_db_for_save(mock_db)
        stack, mocks = _patched(claim_event_for_id=AsyncMock(return_value=event))
        with stack:
            await update_claim_event(
                1,
                PatchClaimEventBody(price_min=25.0, price_max=35.0, currency="EUR"),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        assert event.price_min == 25.0
        assert event.price_max == 35.0
        assert event.pinned_fields == []

    @pytest.mark.asyncio
    async def test_accept_new_price_adopts_fresh_value(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.routers.organizer_claim_edits import PatchClaimEventBody, update_claim_event

        organizer = make_organizer(organizer_id=5)
        event = make_event(price_min=10.0)
        event.currency = "EUR"
        event.pinned_fields = []
        self._mock_db_for_save(mock_db)
        fresh = FreshPrice(price_min=20.0, price_max=30.0, currency="EUR", has_free_tier=False)
        stack, mocks = _patched(
            claim_event_for_id=AsyncMock(return_value=event),
            fetch_fresh_price=AsyncMock(return_value=fresh),
        )
        with stack:
            await update_claim_event(
                1,
                PatchClaimEventBody(accept_new_price=True),
                make_request(method="PATCH", path="/organizer/claims/1/event"),
                current_organizer=organizer,
                db=mock_db,
            )
        assert event.price_min == 20.0
        assert event.price_max == 30.0
        assert event.pinned_fields == []
