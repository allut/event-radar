"""Tests for the organizer auth stack — magic-link request/verify/logout-all
and the get_current_organizer dependency. Mirrors tests/auth/test_auth.py's
structure and DB-mocking approach for the consumer auth stack."""
import http
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from itsdangerous import BadSignature

from app.auth.tokens import (
    generate_organizer_magic_token,
    generate_organizer_session_token,
    generate_magic_token,
    generate_session_token,
    hash_token,
    verify_organizer_magic_token,
    verify_organizer_session_token,
    verify_session_token,
)


class TestOrganizerMagicToken:
    def test_roundtrip(self):
        token, token_hash, expires_at = generate_organizer_magic_token(42)
        assert verify_organizer_magic_token(token) == 42

    def test_hash_token_helper(self):
        token, token_hash, _ = generate_organizer_magic_token(7)
        assert hash_token(token) == token_hash

    def test_expires_at_in_future(self):
        _, _, expires_at = generate_organizer_magic_token(1)
        assert expires_at > datetime.now(timezone.utc)

    def test_bad_signature_raises(self):
        token, _, _ = generate_organizer_magic_token(1)
        with pytest.raises(BadSignature):
            verify_organizer_magic_token(token + "x")

    def test_user_magic_token_rejected_as_organizer_token(self):
        """A consumer magic-link token must never verify as an organizer
        token, even for the same numeric id — distinct salts (see
        AUTH_ORGANIZER_MAGIC_SALT) enforce the account-track separation."""
        user_token, _, _ = generate_magic_token(1)
        with pytest.raises(BadSignature):
            verify_organizer_magic_token(user_token)

    def test_organizer_magic_token_rejected_as_user_token(self):
        from app.auth.tokens import verify_magic_token

        organizer_token, _, _ = generate_organizer_magic_token(1)
        with pytest.raises(BadSignature):
            verify_magic_token(organizer_token)


class TestOrganizerSessionToken:
    def test_roundtrip(self):
        token = generate_organizer_session_token(99, 1)
        assert verify_organizer_session_token(token) == (99, 1)

    def test_roundtrip_carries_version(self):
        token = generate_organizer_session_token(99, 3)
        assert verify_organizer_session_token(token) == (99, 3)

    def test_bad_signature_raises(self):
        token = generate_organizer_session_token(1, 1)
        with pytest.raises(BadSignature):
            verify_organizer_session_token(token + "y")

    def test_user_session_token_rejected_as_organizer_token(self):
        user_session = generate_session_token(1, 1)
        with pytest.raises(BadSignature):
            verify_organizer_session_token(user_session)

    def test_organizer_session_token_rejected_as_user_token(self):
        organizer_session = generate_organizer_session_token(1, 1)
        with pytest.raises(BadSignature):
            verify_session_token(organizer_session)


def _mock_execute_returning(row):
    execute_result = MagicMock()
    execute_result.fetchone.return_value = row
    return AsyncMock(return_value=execute_result)


class TestRequestOrganizerMagicLink:
    @pytest.mark.asyncio
    async def test_new_organizer_creates_and_sends(self, mock_db, make_request):
        from app.routers.organizer_auth import (
            RequestLinkBody,
            request_organizer_magic_link,
        )

        mock_db.scalar.side_effect = [None, None]  # lookup miss, cooldown miss

        def _add_side_effect(obj):
            if hasattr(obj, "id"):
                obj.id = 1

        mock_db.add.side_effect = _add_side_effect
        mock_db.flush = AsyncMock()

        with patch(
            "app.routers.organizer_auth.send_magic_link", new_callable=AsyncMock
        ) as mock_send:
            body = RequestLinkBody(email="org@example.com")
            result = await request_organizer_magic_link(
                body,
                make_request(method="POST", path="/organizer/auth/request-link"),
                mock_db,
            )

        assert "detail" in result
        mock_send.assert_called_once()
        # verify_path must point at the organizer verify route, not /auth/verify.
        assert mock_send.call_args.kwargs.get("verify_path") == "/organizer/verify"

    @pytest.mark.asyncio
    async def test_cooldown_skips_resend(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_auth import (
            RequestLinkBody,
            request_organizer_magic_link,
        )

        existing = make_organizer(organizer_id=5)
        recent_link = MagicMock()
        mock_db.scalar.side_effect = [existing, recent_link]

        with patch(
            "app.routers.organizer_auth.send_magic_link", new_callable=AsyncMock
        ) as mock_send:
            body = RequestLinkBody(email="existing@example.com")
            result = await request_organizer_magic_link(
                body,
                make_request(method="POST", path="/organizer/auth/request-link"),
                mock_db,
            )

        assert "detail" in result
        mock_send.assert_not_called()


class TestVerifyOrganizerMagicLink:
    @pytest.mark.asyncio
    async def test_valid_token_returns_session(self, mock_db, make_request):
        from app.routers.organizer_auth import verify_organizer_magic_link

        token, _, _ = generate_organizer_magic_token(3)
        mock_db.execute = _mock_execute_returning((3,))

        organizer = MagicMock()
        organizer.id = 3
        organizer.email = "org@example.com"
        organizer.locale = "en"
        organizer.session_token_version = 1
        mock_db.get.return_value = organizer

        result = await verify_organizer_magic_link(
            make_request(path="/organizer/auth/verify"), token, mock_db
        )

        assert "session_token" in result
        assert result["organizer"]["id"] == 3
        assert verify_organizer_session_token(result["session_token"]) == (3, 1)

    @pytest.mark.asyncio
    async def test_second_use_raises_400(self, mock_db, make_request):
        """Single-use: the atomic UPDATE finds no matching row the second time
        (used_at already set), so a token replay is rejected."""
        from fastapi import HTTPException
        from app.routers.organizer_auth import verify_organizer_magic_link

        token, _, _ = generate_organizer_magic_token(3)
        mock_db.execute = _mock_execute_returning(None)

        with pytest.raises(HTTPException) as exc_info:
            await verify_organizer_magic_link(
                make_request(path="/organizer/auth/verify"), token, mock_db
            )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_bad_signature_raises_400(self, mock_db, make_request):
        from fastapi import HTTPException
        from app.routers.organizer_auth import verify_organizer_magic_link

        with pytest.raises(HTTPException) as exc_info:
            await verify_organizer_magic_link(
                make_request(path="/organizer/auth/verify"), "garbage", mock_db
            )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST


class TestGetCurrentOrganizer:
    @pytest.mark.asyncio
    async def test_valid_session_token_returns_organizer(self, mock_db, make_organizer):
        from app.routers.organizer_auth import get_current_organizer

        organizer = make_organizer(organizer_id=7)
        mock_db.get.return_value = organizer

        token = generate_organizer_session_token(7, 1)
        result = await get_current_organizer(authorization=f"Bearer {token}", db=mock_db)
        assert result.id == 7

    @pytest.mark.asyncio
    async def test_missing_header_raises_401(self, mock_db):
        from fastapi import HTTPException
        from app.routers.organizer_auth import get_current_organizer

        with pytest.raises(HTTPException) as exc_info:
            await get_current_organizer(authorization=None, db=mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_user_session_token_rejected(self, mock_db):
        """A consumer session token must not authenticate as an organizer —
        distinct salts make verify_organizer_session_token raise BadSignature."""
        from fastapi import HTTPException
        from app.routers.organizer_auth import get_current_organizer

        user_token = generate_session_token(7, 1)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_organizer(
                authorization=f"Bearer {user_token}", db=mock_db
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_revoked_session_raises_401(self, mock_db, make_organizer):
        from fastapi import HTTPException
        from app.routers.organizer_auth import get_current_organizer

        organizer = make_organizer(organizer_id=7, session_token_version=2)
        mock_db.get.return_value = organizer

        token = generate_organizer_session_token(7, 1)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_organizer(authorization=f"Bearer {token}", db=mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.UNAUTHORIZED


class TestOrganizerLogoutAll:
    @pytest.mark.asyncio
    async def test_increments_session_token_version(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_auth import organizer_logout_all

        organizer = make_organizer(organizer_id=7)
        execute_result = MagicMock()
        execute_result.scalar_one.return_value = 2
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        result = await organizer_logout_all(
            request=make_request(method="POST", path="/organizer/auth/logout-all"),
            current_organizer=organizer,
            db=mock_db,
        )

        assert organizer.session_token_version == 2
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()
        assert "detail" in result
