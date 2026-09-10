"""Tests for organizer profile (routers/organizer_profile.py, #175)."""
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestGetOwnProfile:
    @pytest.mark.asyncio
    async def test_returns_serialized_profile(self, make_request, make_organizer):
        from app.routers.organizer_profile import get_own_profile

        organizer = make_organizer(organizer_id=5, name="Tallinn Live", verified=True)

        result = await get_own_profile(
            make_request(method="GET", path="/organizer/profile"), organizer
        )

        assert result == {
            "id": 5,
            "email": organizer.email,
            "locale": organizer.locale,
            "theme_preference": None,
            "verified": True,
            "name": "Tallinn Live",
        }

    @pytest.mark.asyncio
    async def test_name_null_when_unset(self, make_request, make_organizer):
        from app.routers.organizer_profile import get_own_profile

        organizer = make_organizer(organizer_id=5)

        result = await get_own_profile(
            make_request(method="GET", path="/organizer/profile"), organizer
        )

        assert result["name"] is None


class TestUpdateOwnProfile:
    @pytest.mark.asyncio
    async def test_sets_name(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_profile import (
            OrganizerProfilePatchBody,
            update_own_profile,
        )

        organizer = make_organizer(organizer_id=5)

        result = await update_own_profile(
            OrganizerProfilePatchBody(name="Tallinn Live"),
            make_request(method="PATCH", path="/organizer/profile"),
            organizer,
            mock_db,
        )

        assert organizer.name == "Tallinn Live"
        assert result["name"] == "Tallinn Live"
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_strips_whitespace(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_profile import (
            OrganizerProfilePatchBody,
            update_own_profile,
        )

        organizer = make_organizer(organizer_id=5)

        await update_own_profile(
            OrganizerProfilePatchBody(name="  Tallinn Live  "),
            make_request(method="PATCH", path="/organizer/profile"),
            organizer,
            mock_db,
        )

        assert organizer.name == "Tallinn Live"

    @pytest.mark.asyncio
    async def test_blank_name_clears_to_none(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_profile import (
            OrganizerProfilePatchBody,
            update_own_profile,
        )

        organizer = make_organizer(organizer_id=5, name="Old Name")

        await update_own_profile(
            OrganizerProfilePatchBody(name="   "),
            make_request(method="PATCH", path="/organizer/profile"),
            organizer,
            mock_db,
        )

        assert organizer.name is None

    @pytest.mark.asyncio
    async def test_omitted_name_leaves_existing_untouched(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_profile import (
            OrganizerProfilePatchBody,
            update_own_profile,
        )

        organizer = make_organizer(organizer_id=5, name="Existing Name")

        await update_own_profile(
            OrganizerProfilePatchBody(),
            make_request(method="PATCH", path="/organizer/profile"),
            organizer,
            mock_db,
        )

        assert organizer.name == "Existing Name"

    def test_name_over_max_length_rejected(self):
        from pydantic import ValidationError

        from app.constants import ORGANIZER_NAME_MAX_LEN
        from app.routers.organizer_profile import OrganizerProfilePatchBody

        with pytest.raises(ValidationError):
            OrganizerProfilePatchBody(name="x" * (ORGANIZER_NAME_MAX_LEN + 1))

    @pytest.mark.asyncio
    async def test_sets_theme_preference(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_profile import (
            OrganizerProfilePatchBody,
            update_own_profile,
        )

        organizer = make_organizer(organizer_id=5, theme_preference=None)

        result = await update_own_profile(
            OrganizerProfilePatchBody(theme_preference="dark"),
            make_request(method="PATCH", path="/organizer/profile"),
            organizer,
            mock_db,
        )

        assert organizer.theme_preference == "dark"
        assert result["theme_preference"] == "dark"
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_omitted_theme_preference_leaves_existing_untouched(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_profile import (
            OrganizerProfilePatchBody,
            update_own_profile,
        )

        organizer = make_organizer(organizer_id=5, theme_preference="light")

        await update_own_profile(
            OrganizerProfilePatchBody(),
            make_request(method="PATCH", path="/organizer/profile"),
            organizer,
            mock_db,
        )

        assert organizer.theme_preference == "light"

    @pytest.mark.asyncio
    async def test_explicit_null_theme_preference_clears_it(
        self, mock_db, make_request, make_organizer
    ):
        """#257 — an explicit `theme_preference: null` clears the account
        back to "no preference", distinct from omitting the field."""
        from app.routers.organizer_profile import (
            OrganizerProfilePatchBody,
            update_own_profile,
        )

        organizer = make_organizer(organizer_id=5, theme_preference="dark")

        result = await update_own_profile(
            OrganizerProfilePatchBody(theme_preference=None),
            make_request(method="PATCH", path="/organizer/profile"),
            organizer,
            mock_db,
        )

        assert organizer.theme_preference is None
        assert result["theme_preference"] is None
        mock_db.commit.assert_awaited_once()

    def test_theme_preference_invalid_rejected(self):
        from pydantic import ValidationError

        from app.routers.organizer_profile import OrganizerProfilePatchBody

        with pytest.raises(ValidationError):
            OrganizerProfilePatchBody(theme_preference="blue")


class TestUnlinkOwnIdentity:
    @pytest.mark.asyncio
    async def test_deletes_row_bumps_version_and_reissues_cookie(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import Response

        from app.auth.tokens import verify_organizer_session_token
        from app.routers.organizer_profile import unlink_own_identity
        from tests.conftest import assert_hardened_cookie

        organizer = make_organizer(organizer_id=5, session_token_version=1)

        delete_result = MagicMock()
        delete_result.fetchone.return_value = (99,)
        version_result = MagicMock()
        version_result.scalar_one.return_value = 2
        mock_db.execute = AsyncMock(side_effect=[delete_result, version_result])

        response = Response()
        result = await unlink_own_identity(
            "google",
            make_request(method="DELETE", path="/organizer/profile/identities/google"),
            response,
            organizer,
            mock_db,
        )

        assert result == {"detail": "Identity unlinked."}
        assert organizer.session_token_version == 2
        set_cookie = response.headers["set-cookie"]
        assert_hardened_cookie(set_cookie, name="organizer_session", path="/api/organizer")
        cookie_value = set_cookie.split("organizer_session=", 1)[1].split(";", 1)[0]
        assert verify_organizer_session_token(cookie_value) == (5, 2)

    @pytest.mark.asyncio
    async def test_no_linked_identity_raises_404(self, mock_db, make_request, make_organizer):
        from fastapi import HTTPException, Response

        from app.routers.organizer_profile import unlink_own_identity

        organizer = make_organizer(organizer_id=5)
        delete_result = MagicMock()
        delete_result.fetchone.return_value = None
        mock_db.execute = AsyncMock(return_value=delete_result)

        with pytest.raises(HTTPException) as exc_info:
            await unlink_own_identity(
                "google",
                make_request(method="DELETE", path="/organizer/profile/identities/google"),
                Response(),
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == 404
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_scoped_to_calling_organizer_only(self, mock_db, make_request, make_organizer):
        """The DELETE query filters on organizer_id == current_organizer.id —
        this asserts that predicate is actually present, not just trusted."""
        from fastapi import Response

        from app.routers.organizer_profile import unlink_own_identity

        organizer = make_organizer(organizer_id=5)
        delete_result = MagicMock()
        delete_result.fetchone.return_value = (1,)
        version_result = MagicMock()
        version_result.scalar_one.return_value = 2
        mock_db.execute = AsyncMock(side_effect=[delete_result, version_result])

        await unlink_own_identity(
            "google",
            make_request(method="DELETE", path="/organizer/profile/identities/google"),
            Response(),
            organizer,
            mock_db,
        )

        delete_stmt = mock_db.execute.call_args_list[0].args[0]
        compiled = str(delete_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "organizer_id" in compiled
        assert "google" in compiled
