"""Promotion restriction (#612): fill gate clause 6 with a Restriction clearance,
the grant requirement, clearing a newly flagged Promotion, the admin notice,
the backfill and the "Promoted" report tagging."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.constants.llm import LLM_BATCH_FANOUT_CONCURRENCY
from app._generated.shared_constants import PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED
from app.constants.promotions import (
    PROMOTION_ERROR_CLEARANCE_NOTE_REQUIRED,
    PROMOTION_ERROR_CLEARANCE_NOT_NEEDED,
    PROMOTION_ERROR_CLEARANCE_REQUIRED,
    PROMOTION_STATUS_PAID,
)
from app.constants.reports import REPORT_STATUS_OPEN
from app.db import get_db
from app.models.events import Event, EventReport
from app.models.promotions import Promotion
from app.models.organizers import Venue
from app.models.users import User
from app.promotions.fill import evaluate_gate
from app.promotions.grant import GrantRequest, PromotionRefused, grant_promotion
from app.promotions.restriction import (
    backfill_restrictions,
    notify_newly_restricted,
    parse_promotion_restriction,
)
from app.routers import reports as reports_router
from tests.conftest import count_statements
from tests.promotions.conftest import NOW, d
from tests.promotions.test_explore_slot import classified, promote

LIVE_NOW = NOW.replace(day=3)  # inside promote()'s 2090-01-01..05 window


def req(**kw: Any) -> GrantRequest:
    return GrantRequest(d(10), d(12), "Acme Events OÜ", "12345678", **kw)


async def refused_codes(db, event, request) -> list[str]:
    with pytest.raises(PromotionRefused) as exc:
        await grant_promotion(db, event, request, NOW)
    return [v.code for v in exc.value.violations]


class TestParse:
    def test_valid_values_pass_through(self) -> None:
        assert parse_promotion_restriction("gambling") == "gambling"
        assert parse_promotion_restriction(" None ") == "none"

    @pytest.mark.parametrize("raw", [None, "", "drugs", 3, ["tobacco"]])
    def test_anything_else_is_unassessed(self, raw: Any) -> None:
        assert parse_promotion_restriction(raw) is None


class TestGateClause6:
    async def reason(self, db, make, restriction, cleared) -> str | None:
        org = await make.organizer()
        ev = await classified(make, org=org)
        ev.promotion_restriction = restriction
        promo = await promote(db, ev, org, restriction_cleared=cleared)
        [result] = await evaluate_gate(db, [promo], LIVE_NOW)
        return result.reason

    @pytest.mark.asyncio
    async def test_clearance_covering_the_restriction_lets_it_show(self, db, make) -> None:
        assert await self.reason(db, make, "gambling", "gambling") is None

    @pytest.mark.asyncio
    async def test_clearance_covers_only_its_own_restriction(self, db, make) -> None:
        assert (
            await self.reason(db, make, "tobacco", "gambling")
            == PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED
        )

    @pytest.mark.asyncio
    async def test_newly_flagged_live_promotion_pauses(self, db, make) -> None:
        org = await make.organizer()
        ev = await classified(make, org=org)
        ev.promotion_restriction = "none"
        promo = await promote(db, ev, org)
        assert (await evaluate_gate(db, [promo], LIVE_NOW))[0].reason is None
        ev.promotion_restriction = "alcohol"
        await db.flush()
        assert (
            await evaluate_gate(db, [promo], LIVE_NOW)
        )[0].reason == PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED


class TestGrantClearance:
    @pytest.mark.asyncio
    async def test_restricted_event_needs_checkbox_and_note(self, db, make) -> None:
        ev = await make.event(submitted_by=await make.organizer(), promotion_restriction="alcohol")
        assert await refused_codes(db, ev, req()) == [
            PROMOTION_ERROR_CLEARANCE_REQUIRED,
            PROMOTION_ERROR_CLEARANCE_NOTE_REQUIRED,
        ]
        assert await refused_codes(
            db, ev, req(restriction_clearance_confirmed=True)
        ) == [PROMOTION_ERROR_CLEARANCE_NOTE_REQUIRED]
        assert await refused_codes(
            db, ev, req(restriction_clearance_note="ok")
        ) == [PROMOTION_ERROR_CLEARANCE_REQUIRED]

    @pytest.mark.asyncio
    async def test_clearance_is_recorded_on_the_promotion(self, db, make) -> None:
        ev = await make.event(submitted_by=await make.organizer(), promotion_restriction="alcohol")
        promo = await grant_promotion(
            db,
            ev,
            req(restriction_clearance_confirmed=True, restriction_clearance_note=" tasting only "),
            NOW,
        )
        assert promo.restriction_cleared == "alcohol"
        assert promo.restriction_clearance_by == "admin"
        assert promo.restriction_clearance_note == "tasting only"
        assert promo.restriction_cleared_at == NOW

    @pytest.mark.asyncio
    @pytest.mark.parametrize("restriction", ["none", None])
    async def test_clear_or_unassessed_event_needs_no_clearance(
        self, db, make, restriction
    ) -> None:
        ev = await make.event(
            submitted_by=await make.organizer(), promotion_restriction=restriction
        )
        promo = await grant_promotion(db, ev, req(), NOW)
        assert promo.restriction_cleared is None

    API_BODY = {
        "start_date": d(10).isoformat(),
        "end_date": d(12).isoformat(),
        "advertiser_legal_name": "Acme Events OÜ",
        "advertiser_registry_code": "12345678",
    }

    @pytest.mark.asyncio
    async def test_api_refuses_without_clearance(self, client, db, make) -> None:
        ev = await make.event(submitted_by=await make.organizer(), promotion_restriction="weapons")
        resp = await client.post(f"/admin/events/{ev.id}/promotions", json=self.API_BODY)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == PROMOTION_ERROR_CLEARANCE_REQUIRED

    @pytest.mark.asyncio
    async def test_api_records_clearance(self, client, db, make) -> None:
        ev = await make.event(submitted_by=await make.organizer(), promotion_restriction="weapons")
        body = self.API_BODY
        resp = await client.post(
            f"/admin/events/{ev.id}/promotions",
            json={**body, "restriction_clearance_confirmed": True, "restriction_clearance_note": "ok"},
        )
        assert resp.status_code == 201
        assert resp.json()["restriction_clearance"]["restriction"] == "weapons"
        context = (await client.get(f"/admin/events/{ev.id}/promotion-context")).json()
        assert context["promotion_restriction"] == "weapons"


class TestClearNewlyFlagged:
    async def flagged_live(self, db, make) -> tuple[Promotion, Any]:
        org = await make.organizer()
        ev = await classified(make, org=org)
        ev.promotion_restriction = "gambling"
        return await promote(db, ev, org), ev

    @pytest.mark.asyncio
    async def test_clear_resumes_it(self, client, db, make) -> None:
        from app.routers import admin_promotion_commands as commands_module  # noqa: F401
        from tests.promotions.conftest import Clock

        promo, ev = await self.flagged_live(db, make)
        Clock.now = LIVE_NOW
        resp = await client.post(f"/admin/promotions/{promo.id}/clear-restriction", json={"note": "licensed"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["restriction_clearance"]["restriction"] == "gambling"
        await db.refresh(promo)
        assert (await evaluate_gate(db, [promo], LIVE_NOW))[0].reason is None

    @pytest.mark.asyncio
    async def test_clear_needs_a_note(self, client, db, make) -> None:
        from tests.promotions.conftest import Clock

        promo, ev = await self.flagged_live(db, make)
        Clock.now = LIVE_NOW
        resp = await client.post(f"/admin/promotions/{promo.id}/clear-restriction", json={"note": "  "})
        assert resp.json()["detail"]["code"] == PROMOTION_ERROR_CLEARANCE_NOTE_REQUIRED

    @pytest.mark.asyncio
    async def test_clear_needs_a_restricted_event(self, client, db, make) -> None:
        from tests.promotions.conftest import Clock

        promo, ev = await self.flagged_live(db, make)
        Clock.now = LIVE_NOW
        ev.promotion_restriction = "none"
        await db.flush()
        resp = await client.post(f"/admin/promotions/{promo.id}/clear-restriction", json={"note": "x"})
        assert resp.json()["detail"]["code"] == PROMOTION_ERROR_CLEARANCE_NOT_NEEDED

    @pytest.mark.asyncio
    async def test_notice_goes_out_for_newly_flagged_uncleared_only(self, db, make) -> None:
        org = await make.organizer()
        newly = await classified(make, org=org)
        newly.promotion_restriction = "tobacco"
        cleared = await classified(make, 1, org=org)
        cleared.promotion_restriction = "tobacco"
        unchanged = await classified(make, 2, org=org)
        unchanged.promotion_restriction = "tobacco"
        p_new = await promote(db, newly, org)
        await promote(db, cleared, org, restriction_cleared="tobacco")
        await promote(db, unchanged, org)
        with patch(
            "app.promotions.restriction.send_restriction_flagged_notice", new=AsyncMock()
        ) as send:
            notified = await notify_newly_restricted(
                db, [(newly, "none"), (cleared, None), (unchanged, "tobacco")], LIVE_NOW
            )
        assert notified == [p_new.id]
        assert send.await_count == 1

    @pytest.mark.asyncio
    async def test_notices_share_one_client_and_survive_a_failure(self, db, make) -> None:
        org = await make.organizer()
        events = [await classified(make, i, org=org) for i in range(3)]
        promos = []
        for ev in events:
            ev.promotion_restriction = "tobacco"
            promos.append(await promote(db, ev, org))
        clients: list[object] = []

        @asynccontextmanager
        async def one_client():
            client = object()
            clients.append(client)
            yield client

        async def send(promotion, event, restriction, *, http_client=None):
            assert http_client is clients[0]
            if promotion.id == promos[1].id:
                raise RuntimeError("resend down")

        with (
            patch("app.promotions.restriction.resend_http_client", new=one_client),
            patch("app.promotions.restriction.send_restriction_flagged_notice", new=send),
        ):
            notified = await notify_newly_restricted(
                db, [(ev, "none") for ev in events], LIVE_NOW
            )
        assert len(clients) == 1
        assert notified == [promos[0].id, promos[2].id]

    @pytest.mark.asyncio
    async def test_notice_email_has_contact_address_and_deep_link(
        self, db, make, monkeypatch
    ) -> None:
        from app.email import promotion_admin

        org = await make.organizer()
        ev = await classified(make, org=org)
        ev.promotion_restriction = "political"
        promo = await promote(db, ev, org)
        monkeypatch.setattr(promotion_admin.settings, "CONTACT_TO_ADDRESS", "owner@radar.example")
        monkeypatch.setattr(promotion_admin.settings, "FRONTEND_URL", "https://radar.example")
        with patch.object(promotion_admin, "send_resend_email", new=AsyncMock()) as send:
            await promotion_admin.send_restriction_flagged_notice(promo, ev, "political")
        payload = send.await_args.args[0]
        assert payload["to"] == ["owner@radar.example"]
        assert f"https://radar.example/admin/promotions/{promo.id}" in payload["text"]
        assert "political" in payload["subject"]


def alcohol_answer() -> AsyncMock:
    """A provider `post` that always answers `alcohol`."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": '{"promotion_restriction": "alcohol"}'}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }
    return AsyncMock(return_value=resp)


@contextmanager
def groq_only(post: AsyncMock) -> Iterator[None]:
    """Run the real `llm_json` (cache lookup included) against one fake provider."""
    with (
        patch("app.llm.router.settings") as cfg,
        patch("httpx.AsyncClient.post", post),
    ):
        cfg.GROQ_API_KEY = "gsk_test"
        cfg.CLOUDFLARE_WORKERS_AI_API_KEY = ""
        cfg.CLOUDFLARE_WORKERS_AI_BASE_URL = ""
        cfg.MISTRAL_API_KEY = ""
        yield


class TestAssessAgainstRealTable:
    @pytest.mark.asyncio
    async def test_llm_call_row_persists_and_second_assess_hits_cache(self, db, make) -> None:
        from sqlalchemy import func, select

        from app.models.llm import LlmCall
        from app.promotions.restriction import assess_events

        ev = await make.event(submitted_by=await make.organizer())
        post = alcohol_answer()
        with groq_only(post):
            await assess_events(db, [ev])
            await db.flush()
            assert ev.promotion_restriction == "alcohol"
            ev.promotion_restriction = None
            await assess_events(db, [ev])
            await db.flush()
        assert ev.promotion_restriction == "alcohol"
        assert post.await_count == 1
        rows = await db.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.event_id == ev.id))
        assert rows == 1


class TestBackfill:
    @pytest.mark.asyncio
    async def test_assesses_owned_unended_unassessed_once(self, db, make) -> None:
        org = await make.organizer()
        owned = await make.event(submitted_by=org)
        unowned = await make.event()
        done = await make.event(submitted_by=org, promotion_restriction="none")
        answers = AsyncMock(return_value=({"promotion_restriction": "gambling"}, "groq/x"))
        with patch("app.promotions.restriction.llm_json_or_none", answers):
            first = await backfill_restrictions(db, NOW)
            second = await backfill_restrictions(db, NOW)
        assert owned.promotion_restriction == "gambling"
        assert unowned.promotion_restriction is None
        assert done.promotion_restriction == "none"
        assert first["assessed"] >= 1
        assert second["assessed"] == 0 or second["assessed"] <= first["assessed"] - 1
        assert answers.await_count == first["assessed"]  # idempotent: no re-assess

    @pytest.mark.asyncio
    async def test_fresh_page_wider_than_the_fan_out_is_fully_assessed(self, db, make) -> None:
        """The backfill script's shape: a fresh session (venues not loaded) and
        more events than LLM_BATCH_FANOUT_CONCURRENCY, through the real
        `llm_json`. Every event is assessed, its linked venue reaches the prompt,
        and the fan-out issues no per-event cache SELECT on the shared session."""
        org = await make.organizer()
        venue = Venue(organizer_id=org.id, name="Kultuurikatel")
        db.add(venue)
        await db.flush()
        events = [
            await make.event(submitted_by=org, venue_id=venue.id)
            for _ in range(LLM_BATCH_FANOUT_CONCURRENCY + 2)
        ]
        ids = [e.id for e in events]
        db.expunge_all()
        post = alcohol_answer()
        with groq_only(post), count_statements(db) as statements:
            await backfill_restrictions(db, NOW)
        assessed = (await db.scalars(select(Event).where(Event.id.in_(ids)))).all()
        assert [e.promotion_restriction for e in assessed] == ["alcohol"] * len(ids)
        assert post.await_count == len(ids)
        prompt = post.await_args.kwargs["json"]["messages"][0]["content"]
        assert "Kultuurikatel" in prompt
        cache_lookups = [s for s in statements if "FROM llm_calls" in s]
        assert len(cache_lookups) == 1

    @pytest.mark.asyncio
    async def test_llm_outage_leaves_event_unassessed(self, db, make) -> None:
        owned = await make.event(submitted_by=await make.organizer())
        with patch("app.promotions.restriction.llm_json_or_none", AsyncMock(return_value=None)):
            await backfill_restrictions(db, NOW)
        assert owned.promotion_restriction is None


@pytest_asyncio.fixture
async def report_client(db) -> AsyncIterator[AsyncClient]:
    user = User(email="reporter-612@example.com")
    db.add(user)
    await db.flush()
    app = FastAPI()
    app.include_router(reports_router.router)

    async def _db() -> AsyncIterator[Any]:
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestPromotedReports:
    @pytest.mark.asyncio
    async def test_queue_tags_and_sorts_promoted_first(self, client, db, make) -> None:
        from tests.promotions.conftest import Clock

        org = await make.organizer()
        plain = await classified(make, org=org)
        promoted = await classified(make, 1, org=org)
        await promote(db, promoted, org)
        reporter = User(email="rep-queue-612@example.com")
        db.add(reporter)
        await db.flush()
        for ev, illegal in ((plain, True), (promoted, False)):
            db.add(
                EventReport(
                    user_id=reporter.id,
                    event_id=ev.id,
                    reason="spam_or_scam",
                    is_illegal_allegation=illegal,
                    status=REPORT_STATUS_OPEN,
                )
            )
        await db.flush()
        Clock.now = LIVE_NOW
        rows = (await client.get("/admin/reports", params={"limit": 500})).json()["events"]
        ids = [r["event_id"] for r in rows]
        assert ids.index(promoted.id) < ids.index(plain.id)  # beats illegal-first
        by_id = {r["event_id"]: r for r in rows}
        assert by_id[promoted.id]["is_promoted"] is True
        assert by_id[plain.id]["is_promoted"] is False

    @pytest.mark.asyncio
    async def test_notify_subject_gains_promoted_marker(self, report_client, db, make, monkeypatch) -> None:
        org = await make.organizer()
        ev = await classified(make, org=org)
        await promote(db, ev, org)
        monkeypatch.setattr(reports_router, "now_tallinn", lambda: LIVE_NOW)
        with patch.object(reports_router, "send_report_notification", new=AsyncMock()) as send:
            resp = await report_client.post(
                "/reports", json={"event_id": ev.id, "reason": "spam_or_scam"}
            )
        assert resp.status_code == 200
        assert send.await_args.kwargs["is_promoted"] is True

    @pytest.mark.asyncio
    async def test_report_never_pauses_a_promotion(self, report_client, db, make, monkeypatch) -> None:
        org = await make.organizer()
        ev = await classified(make, org=org)
        ev.promotion_restriction = "none"
        promo = await promote(db, ev, org)
        monkeypatch.setattr(reports_router, "now_tallinn", lambda: LIVE_NOW)
        with patch.object(reports_router, "send_report_notification", new=AsyncMock()):
            await report_client.post("/reports", json={"event_id": ev.id, "reason": "spam_or_scam"})
        await db.refresh(promo)
        assert promo.status == PROMOTION_STATUS_PAID
        [result] = await evaluate_gate(db, [promo], LIVE_NOW)
        # The reporter's own report only excludes it for that viewer; the gate is untouched.
        assert result.reason is None
