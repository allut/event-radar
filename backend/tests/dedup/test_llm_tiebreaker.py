"""Tests for app.dedup.llm_tiebreaker — stage-2 LLM dedup wiring."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.dedup.llm_tiebreaker as tiebreaker
import app.llm.router as router
from app.constants import TALLINN_TZ

_BASE = datetime(2026, 7, 1, 20, 0, 0, tzinfo=TALLINN_TZ)


def _event(
    eid: int,
    title: str = "Jazz Night",
    starts_at: datetime = _BASE,
    venue_name: str | None = None,
) -> MagicMock:
    e = MagicMock()
    e.id = eid
    e.title_orig = title
    e.starts_at = starts_at
    e.venue_name = venue_name
    e.status = "draft"
    e.dedup_group_id = None
    return e


def _wire_db(mock_db, events: list) -> None:
    result = MagicMock()
    result.all = MagicMock(return_value=events)
    mock_db.scalars.return_value = result


# ---------------------------------------------------------------------------
# llm_available
# ---------------------------------------------------------------------------


class TestLlmAvailable:
    def test_true_when_any_key_set(self, monkeypatch):
        monkeypatch.setattr(
            router,
            "settings",
            SimpleNamespace(GROQ_API_KEY="", CEREBRAS_API_KEY="k", MISTRAL_API_KEY=""),
        )
        assert router.llm_available() is True

    def test_false_when_no_keys(self, monkeypatch):
        monkeypatch.setattr(
            router,
            "settings",
            SimpleNamespace(GROQ_API_KEY="", CEREBRAS_API_KEY="", MISTRAL_API_KEY=""),
        )
        assert router.llm_available() is False


# ---------------------------------------------------------------------------
# _llm_confirms_pair
# ---------------------------------------------------------------------------


class TestLlmConfirmsPair:
    @pytest.mark.asyncio
    async def test_confirms_when_same_and_confident(self, mock_db, monkeypatch):
        monkeypatch.setattr(
            tiebreaker,
            "llm_json",
            AsyncMock(return_value=({"same": True, "confidence": 0.9}, "groq/x")),
        )
        assert await tiebreaker._llm_confirms_pair(_event(1), _event(2), mock_db) is True

    @pytest.mark.asyncio
    async def test_rejects_below_threshold(self, mock_db, monkeypatch):
        monkeypatch.setattr(
            tiebreaker,
            "llm_json",
            AsyncMock(return_value=({"same": True, "confidence": 0.5}, "groq/x")),
        )
        assert await tiebreaker._llm_confirms_pair(_event(1), _event(2), mock_db) is False

    @pytest.mark.asyncio
    async def test_rejects_when_not_same(self, mock_db, monkeypatch):
        monkeypatch.setattr(
            tiebreaker,
            "llm_json",
            AsyncMock(return_value=({"same": False, "confidence": 0.99}, "groq/x")),
        )
        assert await tiebreaker._llm_confirms_pair(_event(1), _event(2), mock_db) is False

    @pytest.mark.asyncio
    async def test_rejects_on_llm_error(self, mock_db, monkeypatch):
        monkeypatch.setattr(
            tiebreaker,
            "llm_json",
            AsyncMock(side_effect=router.LLMError("all providers failed")),
        )
        assert await tiebreaker._llm_confirms_pair(_event(1), _event(2), mock_db) is False

    @pytest.mark.asyncio
    async def test_rejects_on_bad_response(self, mock_db, monkeypatch):
        # confidence is non-numeric → float() raises ValueError → treated as distinct
        monkeypatch.setattr(
            tiebreaker,
            "llm_json",
            AsyncMock(return_value=({"same": True, "confidence": "high"}, "groq/x")),
        )
        assert await tiebreaker._llm_confirms_pair(_event(1), _event(2), mock_db) is False


# ---------------------------------------------------------------------------
# run_dedup_pass_llm
# ---------------------------------------------------------------------------


class TestRunDedupPassLlm:
    @pytest.mark.asyncio
    async def test_falls_back_to_rule_only_without_provider(self, mock_db, monkeypatch):
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: False)
        sentinel = {"total": 3, "grouped": 2, "groups": 1, "updated": 2}
        rule_only = AsyncMock(return_value=sentinel)
        monkeypatch.setattr(tiebreaker, "run_dedup_pass", rule_only)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        rule_only.assert_awaited_once_with(mock_db)
        # Stage-2 path never touched the DB or the LLM
        mock_db.scalars.assert_not_called()
        # Documented stage-2 summary shape must hold on the fallback path too
        assert result["candidate_pairs"] == 0
        assert result["llm_confirmed"] == 0
        assert result["grouped"] == 2
        assert result["updated"] == 2

    @pytest.mark.asyncio
    async def test_empty_window_returns_zeros(self, mock_db, monkeypatch):
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        _wire_db(mock_db, [])

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["total"] == 0
        assert result["candidate_pairs"] == 0
        assert result["llm_confirmed"] == 0

    @pytest.mark.asyncio
    async def test_confirmed_pair_is_grouped(self, mock_db, monkeypatch):
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a, b = _event(1), _event(2)
        _wire_db(mock_db, [a, b])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", AsyncMock(return_value=True))

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 1
        assert result["llm_confirmed"] == 1
        assert result["grouped"] == 2
        assert result["groups"] == 1
        assert result["updated"] == 2
        assert a.dedup_group_id == 1
        assert b.dedup_group_id == 1

    @pytest.mark.asyncio
    async def test_rejected_pair_is_not_grouped(self, mock_db, monkeypatch):
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a, b = _event(1), _event(2)
        _wire_db(mock_db, [a, b])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        monkeypatch.setattr(
            tiebreaker, "_llm_confirms_pair", AsyncMock(return_value=False)
        )

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 1
        assert result["llm_confirmed"] == 0
        assert result["grouped"] == 0
        assert a.dedup_group_id is None
        assert b.dedup_group_id is None

    @pytest.mark.asyncio
    async def test_pair_failing_fuzzy_check_skips_llm(self, mock_db, monkeypatch):
        # SQL time-window pre-filter returns the pair, but titles differ enough
        # that is_candidate_pair rejects it → LLM is never consulted.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a = _event(1, title="Jazz Night")
        b = _event(2, title="Completely Different Circus Show")
        _wire_db(mock_db, [a, b])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        confirm = AsyncMock(return_value=True)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 0
        confirm.assert_not_called()

    @pytest.mark.asyncio
    async def test_candidate_pair_cap_bounds_llm_calls(self, mock_db, monkeypatch):
        # cap=2 with 3 fuzzy-matching pairs → only 2 reach the LLM, and the
        # reported candidate_pairs never exceeds the cap.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        monkeypatch.setattr(tiebreaker, "LLM_DEDUP_MAX_CANDIDATE_PAIRS_PER_PASS", 2)
        events = [_event(1), _event(2), _event(3)]
        _wire_db(mock_db, events)
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2), (1, 3), (2, 3)]),
        )
        confirm = AsyncMock(return_value=False)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 2
        assert confirm.await_count == 2
