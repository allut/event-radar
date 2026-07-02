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
    make_event_fn,
    eid: int,
    title: str | None = None,
    starts_at: datetime = _BASE,
    venue_name: str | None = None,
) -> MagicMock:
    # Default to a per-eid title so two default events have DISTINCT normalized
    # titles (not collapsed by apply_same_day_title_unions) yet still fuzzy-match
    # >= TITLE_RATIO_VENUE_BYPASS_THRESHOLD, so they reach the LLM via the venue
    # bypass — these tests exercise the cache/budget machinery, not same-day
    # collapse. Tests that need an identical title pass it explicitly.
    # Quality fields set to None/"" so all events rank equally and tie-break
    # keeps min(id), preserving the existing dedup_group_id assertions below.
    return make_event_fn(
        event_id=eid,
        title=title if title is not None else f"Jazz Night {eid}",
        starts_at=starts_at,
        venue_name=venue_name,
        status="draft",
        venue_address=None,
        lat=None,
        lng=None,
        description_orig="",
    )


def _wire_db(mock_db, events: list) -> None:
    result = MagicMock()
    result.all = MagicMock(return_value=events)
    mock_db.scalars.return_value = result


def _wire_execute(mock_db, rows: list | None = None) -> None:
    """Wire mock_db.execute(...).all() to return the given rows.

    Used for the bulk prefetch query in _prefetch_cached_decisions; rows are
    (content_hash, response_json) tuples. The final stale-group-id update
    statement also calls db.execute, but its return value is unused.
    """
    result = MagicMock()
    result.all = MagicMock(return_value=rows or [])
    mock_db.execute.return_value = result


def _hash_by_ids(a, b) -> str:
    return f"hash-{a.id}-{b.id}"


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
    async def test_confirms_when_same_and_confident(self, mock_db, monkeypatch, make_event):
        monkeypatch.setattr(
            tiebreaker,
            "llm_json",
            AsyncMock(return_value=({"same": True, "confidence": 0.9}, "groq/x")),
        )
        assert await tiebreaker._llm_confirms_pair(_event(make_event, 1), _event(make_event, 2), mock_db) is True

    @pytest.mark.asyncio
    async def test_rejects_below_threshold(self, mock_db, monkeypatch, make_event):
        monkeypatch.setattr(
            tiebreaker,
            "llm_json",
            AsyncMock(return_value=({"same": True, "confidence": 0.5}, "groq/x")),
        )
        assert await tiebreaker._llm_confirms_pair(_event(make_event, 1), _event(make_event, 2), mock_db) is False

    @pytest.mark.asyncio
    async def test_rejects_when_not_same(self, mock_db, monkeypatch, make_event):
        monkeypatch.setattr(
            tiebreaker,
            "llm_json",
            AsyncMock(return_value=({"same": False, "confidence": 0.99}, "groq/x")),
        )
        assert await tiebreaker._llm_confirms_pair(_event(make_event, 1), _event(make_event, 2), mock_db) is False

    @pytest.mark.asyncio
    async def test_rejects_on_llm_error(self, mock_db, monkeypatch, make_event):
        monkeypatch.setattr(
            tiebreaker,
            "llm_json",
            AsyncMock(side_effect=router.LLMError("all providers failed")),
        )
        assert await tiebreaker._llm_confirms_pair(_event(make_event, 1), _event(make_event, 2), mock_db) is False

    @pytest.mark.asyncio
    async def test_rejects_on_bad_response(self, mock_db, monkeypatch, make_event):
        # confidence is non-numeric → float() raises ValueError → treated as distinct
        monkeypatch.setattr(
            tiebreaker,
            "llm_json",
            AsyncMock(return_value=({"same": True, "confidence": "high"}, "groq/x")),
        )
        assert await tiebreaker._llm_confirms_pair(_event(make_event, 1), _event(make_event, 2), mock_db) is False


# ---------------------------------------------------------------------------
# _verdict_confirms
# ---------------------------------------------------------------------------


class TestVerdictConfirms:
    def test_confirms_when_same_and_confident(self):
        assert tiebreaker._verdict_confirms({"same": True, "confidence": 0.9}) is True

    def test_rejects_when_not_same(self):
        assert tiebreaker._verdict_confirms({"same": False, "confidence": 0.99}) is False

    def test_rejects_below_threshold(self):
        assert tiebreaker._verdict_confirms({"same": True, "confidence": 0.5}) is False

    def test_raises_on_malformed_confidence(self):
        with pytest.raises(ValueError):
            tiebreaker._verdict_confirms({"same": True, "confidence": "high"})


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
        assert result["fresh_calls"] == 0
        assert result["deferred_pairs"] == 0
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
        assert result["fresh_calls"] == 0
        assert result["deferred_pairs"] == 0

    @pytest.mark.asyncio
    async def test_confirmed_pair_is_grouped(self, mock_db, monkeypatch, make_event):
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a, b = _event(make_event, 1), _event(make_event, 2)
        _wire_db(mock_db, [a, b])
        _wire_execute(mock_db, [])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", AsyncMock(return_value=True))

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 1
        assert result["llm_confirmed"] == 1
        assert result["fresh_calls"] == 1
        assert result["deferred_pairs"] == 0
        assert result["grouped"] == 2
        assert result["groups"] == 1
        assert result["updated"] == 2
        assert a.dedup_group_id == 1
        assert b.dedup_group_id == 1

    @pytest.mark.asyncio
    async def test_rejected_pair_is_not_grouped(self, mock_db, monkeypatch, make_event):
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a, b = _event(make_event, 1), _event(make_event, 2)
        _wire_db(mock_db, [a, b])
        _wire_execute(mock_db, [])
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
        assert result["fresh_calls"] == 1
        assert result["deferred_pairs"] == 0
        assert result["grouped"] == 0
        assert a.dedup_group_id is None
        assert b.dedup_group_id is None

    @pytest.mark.asyncio
    async def test_pair_failing_fuzzy_check_skips_llm(self, mock_db, monkeypatch, make_event):
        # SQL time-window pre-filter returns the pair, but titles differ enough
        # and venues are incompatible, so is_candidate_pair rejects it under both
        # bypasses → LLM is never consulted. (Distinct, incompatible venues also
        # rule out the exact-time-and-venue title bypass, not just the fuzzy gate.)
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a = _event(make_event, 1, title="Jazz Night", venue_name="Von Krahli")
        b = _event(make_event, 2, title="Completely Different Circus Show", venue_name="Fotografiska")
        _wire_db(mock_db, [a, b])
        _wire_execute(mock_db, [])
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
    async def test_strong_title_venue_mismatch_pair_survives_to_llm(
        self, mock_db, monkeypatch, make_event
    ):
        # Near-exact title, same time, different venue spellings — the rule-only
        # gate would reject this, but the LLM path's bypass_venue_on_near_exact_title
        # lets it survive to the LLM, which confirms and merges it.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a = _event(make_event, 1, title="Klassikatähed", venue_name="Estonia Concert Hall")
        b = _event(make_event, 2, title="Klassikatähed", venue_name="Eesti Kontsert")
        _wire_db(mock_db, [a, b])
        _wire_execute(mock_db, [])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        confirm = AsyncMock(return_value=True)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 1
        confirm.assert_awaited_once()
        assert result["llm_confirmed"] == 1
        assert a.dedup_group_id == 1
        assert b.dedup_group_id == 1

    @pytest.mark.asyncio
    async def test_same_day_identical_title_grouped_without_llm(
        self, mock_db, monkeypatch, make_event
    ):
        # Two same-title, same-day, same-venue slots are collapsed deterministically
        # by apply_same_day_title_unions before the tiebreaker, so the LLM is never
        # consulted for the pair (Fix 1 removes the timed-entry storm) — yet they
        # are still grouped.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a = _event(make_event, 1, title="Van Gogh", venue_name="Vaba Lava")
        b = _event(make_event, 2, title="Van Gogh", venue_name="Vaba Lava")
        _wire_db(mock_db, [a, b])
        _wire_execute(mock_db, [])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        confirm = AsyncMock(return_value=True)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 0
        assert result["fresh_calls"] == 0
        confirm.assert_not_called()
        assert result["grouped"] == 2
        assert result["groups"] == 1
        assert a.dedup_group_id == 1
        assert b.dedup_group_id == 1

    @pytest.mark.asyncio
    async def test_cross_language_near_title_reaches_llm(self, mock_db, monkeypatch, make_event):
        # Different normalized titles (ratio in [85, 90)) at cross-language venue
        # spellings: not collapsed by the same-day union, but Fix 2's lowered
        # bypass threshold lets the pair survive the venue gate and reach the LLM.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a = _event(
            make_event, 1, title="Bach Cantata Evening Series", venue_name="Estonia kontserdisaal"
        )
        b = _event(
            make_event, 2, title="Bach Cantata Evening Show", venue_name="Estonia Concert Hall"
        )
        _wire_db(mock_db, [a, b])
        _wire_execute(mock_db, [])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        confirm = AsyncMock(return_value=True)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 1
        confirm.assert_awaited_once()
        assert result["llm_confirmed"] == 1

    @pytest.mark.asyncio
    async def test_cross_language_titles_exact_slot_reaches_llm_and_merges(
        self, mock_db, monkeypatch, make_event
    ):
        # The 142/143/144 case: three completely different-language titles at an
        # identical starts_at/venue. token_set_ratio is near 0 — only the new
        # bypass_title_on_exact_time_and_venue path gets this to the LLM.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a = _event(make_event, 1, title="Energia avastuskeskuse sissepääsupilet", venue_name="Energia avastuskeskus")
        b = _event(make_event, 2, title="Входной билет Познавательного центра", venue_name="Energia avastuskeskus")
        c = _event(make_event, 3, title="Entrance ticket to Energy Discovery Centre", venue_name="Energia avastuskeskus")
        _wire_db(mock_db, [a, b, c])
        _wire_execute(mock_db, [])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2), (1, 3), (2, 3)]),
        )
        confirm = AsyncMock(return_value=True)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 3
        assert result["llm_confirmed"] == 3
        assert a.dedup_group_id == 1
        assert b.dedup_group_id == 1
        assert c.dedup_group_id == 1

    @pytest.mark.asyncio
    async def test_distinct_products_same_slot_reach_llm_but_stay_unmerged(
        self, mock_db, monkeypatch, make_event
    ):
        # False-positive pattern found in the DB scan (Pirita Seikluspark ticket
        # vs gift card): same venue/exact time survives the new bypass and
        # reaches the LLM, but the (mocked) LLM correctly says "different" and
        # no merge happens.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a = _event(make_event, 1, title="Piletid Pirita Seiklusparki", venue_name="Pirita Seikluspark")
        b = _event(make_event, 2, title="Kinkekaart Pirita Seiklusparki", venue_name="Pirita Seikluspark")
        _wire_db(mock_db, [a, b])
        _wire_execute(mock_db, [])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        confirm = AsyncMock(return_value=False)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 1
        confirm.assert_awaited_once()
        assert result["llm_confirmed"] == 0
        assert a.dedup_group_id is None
        assert b.dedup_group_id is None

    @pytest.mark.asyncio
    async def test_fresh_call_cap_bounds_network_calls(self, mock_db, monkeypatch, make_event):
        # cap=2 with 3 cache-miss fuzzy-matching pairs → only 2 reach the LLM,
        # the 3rd is deferred, and the loop does NOT break (candidate_pairs==3).
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        monkeypatch.setattr(tiebreaker, "LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS", 2)
        events = [_event(make_event, 1), _event(make_event, 2), _event(make_event, 3)]
        _wire_db(mock_db, events)
        _wire_execute(mock_db, [])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2), (1, 3), (2, 3)]),
        )
        confirm = AsyncMock(return_value=False)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 3
        assert result["fresh_calls"] == 2
        assert result["deferred_pairs"] == 1
        assert confirm.await_count == 2

    @pytest.mark.asyncio
    async def test_cached_pairs_do_not_consume_fresh_budget(self, mock_db, monkeypatch, make_event):
        # cap=1, 2 cached + 1 fresh pair → all decided, fresh_calls==1.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        monkeypatch.setattr(tiebreaker, "LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS", 1)
        events = [_event(make_event, 1), _event(make_event, 2), _event(make_event, 3)]
        _wire_db(mock_db, events)
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2), (1, 3), (2, 3)]),
        )
        monkeypatch.setattr(tiebreaker, "_dedup_pair_hash", _hash_by_ids)
        _wire_execute(
            mock_db,
            [
                ("hash-1-2", {"same": True, "confidence": 0.9}),
                ("hash-1-3", {"same": True, "confidence": 0.9}),
            ],
        )
        confirm = AsyncMock(return_value=True)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["fresh_calls"] == 1
        assert result["deferred_pairs"] == 0
        assert result["llm_confirmed"] == 3
        confirm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cached_reject_is_respected(self, mock_db, monkeypatch, make_event):
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a, b = _event(make_event, 1), _event(make_event, 2)
        _wire_db(mock_db, [a, b])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        monkeypatch.setattr(tiebreaker, "_dedup_pair_hash", _hash_by_ids)
        _wire_execute(mock_db, [("hash-1-2", {"same": False, "confidence": 0.95})])
        confirm = AsyncMock(return_value=True)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["llm_confirmed"] == 0
        assert result["fresh_calls"] == 0
        assert a.dedup_group_id is None
        assert b.dedup_group_id is None
        confirm.assert_not_called()

    @pytest.mark.asyncio
    async def test_high_id_cached_pairs_applied_despite_low_id_budget_spend(
        self, mock_db, monkeypatch, make_event
    ):
        # Core regression: cap=1 spent on the low-id pair must not prevent a
        # high-id pair's already-cached confirmation from being applied.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        monkeypatch.setattr(tiebreaker, "LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS", 1)
        low_a, low_b = _event(make_event, 1), _event(make_event, 2)
        high_a, high_b = _event(make_event, 100), _event(make_event, 101)
        events = [low_a, low_b, high_a, high_b]
        _wire_db(mock_db, events)
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2), (100, 101)]),
        )
        monkeypatch.setattr(tiebreaker, "_dedup_pair_hash", _hash_by_ids)
        _wire_execute(mock_db, [("hash-100-101", {"same": True, "confidence": 0.9})])
        confirm = AsyncMock(return_value=False)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["fresh_calls"] == 1
        assert result["deferred_pairs"] == 0
        confirm.assert_awaited_once()
        assert high_a.dedup_group_id == 100
        assert high_b.dedup_group_id == 100
        assert low_a.dedup_group_id is None
        assert low_b.dedup_group_id is None

    @pytest.mark.asyncio
    async def test_backlog_drains_across_runs(self, mock_db, monkeypatch, make_event):
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        monkeypatch.setattr(tiebreaker, "LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS", 1)
        monkeypatch.setattr(tiebreaker, "_dedup_pair_hash", _hash_by_ids)
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2), (3, 4)]),
        )

        # Run 1: cold cache, budget=1 → one fresh call, one pair deferred.
        run1_events = [_event(make_event, 1), _event(make_event, 2), _event(make_event, 3), _event(make_event, 4)]
        _wire_db(mock_db, run1_events)
        _wire_execute(mock_db, [])
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", AsyncMock(return_value=True))

        result1 = await tiebreaker.run_dedup_pass_llm(mock_db)
        assert result1["fresh_calls"] == 1
        assert result1["deferred_pairs"] == 1

        # Run 2: prefetch now returns cached decisions for both pairs (the
        # backlog has drained) → no fresh calls, no deferrals, all grouped.
        run2_events = [_event(make_event, 1), _event(make_event, 2), _event(make_event, 3), _event(make_event, 4)]
        _wire_db(mock_db, run2_events)
        _wire_execute(
            mock_db,
            [
                ("hash-1-2", {"same": True, "confidence": 0.9}),
                ("hash-3-4", {"same": True, "confidence": 0.9}),
            ],
        )

        result2 = await tiebreaker.run_dedup_pass_llm(mock_db)
        assert result2["fresh_calls"] == 0
        assert result2["deferred_pairs"] == 0
        assert result2["llm_confirmed"] == 2

    @pytest.mark.asyncio
    async def test_complete_clustering_at_warm_cache(self, mock_db, monkeypatch, make_event):
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        monkeypatch.setattr(tiebreaker, "LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS", 1)
        a, b = _event(make_event, 1), _event(make_event, 2)
        _wire_db(mock_db, [a, b])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        monkeypatch.setattr(tiebreaker, "_dedup_pair_hash", _hash_by_ids)
        _wire_execute(mock_db, [("hash-1-2", {"same": True, "confidence": 0.9})])
        confirm = AsyncMock(return_value=True)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["fresh_calls"] == 0
        assert result["llm_confirmed"] == 1
        confirm.assert_not_called()

    @pytest.mark.asyncio
    async def test_prefetch_uses_single_bulk_query(self, mock_db, monkeypatch, make_event):
        # M=4 cached-reject pairs → one bulk prefetch query (plus the final
        # stale-group cleanup), never one query per pair; llm_json untouched.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        events = [_event(make_event, i) for i in range(1, 6)]
        _wire_db(mock_db, events)
        pairs = [(1, 2), (1, 3), (1, 4), (1, 5)]
        monkeypatch.setattr(
            tiebreaker, "candidate_pair_ids_in_window", AsyncMock(return_value=pairs)
        )
        monkeypatch.setattr(tiebreaker, "_dedup_pair_hash", _hash_by_ids)
        cached_rows = [
            (f"hash-{a_id}-{b_id}", {"same": False, "confidence": 0.9})
            for a_id, b_id in pairs
        ]
        _wire_execute(mock_db, cached_rows)
        llm_json_mock = AsyncMock()
        monkeypatch.setattr(tiebreaker, "llm_json", llm_json_mock)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["candidate_pairs"] == 4
        assert result["fresh_calls"] == 0
        # 1 prefetch query (M=4 < chunk size) + 1 stale-group cleanup update
        assert mock_db.execute.call_count == 2
        llm_json_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_newest_row_wins_per_hash(self, mock_db, monkeypatch, make_event):
        # Two rows for the same hash, returned oldest-first (older reject,
        # newer confirm) → the newer confirm wins by dict overwrite.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a, b = _event(make_event, 1), _event(make_event, 2)
        _wire_db(mock_db, [a, b])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        monkeypatch.setattr(tiebreaker, "_dedup_pair_hash", _hash_by_ids)
        _wire_execute(
            mock_db,
            [
                ("hash-1-2", {"same": False, "confidence": 0.95}),
                ("hash-1-2", {"same": True, "confidence": 0.9}),
            ],
        )
        confirm = AsyncMock()
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["llm_confirmed"] == 1
        assert result["fresh_calls"] == 0
        confirm.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_cached_response_treated_as_undecided(
        self, mock_db, monkeypatch, make_event
    ):
        # Bad confidence in the cached row → treated as absent, falls through
        # to a fresh call (not a cached reject).
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a, b = _event(make_event, 1), _event(make_event, 2)
        _wire_db(mock_db, [a, b])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        monkeypatch.setattr(tiebreaker, "_dedup_pair_hash", _hash_by_ids)
        _wire_execute(mock_db, [("hash-1-2", {"same": True, "confidence": "bad"})])
        confirm = AsyncMock(return_value=True)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["fresh_calls"] == 1
        assert result["llm_confirmed"] == 1
        confirm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_dict_cached_response_treated_as_undecided(
        self, mock_db, monkeypatch, make_event
    ):
        # A cached row whose response_json isn't a dict (e.g. a stray JSON
        # array) must not crash the pass — treated as absent, falls through
        # to a fresh call.
        monkeypatch.setattr(tiebreaker, "llm_available", lambda: True)
        a, b = _event(make_event, 1), _event(make_event, 2)
        _wire_db(mock_db, [a, b])
        monkeypatch.setattr(
            tiebreaker,
            "candidate_pair_ids_in_window",
            AsyncMock(return_value=[(1, 2)]),
        )
        monkeypatch.setattr(tiebreaker, "_dedup_pair_hash", _hash_by_ids)
        _wire_execute(mock_db, [("hash-1-2", ["unexpected", "array"])])
        confirm = AsyncMock(return_value=True)
        monkeypatch.setattr(tiebreaker, "_llm_confirms_pair", confirm)

        result = await tiebreaker.run_dedup_pass_llm(mock_db)

        assert result["fresh_calls"] == 1
        assert result["llm_confirmed"] == 1
        confirm.assert_awaited_once()
