"""Tests for GET /users/me and PATCH /users/me (settings) endpoints."""
import http
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.constants import DEFAULT_USER_LOCALE, DEFAULT_USER_CITY, PERSONA_PRIMARY_WEIGHT


def _mock_db():
    db = AsyncMock()
    db.get = AsyncMock()
    db.scalar = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_user(user_id: int = 1, locale: str = DEFAULT_USER_LOCALE, opt_in: bool = True):
    u = MagicMock()
    u.id = user_id
    u.email = "test@example.com"
    u.locale = locale
    u.home_city = DEFAULT_USER_CITY
    u.email_digest_opt_in = opt_in
    u.created_at = MagicMock()
    u.created_at.isoformat.return_value = "2026-05-13T06:00:00+00:00"
    return u


def _empty_execute():
    """Returns a mock execute result with no persona rows."""
    result = MagicMock()
    result.all.return_value = []
    db = _mock_db()
    db.execute.return_value = result
    return db


class TestGetSettings:
    @pytest.mark.asyncio
    async def test_returns_user_fields(self):
        from app.routers.settings import get_settings

        db = _empty_execute()
        user = _make_user(locale="et", opt_in=True)

        result = await get_settings(current_user=user, db=db)

        assert result["email"] == "test@example.com"
        assert result["locale"] == "et"
        assert result["email_digest_opt_in"] is True
        assert result["personas"] == []

    @pytest.mark.asyncio
    async def test_personas_included(self):
        from app.routers.settings import get_settings

        db = _mock_db()
        persona = MagicMock()
        persona.slug = "culture_buff"
        persona.display_name_en = "Culture Buff"
        persona.display_name_et = "Kultuuriinimene"
        persona.display_name_ru = "Культурный"
        up = MagicMock()
        up.weight = PERSONA_PRIMARY_WEIGHT
        result_mock = MagicMock()
        result_mock.all.return_value = [(up, persona)]
        db.execute.return_value = result_mock

        user = _make_user()
        result = await get_settings(current_user=user, db=db)

        assert len(result["personas"]) == 1
        assert result["personas"][0]["slug"] == "culture_buff"
        assert result["personas"][0]["weight"] == PERSONA_PRIMARY_WEIGHT


class TestPatchSettings:
    @pytest.mark.asyncio
    async def test_update_locale(self):
        from app.routers.settings import patch_settings, PatchSettingsBody

        db = _empty_execute()
        user = _make_user(locale="en")

        result = await patch_settings(
            body=PatchSettingsBody(locale="ru"),
            current_user=user,
            db=db,
        )

        assert user.locale == "ru"
        db.commit.assert_called_once()
        assert result["locale"] == "ru"

    @pytest.mark.asyncio
    async def test_update_email_opt_in(self):
        from app.routers.settings import patch_settings, PatchSettingsBody

        db = _empty_execute()
        user = _make_user(opt_in=True)

        result = await patch_settings(
            body=PatchSettingsBody(email_digest_opt_in=False),
            current_user=user,
            db=db,
        )

        assert user.email_digest_opt_in is False
        db.commit.assert_called_once()
        assert result["email_digest_opt_in"] is False

    @pytest.mark.asyncio
    async def test_empty_body_raises_400(self):
        from fastapi import HTTPException
        from app.routers.settings import patch_settings, PatchSettingsBody

        db = _empty_execute()
        user = _make_user()

        with pytest.raises(HTTPException) as exc_info:
            await patch_settings(
                body=PatchSettingsBody(),
                current_user=user,
                db=db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_invalid_locale_rejected(self):
        from pydantic import ValidationError
        from app.routers.settings import PatchSettingsBody

        with pytest.raises(ValidationError):
            PatchSettingsBody(locale="fr")

    @pytest.mark.asyncio
    async def test_update_both_fields(self):
        from app.routers.settings import patch_settings, PatchSettingsBody

        db = _empty_execute()
        user = _make_user(locale="en", opt_in=True)

        await patch_settings(
            body=PatchSettingsBody(locale="et", email_digest_opt_in=False),
            current_user=user,
            db=db,
        )

        assert user.locale == "et"
        assert user.email_digest_opt_in is False
