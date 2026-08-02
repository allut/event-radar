"""Tests for magic-link auth and onboarding endpoints.

Uses AsyncMock to stub DB and email so no real DB is needed.
"""
import http
import hashlib
from collections import namedtuple
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.constants import DEFAULT_USER_CITY, DEFAULT_USER_LOCALE

import pytest
from itsdangerous import BadSignature

from app.auth.tokens import (
    generate_magic_token,
    generate_session_token,
    generate_unsubscribe_token,
    hash_token,
    verify_magic_token,
    verify_session_token,
    verify_unsubscribe_token,
)


# ---------------------------------------------------------------------------
# Token utility tests (pure, no I/O)
# ---------------------------------------------------------------------------


class TestMagicToken:
    def test_roundtrip(self):
        token, token_hash, expires_at = generate_magic_token(42)
        assert verify_magic_token(token) == 42

    def test_hash_matches_sha256(self):
        token, token_hash, expires_at = generate_magic_token(1)
        expected = hashlib.sha256(token.encode()).hexdigest()
        assert token_hash == expected

    def test_hash_token_helper(self):
        token, token_hash, _ = generate_magic_token(7)
        assert hash_token(token) == token_hash

    def test_expires_at_in_future(self):
        _, _, expires_at = generate_magic_token(1)
        assert expires_at > datetime.now(timezone.utc)

    def test_bad_signature_raises(self):
        token, _, _ = generate_magic_token(1)
        with pytest.raises(BadSignature):
            verify_magic_token(token + "x")

    def test_wrong_salt_raises(self):
        # A session token should not be accepted as a magic token
        session_token = generate_session_token(1, 1)
        with pytest.raises(BadSignature):
            verify_magic_token(session_token)

    def test_different_users_different_tokens(self):
        t1, _, _ = generate_magic_token(1)
        t2, _, _ = generate_magic_token(2)
        assert t1 != t2


class TestSessionToken:
    def test_roundtrip(self):
        token = generate_session_token(99, 1)
        assert verify_session_token(token) == (99, 1)

    def test_roundtrip_carries_version(self):
        token = generate_session_token(99, 3)
        assert verify_session_token(token) == (99, 3)

    def test_legacy_token_without_version_claim_defaults_to_one(self):
        # Tokens minted before the "v" claim existed must keep working —
        # they decode to version 1, matching the new column's server_default.
        from app.auth.tokens import _serializer
        from app.constants import AUTH_SESSION_SALT

        legacy_token = _serializer().dumps({"uid": 5}, salt=AUTH_SESSION_SALT)
        assert verify_session_token(legacy_token) == (5, 1)

    def test_bad_signature_raises(self):
        token = generate_session_token(1, 1)
        with pytest.raises(BadSignature):
            verify_session_token(token + "y")

    def test_wrong_salt_raises(self):
        # A magic token should not be accepted as a session token
        magic_token, _, _ = generate_magic_token(1)
        with pytest.raises(BadSignature):
            verify_session_token(magic_token)


class TestUnsubscribeToken:
    def test_roundtrip(self):
        token = generate_unsubscribe_token(42)
        assert verify_unsubscribe_token(token) == 42

    def test_bad_signature_raises(self):
        token = generate_unsubscribe_token(1)
        with pytest.raises(BadSignature):
            verify_unsubscribe_token(token + "x")

    def test_wrong_salt_rejects_magic_token(self):
        magic_token, _, _ = generate_magic_token(1)
        with pytest.raises(BadSignature):
            verify_unsubscribe_token(magic_token)

    def test_wrong_salt_rejects_session_token(self):
        session_token = generate_session_token(1, 1)
        with pytest.raises(BadSignature):
            verify_unsubscribe_token(session_token)

    def test_magic_token_rejects_unsubscribe_token(self):
        unsub_token = generate_unsubscribe_token(1)
        with pytest.raises(BadSignature):
            verify_magic_token(unsub_token)

    def test_different_users_different_tokens(self):
        t1 = generate_unsubscribe_token(1)
        t2 = generate_unsubscribe_token(2)
        assert t1 != t2


# ---------------------------------------------------------------------------
# Auth router tests (mocked DB + email)
# ---------------------------------------------------------------------------


class TestRequestMagicLink:
    @pytest.mark.asyncio
    async def test_new_user_creates_and_sends(self, mock_db, make_request):
        from app.routers.auth import request_magic_link, RequestLinkBody

        # First scalar call: user lookup → None; second: cooldown check → None
        mock_db.scalar.side_effect = [None, None]

        def _add_side_effect(obj):
            if hasattr(obj, "id") and not hasattr(obj, "_mock_methods"):
                obj.id = 1

        mock_db.add.side_effect = _add_side_effect
        mock_db.flush = AsyncMock()

        with patch("app.routers.auth.send_magic_link", new_callable=AsyncMock) as mock_send:
            body = RequestLinkBody(email="test@example.com")
            result = await request_magic_link(body, make_request(), mock_db)

        assert "registered" in result["detail"].lower() or "sent" in result["detail"].lower()
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_user_upserts_link(self, mock_db, make_request, make_user):
        from app.routers.auth import request_magic_link, RequestLinkBody

        existing_user = make_user(user_id=5)
        # First scalar: user found; second: cooldown check → no recent link
        mock_db.scalar.side_effect = [existing_user, None]

        with patch("app.routers.auth.send_magic_link", new_callable=AsyncMock):
            body = RequestLinkBody(email="existing@example.com")
            result = await request_magic_link(body, make_request(), mock_db)

        assert "detail" in result

    @pytest.mark.asyncio
    async def test_cooldown_skips_resend(self, mock_db, make_request, make_user):
        from app.routers.auth import request_magic_link, RequestLinkBody

        existing_user = make_user(user_id=5)
        recent_link = MagicMock()
        # First scalar: user found; second: cooldown check → recent link exists
        mock_db.scalar.side_effect = [existing_user, recent_link]

        with patch("app.routers.auth.send_magic_link", new_callable=AsyncMock) as mock_send:
            body = RequestLinkBody(email="existing@example.com")
            result = await request_magic_link(body, make_request(), mock_db)

        assert "detail" in result
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_email_failure_does_not_500(self, mock_db, make_request):
        from app.routers.auth import request_magic_link, RequestLinkBody

        mock_db.scalar.side_effect = [None, None]
        with patch("app.routers.auth.send_magic_link", side_effect=Exception("smtp down")):
            body = RequestLinkBody(email="fail@example.com")
            result = await request_magic_link(body, make_request(), mock_db)
        assert "detail" in result  # still returns 200 with message


def _mock_execute_returning(row):
    """Return an AsyncMock whose result has .fetchone() returning `row`."""
    execute_result = MagicMock()
    execute_result.fetchone.return_value = row
    execute_mock = AsyncMock(return_value=execute_result)
    return execute_mock


# Mirrors the column order of verify_magic_link's
# `.returning(User.id, User.email, User.locale, User.session_token_version)` —
# a real SQLAlchemy Row supports attribute access; a plain tuple does not.
_UserRow = namedtuple("_UserRow", ["id", "email", "locale", "session_token_version"])


def _mock_execute_returning_sequence(rows: list):
    """Return an AsyncMock whose successive calls' .fetchone() return each
    row in `rows`, in order — for functions that call db.execute() more
    than once (e.g. verify_magic_link's link-consume then user-verify)."""
    results = []
    for row in rows:
        result = MagicMock()
        result.fetchone.return_value = row
        results.append(result)
    return AsyncMock(side_effect=results)


class TestVerifyMagicLink:
    @pytest.mark.asyncio
    async def test_valid_token_returns_session(self, mock_db, make_request):
        from app.routers.auth import verify_magic_link

        token, _, _ = generate_magic_token(3)

        # Atomic UPDATEs: first the magic-link consume, then the user
        # email_verified update — both return a row (success).
        mock_db.execute = _mock_execute_returning_sequence(
            [(3,), _UserRow(3, "user@example.com", "en", 1)]
        )

        result = await verify_magic_link(make_request(), token, mock_db)

        assert "session_token" in result
        assert result["user"]["id"] == 3
        assert verify_session_token(result["session_token"]) == (3, 1)

    @pytest.mark.asyncio
    async def test_valid_token_marks_email_verified(self, mock_db, make_request):
        from app.routers.auth import verify_magic_link

        token, _, _ = generate_magic_token(3)

        mock_db.execute = _mock_execute_returning_sequence(
            [(3,), _UserRow(3, "user@example.com", "en", 1)]
        )

        await verify_magic_link(make_request(), token, mock_db)

        # Second db.execute call is the User email_verified UPDATE.
        second_call_stmt = mock_db.execute.call_args_list[1].args[0]
        compiled = second_call_stmt.compile(compile_kwargs={"literal_binds": True})
        assert "email_verified" in str(compiled)
        assert "true" in str(compiled).lower()

    @pytest.mark.asyncio
    async def test_used_or_expired_link_raises_400(self, mock_db, make_request):
        from fastapi import HTTPException
        from app.routers.auth import verify_magic_link

        token, _, _ = generate_magic_token(3)

        # Atomic UPDATE finds no matching row (already used or expired)
        mock_db.execute = _mock_execute_returning(None)

        with pytest.raises(HTTPException) as exc_info:
            await verify_magic_link(make_request(), token, mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_bad_signature_raises_400(self, mock_db, make_request):
        from fastapi import HTTPException
        from app.routers.auth import verify_magic_link

        with pytest.raises(HTTPException) as exc_info:
            await verify_magic_link(make_request(), "not-a-valid-token", mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_valid_session_token_returns_user(self, mock_db):
        from app.routers.auth import get_current_user

        user = MagicMock()
        user.id = 7
        user.session_token_version = 1
        mock_db.get.return_value = user

        session_token = generate_session_token(7, 1)
        result = await get_current_user(
            authorization=f"Bearer {session_token}",
            db=mock_db,
        )
        assert result.id == 7

    @pytest.mark.asyncio
    async def test_missing_header_raises_401(self, mock_db):
        from fastapi import HTTPException
        from app.routers.auth import get_current_user

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(authorization=None, db=mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self, mock_db):
        from fastapi import HTTPException
        from app.routers.auth import get_current_user

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(authorization="Bearer garbage", db=mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_revoked_session_raises_401(self, mock_db):
        """A token minted with an older session_token_version (e.g. before the
        user hit "log out everywhere") must be rejected even though its
        signature and TTL are still valid."""
        from fastapi import HTTPException
        from app.routers.auth import get_current_user

        user = MagicMock()
        user.id = 7
        user.session_token_version = 2
        mock_db.get.return_value = user

        session_token = generate_session_token(7, 1)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                authorization=f"Bearer {session_token}",
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNAUTHORIZED


class TestLogoutAll:
    @pytest.mark.asyncio
    async def test_increments_session_token_version(self, mock_db, make_request):
        from app.routers.auth import logout_all

        user = MagicMock()
        user.id = 7
        user.session_token_version = 1

        execute_result = MagicMock()
        execute_result.scalar_one.return_value = 2
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        result = await logout_all(
            request=make_request(method="POST", path="/auth/logout-all"),
            current_user=user,
            db=mock_db,
        )

        assert user.session_token_version == 2
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()
        assert "detail" in result


class TestGetMe:
    @pytest.mark.asyncio
    async def test_has_personas_true_when_count_nonzero(self, mock_db, make_request):
        from app.routers.auth import get_me

        user = MagicMock()
        user.id = 1
        user.email = "a@b.com"
        user.locale = DEFAULT_USER_LOCALE
        user.home_city = DEFAULT_USER_CITY
        user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_db.scalar.return_value = 2

        result = await get_me(request=make_request(), current_user=user, db=mock_db)
        assert result["has_personas"] is True

    @pytest.mark.asyncio
    async def test_has_personas_false_when_count_zero(self, mock_db, make_request):
        from app.routers.auth import get_me

        user = MagicMock()
        user.id = 2
        user.email = "c@d.com"
        user.locale = "et"
        user.home_city = DEFAULT_USER_CITY
        user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_db.scalar.return_value = 0

        result = await get_me(request=make_request(), current_user=user, db=mock_db)
        assert result["has_personas"] is False

    @pytest.mark.asyncio
    async def test_has_personas_false_when_count_none(self, mock_db, make_request):
        from app.routers.auth import get_me

        user = MagicMock()
        user.id = 3
        user.email = "e@f.com"
        user.locale = "ru"
        user.home_city = DEFAULT_USER_CITY
        user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_db.scalar.return_value = None

        result = await get_me(request=make_request(), current_user=user, db=mock_db)
        assert result["has_personas"] is False


class TestDetectLocale:
    def test_estonian_detected(self):
        from app.routers.auth import _detect_locale
        assert _detect_locale("et-EE,et;q=0.9,en;q=0.8") == "et"

    def test_russian_detected(self):
        from app.routers.auth import _detect_locale
        assert _detect_locale("ru-RU,ru;q=0.9") == "ru"

    def test_english_detected(self):
        from app.routers.auth import _detect_locale
        assert _detect_locale("en-US,en;q=0.9") == "en"

    def test_unsupported_falls_back_to_en(self):
        from app.routers.auth import _detect_locale
        assert _detect_locale("fi-FI,fi;q=0.9") == "en"

    def test_empty_falls_back_to_en(self):
        from app.routers.auth import _detect_locale
        assert _detect_locale("") == "en"

    @pytest.mark.asyncio
    async def test_new_user_gets_locale_from_header(self, mock_db, make_request):
        from app.routers.auth import request_magic_link, RequestLinkBody

        mock_db.scalar.side_effect = [None, None]

        created_user = None

        def _capture_add(obj):
            nonlocal created_user
            if hasattr(obj, "locale"):
                created_user = obj
                obj.id = 99

        mock_db.add.side_effect = _capture_add
        mock_db.flush = AsyncMock()

        with patch("app.routers.auth.send_magic_link", new_callable=AsyncMock):
            body = RequestLinkBody(email="newuser@example.com")
            await request_magic_link(body, make_request("et-EE,et;q=0.9"), mock_db)

        assert created_user is not None and created_user.locale == "et"


class TestRequestLinkBodyLocale:
    @pytest.mark.asyncio
    async def test_body_locale_used_for_email(self, mock_db, make_request, make_user):
        from app.routers.auth import request_magic_link, RequestLinkBody

        existing_user = make_user(user_id=5, locale="en")
        mock_db.scalar.side_effect = [existing_user, None]

        with patch("app.routers.auth.send_magic_link", new_callable=AsyncMock) as mock_send:
            body = RequestLinkBody(email="existing@example.com", locale="et")
            await request_magic_link(body, make_request(), mock_db)

        mock_send.assert_called_once()
        assert mock_send.call_args.args[2] == "et"

    @pytest.mark.asyncio
    async def test_invalid_body_locale_falls_back_to_user_locale(
        self, mock_db, make_request, make_user
    ):
        from app.routers.auth import request_magic_link, RequestLinkBody

        existing_user = make_user(user_id=5, locale="ru")
        mock_db.scalar.side_effect = [existing_user, None]

        with patch("app.routers.auth.send_magic_link", new_callable=AsyncMock) as mock_send:
            body = RequestLinkBody(email="existing@example.com", locale="xx")
            await request_magic_link(body, make_request(), mock_db)

        assert mock_send.call_args.args[2] == "ru"

    @pytest.mark.asyncio
    async def test_absent_body_locale_falls_back_to_user_locale(
        self, mock_db, make_request, make_user
    ):
        from app.routers.auth import request_magic_link, RequestLinkBody

        existing_user = make_user(user_id=5, locale="ru")
        mock_db.scalar.side_effect = [existing_user, None]

        with patch("app.routers.auth.send_magic_link", new_callable=AsyncMock) as mock_send:
            body = RequestLinkBody(email="existing@example.com")
            await request_magic_link(body, make_request(), mock_db)

        assert mock_send.call_args.args[2] == "ru"

    @pytest.mark.asyncio
    async def test_new_user_seeded_from_body_locale_over_header(
        self, mock_db, make_request
    ):
        from app.routers.auth import request_magic_link, RequestLinkBody

        mock_db.scalar.side_effect = [None, None]

        created_user = None

        def _capture_add(obj):
            nonlocal created_user
            if hasattr(obj, "locale"):
                created_user = obj
                obj.id = 99

        mock_db.add.side_effect = _capture_add
        mock_db.flush = AsyncMock()

        with patch("app.routers.auth.send_magic_link", new_callable=AsyncMock) as mock_send:
            body = RequestLinkBody(email="newuser2@example.com", locale="ru")
            await request_magic_link(body, make_request("en-US,en;q=0.9"), mock_db)

        assert created_user is not None and created_user.locale == "ru"
        assert mock_send.call_args.args[2] == "ru"

    @pytest.mark.asyncio
    async def test_existing_user_locale_not_overwritten_by_body(
        self, mock_db, make_request, make_user
    ):
        from app.routers.auth import request_magic_link, RequestLinkBody

        existing_user = make_user(user_id=5, locale="en")
        mock_db.scalar.side_effect = [existing_user, None]

        with patch("app.routers.auth.send_magic_link", new_callable=AsyncMock):
            body = RequestLinkBody(email="existing@example.com", locale="et")
            await request_magic_link(body, make_request(), mock_db)

        # The email sends in the requested locale, but the stored user row
        # is never mutated by this unauthenticated endpoint.
        assert existing_user.locale == "en"
