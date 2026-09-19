"""Tests for GET /users/me and PATCH /users/me (settings) endpoints."""
import http
from unittest.mock import MagicMock

import pytest

from app.constants import PERSONA_PRIMARY_WEIGHT


def _attach_empty_personas(db) -> None:
    """Wire mock_db.execute to return zero persona rows and no linked
    Google identity (both get_settings/patch_settings queries share this
    single mocked result — .all() feeds the persona query, .scalars().first()
    feeds _is_google_linked)."""
    result = MagicMock()
    result.all.return_value = []
    result.scalars.return_value.first.return_value = None
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
        assert result["google_linked"] is False

    @pytest.mark.asyncio
    async def test_google_linked_true_when_identity_row_exists(
        self, mock_db, make_user, make_request
    ):
        from app.routers.settings import get_settings

        persona_result = MagicMock()
        persona_result.all.return_value = []
        linked_result = MagicMock()
        linked_result.scalars.return_value.first.return_value = 1
        mock_db.execute.side_effect = [persona_result, linked_result]

        user = make_user()
        result = await get_settings(
            request=make_request(method="GET", path="/users/me"),
            current_user=user,
            db=mock_db,
        )

        assert result["google_linked"] is True

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

    @pytest.mark.asyncio
    async def test_stale_theme_preference_field_is_silently_ignored(
        self, mock_db, make_user, make_request
    ):
        """A tab left open from before #378's deploy may still send the
        retired theme_preference field — it must be a no-op, not a 422
        (extra fields are ignored by default, no explicit-reject config)."""
        from app.routers.settings import patch_settings, PatchSettingsBody

        _attach_empty_personas(mock_db)
        user = make_user(locale="en")

        result = await patch_settings(
            body=PatchSettingsBody(locale="ru", theme_preference="dark"),
            request=make_request(method="PATCH", path="/users/me"),
            current_user=user,
            db=mock_db,
        )

        assert user.locale == "ru"
        assert "theme_preference" not in result

    @pytest.mark.asyncio
    async def test_response_never_serializes_theme(self, mock_db, make_user, make_request):
        from app.routers.settings import get_settings

        _attach_empty_personas(mock_db)
        user = make_user()

        result = await get_settings(
            request=make_request(method="GET", path="/users/me"),
            current_user=user,
            db=mock_db,
        )

        assert "theme_preference" not in result


class TestUnlinkOwnIdentity:
    """Mirrors tests/routers/test_organizer_profile.py::TestUnlinkOwnIdentity
    for the consumer-track DELETE /users/me/identities/{provider} (#296)."""

    @pytest.mark.asyncio
    async def test_deletes_row_bumps_version_and_reissues_cookie(
        self, mock_db, make_request, make_user
    ):
        from fastapi import Response

        from app.auth.tokens import verify_session_token
        from app.routers.settings import unlink_own_identity
        from tests.conftest import assert_hardened_cookie

        user = make_user(user_id=5)
        user.session_token_version = 1

        delete_result = MagicMock()
        delete_result.fetchone.return_value = (99,)
        version_result = MagicMock()
        version_result.scalar_one.return_value = 2
        mock_db.execute.side_effect = [delete_result, version_result]

        response = Response()
        result = await unlink_own_identity(
            "google",
            make_request(method="DELETE", path="/users/me/identities/google"),
            response,
            user,
            mock_db,
        )

        assert result == {"detail": "Identity unlinked."}
        assert user.session_token_version == 2
        set_cookie = response.headers["set-cookie"]
        assert_hardened_cookie(set_cookie, name="session", path="/api")
        cookie_value = set_cookie.split("session=", 1)[1].split(";", 1)[0]
        assert verify_session_token(cookie_value) == (5, 2)

    @pytest.mark.asyncio
    async def test_no_linked_identity_raises_404(self, mock_db, make_request, make_user):
        from fastapi import HTTPException, Response

        from app.routers.settings import unlink_own_identity

        user = make_user(user_id=5)
        delete_result = MagicMock()
        delete_result.fetchone.return_value = None
        mock_db.execute.return_value = delete_result

        with pytest.raises(HTTPException) as exc_info:
            await unlink_own_identity(
                "google",
                make_request(method="DELETE", path="/users/me/identities/google"),
                Response(),
                user,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND
