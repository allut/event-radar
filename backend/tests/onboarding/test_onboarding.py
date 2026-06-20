"""Tests for POST /onboarding/persona."""
from unittest.mock import MagicMock

import pytest

from app.constants import PERSONA_PRIMARY_WEIGHT, PERSONA_SECONDARY_WEIGHT


def _make_persona(slug: str, persona_id: int) -> MagicMock:
    p = MagicMock()
    p.slug = slug
    p.id = persona_id
    return p


class TestSetPersona:
    @pytest.mark.asyncio
    async def test_sets_primary_only(self, mock_db, make_user, make_request):
        from app.routers.onboarding import set_persona, PersonaBody

        culture_buff = _make_persona("culture_buff", 1)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[culture_buff]))

        result = await set_persona(
            body=PersonaBody(primary_slug="culture_buff"),
            request=make_request(method="POST", path="/onboarding/persona"),
            current_user=make_user(),
            db=mock_db,
        )

        assert result["personas"] == [
            {"slug": "culture_buff", "weight": PERSONA_PRIMARY_WEIGHT}
        ]
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sets_primary_and_secondary(self, mock_db, make_user, make_request):
        from app.routers.onboarding import set_persona, PersonaBody

        culture_buff = _make_persona("culture_buff", 1)
        nightlife = _make_persona("nightlife", 2)
        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[culture_buff, nightlife])
        )

        result = await set_persona(
            body=PersonaBody(primary_slug="culture_buff", secondary_slug="nightlife"),
            request=make_request(method="POST", path="/onboarding/persona"),
            current_user=make_user(),
            db=mock_db,
        )

        assert result["personas"] == [
            {"slug": "culture_buff", "weight": PERSONA_PRIMARY_WEIGHT},
            {"slug": "nightlife", "weight": PERSONA_SECONDARY_WEIGHT},
        ]

    @pytest.mark.asyncio
    async def test_same_primary_and_secondary_raises_400(
        self, mock_db, make_user, make_request
    ):
        from fastapi import HTTPException
        from app.routers.onboarding import set_persona, PersonaBody

        with pytest.raises(HTTPException) as exc_info:
            await set_persona(
                body=PersonaBody(primary_slug="culture_buff", secondary_slug="culture_buff"),
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
                body=PersonaBody(primary_slug="nonexistent"),
                request=make_request(method="POST", path="/onboarding/persona"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 400
