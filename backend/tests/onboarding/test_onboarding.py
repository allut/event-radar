"""Tests for POST /onboarding/persona."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants import PERSONA_RANK_WEIGHTS


def _make_persona(slug: str, persona_id: int) -> MagicMock:
    p = MagicMock()
    p.slug = slug
    p.id = persona_id
    return p


class TestSetPersona:
    @pytest.mark.asyncio
    async def test_sets_single_persona(self, mock_db, make_user, make_request):
        from app.routers.onboarding import set_persona, PersonaBody

        culture_buff = _make_persona("culture_buff", 1)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[culture_buff]))

        result = await set_persona(
            body=PersonaBody(persona_slugs=["culture_buff"]),
            request=make_request(method="POST", path="/onboarding/persona"),
            current_user=make_user(),
            db=mock_db,
        )

        assert result["personas"] == [
            {"slug": "culture_buff", "weight": PERSONA_RANK_WEIGHTS[0]}
        ]
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sets_two_personas(self, mock_db, make_user, make_request):
        from app.routers.onboarding import set_persona, PersonaBody

        culture_buff = _make_persona("culture_buff", 1)
        nightlife = _make_persona("nightlife", 2)
        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[culture_buff, nightlife])
        )

        result = await set_persona(
            body=PersonaBody(persona_slugs=["culture_buff", "nightlife"]),
            request=make_request(method="POST", path="/onboarding/persona"),
            current_user=make_user(),
            db=mock_db,
        )

        assert result["personas"] == [
            {"slug": "culture_buff", "weight": PERSONA_RANK_WEIGHTS[0]},
            {"slug": "nightlife", "weight": PERSONA_RANK_WEIGHTS[1]},
        ]

    @pytest.mark.asyncio
    async def test_sets_three_personas(self, mock_db, make_user, make_request):
        from app.routers.onboarding import set_persona, PersonaBody

        culture_buff = _make_persona("culture_buff", 1)
        nightlife = _make_persona("nightlife", 2)
        family = _make_persona("family_organizer", 3)
        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[culture_buff, nightlife, family])
        )

        result = await set_persona(
            body=PersonaBody(persona_slugs=["culture_buff", "nightlife", "family_organizer"]),
            request=make_request(method="POST", path="/onboarding/persona"),
            current_user=make_user(),
            db=mock_db,
        )

        assert result["personas"] == [
            {"slug": "culture_buff", "weight": PERSONA_RANK_WEIGHTS[0]},
            {"slug": "nightlife", "weight": PERSONA_RANK_WEIGHTS[1]},
            {"slug": "family_organizer", "weight": PERSONA_RANK_WEIGHTS[2]},
        ]

    @pytest.mark.asyncio
    async def test_more_than_max_raises_400(self, mock_db, make_user, make_request):
        from fastapi import HTTPException
        from app.routers.onboarding import set_persona, PersonaBody

        with pytest.raises(HTTPException) as exc_info:
            await set_persona(
                body=PersonaBody(
                    persona_slugs=["culture_buff", "nightlife", "family_organizer", "foodie"]
                ),
                request=make_request(method="POST", path="/onboarding/persona"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_zero_slugs_raises_400(self, mock_db, make_user, make_request):
        from fastapi import HTTPException
        from app.routers.onboarding import set_persona, PersonaBody

        with pytest.raises(HTTPException) as exc_info:
            await set_persona(
                body=PersonaBody(persona_slugs=[]),
                request=make_request(method="POST", path="/onboarding/persona"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_duplicate_slugs_raises_400(self, mock_db, make_user, make_request):
        from fastapi import HTTPException
        from app.routers.onboarding import set_persona, PersonaBody

        with pytest.raises(HTTPException) as exc_info:
            await set_persona(
                body=PersonaBody(persona_slugs=["culture_buff", "culture_buff"]),
                request=make_request(method="POST", path="/onboarding/persona"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_slug_raises_400(self, mock_db, make_user, make_request):
        from fastapi import HTTPException
        from app.routers.onboarding import set_persona, PersonaBody

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        with pytest.raises(HTTPException) as exc_info:
            await set_persona(
                body=PersonaBody(persona_slugs=["nonexistent"]),
                request=make_request(method="POST", path="/onboarding/persona"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_builds_initial_feed_after_persona_commit(
        self, mock_db, make_user, make_request
    ):
        """Onboarding completion triggers a synchronous single-user feed build."""
        from app.routers.onboarding import set_persona, PersonaBody

        culture_buff = _make_persona("culture_buff", 1)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[culture_buff]))
        user = make_user(user_id=42)

        with patch(
            "app.routers.onboarding.build_daily_feed_for_user", new_callable=AsyncMock
        ) as mock_build:
            result = await set_persona(
                body=PersonaBody(persona_slugs=["culture_buff"]),
                request=make_request(method="POST", path="/onboarding/persona"),
                current_user=user,
                db=mock_db,
            )

        mock_build.assert_awaited_once_with(mock_db, 42)
        assert result["personas"] == [
            {"slug": "culture_buff", "weight": PERSONA_RANK_WEIGHTS[0]}
        ]

    @pytest.mark.asyncio
    async def test_persona_change_invalidates_score_cache_before_rebuild(
        self, mock_db, make_user, make_request
    ):
        """A persona re-pick must bust cached ranking scores before the feed
        rebuild — otherwise the rebuild reuses scores computed under the old
        personas (short-circuited by _score_or_reuse) and the feed reflects
        stale taste."""
        from app.routers.onboarding import set_persona, PersonaBody

        culture_buff = _make_persona("culture_buff", 1)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[culture_buff]))
        user = make_user(user_id=7)

        execute_count_at_build: list[int] = []

        async def fake_build(db, user_id):
            execute_count_at_build.append(mock_db.execute.call_count)

        with patch(
            "app.routers.onboarding.build_daily_feed_for_user",
            new_callable=AsyncMock,
            side_effect=fake_build,
        ):
            await set_persona(
                body=PersonaBody(persona_slugs=["culture_buff"]),
                request=make_request(method="POST", path="/onboarding/persona"),
                current_user=user,
                db=mock_db,
            )

        # execute() #1 is the UserPersona replace-delete, #2 is the score-cache
        # invalidation — both must land before build_daily_feed_for_user runs.
        assert execute_count_at_build == [2]
        invalidate_stmt = mock_db.execute.call_args_list[1].args[0]
        compiled = str(invalidate_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "DELETE FROM user_event_scores" in compiled
        assert f"user_id = {user.id}" in compiled

    @pytest.mark.asyncio
    async def test_feed_build_failure_does_not_fail_onboarding(
        self, mock_db, make_user, make_request
    ):
        """A build_daily_feed_for_user exception must not surface to the caller —
        worst case the user falls back to the stale feed or empty state until 06:00."""
        from app.routers.onboarding import set_persona, PersonaBody

        culture_buff = _make_persona("culture_buff", 1)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[culture_buff]))

        with patch(
            "app.routers.onboarding.build_daily_feed_for_user",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await set_persona(
                body=PersonaBody(persona_slugs=["culture_buff"]),
                request=make_request(method="POST", path="/onboarding/persona"),
                current_user=make_user(),
                db=mock_db,
            )

        assert result["personas"] == [
            {"slug": "culture_buff", "weight": PERSONA_RANK_WEIGHTS[0]}
        ]
