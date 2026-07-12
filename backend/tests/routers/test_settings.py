"""Tests for GET /users/me and PATCH /users/me (settings) endpoints."""
import http
from unittest.mock import MagicMock

import pytest

from app.constants import PERSONA_PRIMARY_WEIGHT


def _attach_empty_personas(db) -> None:
    """Wire mock_db.execute to return zero persona rows."""
    result = MagicMock()
    result.all.return_value = []
    db.execute.return_value = result


class TestGetSettings:
    @pytest.mark.asyncio
    async def test_returns_user_fields(self, mock_db, make_user, make_request):
        from app.routers.settings import get_settings

        _attach_empty_personas(mock_db)
        user = make_user(locale="et", opt_in=True)

        result = await get_settings(
            request=make_request(method="GET", path="/users/me"),
            current_user=user,
            db=mock_db,
        )

        assert result["email"] == "test@example.com"
        assert result["locale"] == "et"
        assert result["email_digest_opt_in"] is True
        assert result["personas"] == []
        assert result["preferred_categories"] == []
        assert result["preferred_vibes"] == []

    @pytest.mark.asyncio
    async def test_personas_included(self, mock_db, make_user, make_request):
        from app.routers.settings import get_settings

        persona = MagicMock()
        persona.slug = "culture_buff"
        persona.display_name_en = "Culture Buff"
        persona.display_name_et = "Kultuuriinimene"
        persona.display_name_ru = "Культурный"
        persona.affinity_vector = {
            "categories": {"exhibitions": 0.9},
            "vibes": {"educational": 0.8},
        }
        up = MagicMock()
        up.weight = PERSONA_PRIMARY_WEIGHT
        result_mock = MagicMock()
        result_mock.all.return_value = [(up, persona)]
        mock_db.execute.return_value = result_mock

        user = make_user()
        result = await get_settings(
            request=make_request(method="GET", path="/users/me"),
            current_user=user,
            db=mock_db,
        )

        assert len(result["personas"]) == 1
        assert result["personas"][0]["slug"] == "culture_buff"
        assert result["preferred_categories"] == ["exhibitions"]
        assert result["preferred_vibes"] == ["educational"]
        assert result["personas"][0]["weight"] == PERSONA_PRIMARY_WEIGHT


class TestPatchSettings:
    @pytest.mark.asyncio
    async def test_update_locale(self, mock_db, make_user, make_request):
        from app.routers.settings import patch_settings, PatchSettingsBody

        _attach_empty_personas(mock_db)
        user = make_user(locale="en")

        result = await patch_settings(
            body=PatchSettingsBody(locale="ru"),
            request=make_request(method="PATCH", path="/users/me"),
            current_user=user,
            db=mock_db,
        )

        assert user.locale == "ru"
        mock_db.commit.assert_called_once()
        assert result["locale"] == "ru"

    @pytest.mark.asyncio
    async def test_update_email_opt_in(self, mock_db, make_user, make_request):
        from app.routers.settings import patch_settings, PatchSettingsBody

        _attach_empty_personas(mock_db)
        user = make_user(opt_in=True)

        result = await patch_settings(
            body=PatchSettingsBody(email_digest_opt_in=False),
            request=make_request(method="PATCH", path="/users/me"),
            current_user=user,
            db=mock_db,
        )

        assert user.email_digest_opt_in is False
        mock_db.commit.assert_called_once()
        assert result["email_digest_opt_in"] is False

    @pytest.mark.asyncio
    async def test_empty_body_raises_400(self, mock_db, make_user, make_request):
        from fastapi import HTTPException
        from app.routers.settings import patch_settings, PatchSettingsBody

        _attach_empty_personas(mock_db)
        user = make_user()

        with pytest.raises(HTTPException) as exc_info:
            await patch_settings(
                body=PatchSettingsBody(),
                request=make_request(method="PATCH", path="/users/me"),
                current_user=user,
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_invalid_locale_rejected(self):
        from pydantic import ValidationError
        from app.routers.settings import PatchSettingsBody

        with pytest.raises(ValidationError):
            PatchSettingsBody(locale="fr")

    @pytest.mark.asyncio
    async def test_update_both_fields(self, mock_db, make_user, make_request):
        from app.routers.settings import patch_settings, PatchSettingsBody

        _attach_empty_personas(mock_db)
        user = make_user(locale="en", opt_in=True)

        await patch_settings(
            body=PatchSettingsBody(locale="et", email_digest_opt_in=False),
            request=make_request(method="PATCH", path="/users/me"),
            current_user=user,
            db=mock_db,
        )

        assert user.locale == "et"
        assert user.email_digest_opt_in is False
