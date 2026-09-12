"""Tests for the organizer auth stack — magic-link request/verify/logout-all
and the get_current_organizer dependency. Mirrors tests/auth/test_auth.py's
structure and DB-mocking approach for the consumer auth stack."""
import http
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from itsdangerous import BadSignature

from app.auth.tokens import (
    generate_oauth_state_token,
    generate_organizer_magic_token,
    generate_organizer_session_token,
    generate_magic_token,
    generate_session_token,
    hash_token,
    verify_oauth_state_token,
    verify_organizer_magic_token,
    verify_organizer_session_token,
    verify_session_token,
)
from tests.auth.conftest import mock_execute_returning
from tests.conftest import assert_hardened_cookie


class TestOAuthStateToken:
    def test_roundtrip(self):
        token = generate_oauth_state_token("s1", "verifier1", track="organizer")
        payload = verify_oauth_state_token(token, track="organizer")
        assert payload == {"state": "s1", "code_verifier": "verifier1", "track": "organizer"}

    def test_wrong_track_rejected(self):
        """A state token minted for one track must never verify against the
        other track's callback — mirrors the user/organizer token separation."""
        token = generate_oauth_state_token("s1", "verifier1", track="organizer")
        with pytest.raises(BadSignature):
            verify_oauth_state_token(token, track="user")

    def test_bad_signature_raises(self):
        token = generate_oauth_state_token("s1", "verifier1", track="organizer")
        with pytest.raises(BadSignature):
            verify_oauth_state_token(token + "x", track="organizer")


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
    async def test_valid_token_sets_organizer_session_cookie(self, mock_db, make_request):
        from fastapi import Response
        from app.routers.organizer_auth import VerifyTokenBody, verify_organizer_magic_link

        token, _, _ = generate_organizer_magic_token(3)
        mock_db.execute = mock_execute_returning((3, None))

        organizer = MagicMock()
        organizer.id = 3
        organizer.email = "org@example.com"
        organizer.locale = "en"
        organizer.session_token_version = 1
        mock_db.get.return_value = organizer

        response = Response()
        result = await verify_organizer_magic_link(
            make_request(path="/organizer/auth/verify"),
            VerifyTokenBody(token=token),
            response,
            mock_db,
        )

        assert "session_token" not in result
        assert result["organizer"]["id"] == 3

        set_cookie = response.headers["set-cookie"]
        assert_hardened_cookie(set_cookie, name="organizer_session", path="/api/organizer")
        cookie_value = set_cookie.split("organizer_session=", 1)[1].split(";", 1)[0]
        assert verify_organizer_session_token(cookie_value) == (3, 1)

    @pytest.mark.asyncio
    async def test_second_use_raises_400(self, mock_db, make_request):
        """Single-use: the atomic UPDATE finds no matching row the second time
        (used_at already set), so a token replay is rejected."""
        from fastapi import HTTPException, Response
        from app.routers.organizer_auth import VerifyTokenBody, verify_organizer_magic_link

        token, _, _ = generate_organizer_magic_token(3)
        mock_db.execute = mock_execute_returning(None)

        with pytest.raises(HTTPException) as exc_info:
            await verify_organizer_magic_link(
                make_request(path="/organizer/auth/verify"),
                VerifyTokenBody(token=token),
                Response(),
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_bad_signature_raises_400(self, mock_db, make_request):
        from fastapi import HTTPException, Response
        from app.routers.organizer_auth import VerifyTokenBody, verify_organizer_magic_link

        with pytest.raises(HTTPException) as exc_info:
            await verify_organizer_magic_link(
                make_request(path="/organizer/auth/verify"),
                VerifyTokenBody(token="garbage"),
                Response(),
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST


class TestGetCurrentOrganizer:
    @pytest.mark.asyncio
    async def test_valid_session_cookie_returns_organizer(self, mock_db, make_organizer):
        from app.routers.organizer_auth import get_current_organizer

        organizer = make_organizer(organizer_id=7)
        mock_db.get.return_value = organizer

        token = generate_organizer_session_token(7, 1)
        result = await get_current_organizer(organizer_session=token, db=mock_db)
        assert result.id == 7

    @pytest.mark.asyncio
    async def test_missing_cookie_raises_401(self, mock_db):
        from fastapi import HTTPException
        from app.routers.organizer_auth import get_current_organizer

        with pytest.raises(HTTPException) as exc_info:
            await get_current_organizer(organizer_session=None, db=mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_user_session_token_rejected(self, mock_db):
        """A consumer session token must not authenticate as an organizer —
        distinct salts make verify_organizer_session_token raise BadSignature."""
        from fastapi import HTTPException
        from app.routers.organizer_auth import get_current_organizer

        user_token = generate_session_token(7, 1)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_organizer(organizer_session=user_token, db=mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_revoked_session_raises_401(self, mock_db, make_organizer):
        from fastapi import HTTPException
        from app.routers.organizer_auth import get_current_organizer

        organizer = make_organizer(organizer_id=7, session_token_version=2)
        mock_db.get.return_value = organizer

        token = generate_organizer_session_token(7, 1)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_organizer(organizer_session=token, db=mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.UNAUTHORIZED


class TestOrganizerLogout:
    @pytest.mark.asyncio
    async def test_expires_organizer_cookie_without_bumping_version(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import Response
        from app.routers.organizer_auth import organizer_logout

        response = Response()
        result = await organizer_logout(
            request=make_request(method="POST", path="/organizer/auth/logout"),
            response=response,
        )

        assert_hardened_cookie(
            response.headers["set-cookie"],
            name="organizer_session",
            path="/api/organizer",
            cleared=True,
        )
        assert "detail" in result

    @pytest.mark.asyncio
    async def test_idempotent_with_no_session_at_all(self, mock_db, make_request):
        """OWASP audit F18: logout must not depend on a valid session — an
        already-expired/revoked cookie still gets a 200 and gets cleared."""
        from fastapi import Response
        from app.routers.organizer_auth import organizer_logout

        response = Response()
        result = await organizer_logout(
            request=make_request(method="POST", path="/organizer/auth/logout"),
            response=response,
        )

        assert_hardened_cookie(
            response.headers["set-cookie"],
            name="organizer_session",
            path="/api/organizer",
            cleared=True,
        )
        assert "detail" in result


class TestOrganizerLogoutAll:
    @pytest.mark.asyncio
    async def test_increments_session_token_version_and_clears_cookie(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import Response
        from app.routers.organizer_auth import organizer_logout_all

        organizer = make_organizer(organizer_id=7)
        execute_result = MagicMock()
        execute_result.scalar_one.return_value = 2
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        response = Response()
        result = await organizer_logout_all(
            request=make_request(method="POST", path="/organizer/auth/logout-all"),
            response=response,
            current_organizer=organizer,
            db=mock_db,
        )

        assert organizer.session_token_version == 2
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()
        assert "detail" in result
        assert_hardened_cookie(
            response.headers["set-cookie"],
            name="organizer_session",
            path="/api/organizer",
            cleared=True,
        )


def _set_cookie_headers(response) -> list[str]:
    """Collect every Set-Cookie header value — the callback can set both the
    organizer_session cookie and clear organizer_oauth_state in one response,
    which response.headers["set-cookie"] (a single-value lookup) can't see."""
    return [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]


GOOGLE_IDENTITY_AUTHORITATIVE = {
    "sub": "sub-1",
    "email": "person@gmail.com",
    "email_verified": True,
    "hd": None,
}
GOOGLE_IDENTITY_NON_AUTHORITATIVE = {
    "sub": "sub-2",
    "email": "person@yahoo.com",
    "email_verified": True,
    "hd": None,
}


class TestApplyGoogleLinkingGate:
    @pytest.mark.asyncio
    async def test_existing_identity_returns_existing_login(self, mock_db, make_organizer):
        from app.routers.organizer_auth import _apply_google_linking_gate

        identity_row = MagicMock(organizer_id=7)
        mock_db.scalar = AsyncMock(return_value=identity_row)
        organizer = make_organizer(organizer_id=7)
        mock_db.get = AsyncMock(return_value=organizer)

        outcome, result_organizer = await _apply_google_linking_gate(
            mock_db, GOOGLE_IDENTITY_AUTHORITATIVE
        )

        assert outcome == "existing_login"
        assert result_organizer is organizer
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_identity_no_organizer_authoritative_creates_new_account(self, mock_db):
        from app.routers.organizer_auth import _apply_google_linking_gate

        mock_db.scalar = AsyncMock(side_effect=[None, None])

        def _add_side_effect(obj):
            if hasattr(obj, "id"):
                obj.id = 1

        mock_db.add = MagicMock(side_effect=_add_side_effect)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        outcome, organizer = await _apply_google_linking_gate(
            mock_db, GOOGLE_IDENTITY_AUTHORITATIVE
        )

        assert outcome == "new_account"
        assert organizer is not None
        assert organizer.email == "person@gmail.com"
        assert mock_db.add.call_count == 2  # Organizer, then OrganizerIdentity
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_concurrent_identity_insert_falls_back_to_existing_login(
        self, mock_db, make_organizer
    ):
        """Two concurrent callbacks for the same Google account (double-click,
        two tabs) both try to INSERT the identity row; the loser's commit
        hits the UniqueConstraint("provider", "provider_sub") and must fall
        back gracefully, never surface a 500."""
        from sqlalchemy.exc import IntegrityError

        from app.routers.organizer_auth import _apply_google_linking_gate

        organizer = make_organizer(organizer_id=7)
        winning_identity_row = MagicMock(organizer_id=7)
        mock_db.scalar = AsyncMock(side_effect=[None, None, winning_identity_row])
        mock_db.get = AsyncMock(return_value=organizer)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("dup")))
        mock_db.rollback = AsyncMock()

        outcome, result_organizer = await _apply_google_linking_gate(
            mock_db, GOOGLE_IDENTITY_AUTHORITATIVE
        )

        assert outcome == "existing_login"
        assert result_organizer is organizer
        mock_db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_identity_existing_organizer_authoritative_auto_links(
        self, mock_db, make_organizer
    ):
        from app.routers.organizer_auth import _apply_google_linking_gate

        existing_organizer = make_organizer(organizer_id=5)
        mock_db.scalar = AsyncMock(side_effect=[None, existing_organizer])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        outcome, organizer = await _apply_google_linking_gate(
            mock_db, GOOGLE_IDENTITY_AUTHORITATIVE
        )

        assert outcome == "auto_linked"
        assert organizer is existing_organizer
        mock_db.add.assert_called_once()
        added_identity = mock_db.add.call_args.args[0]
        assert added_identity.organizer_id == 5
        assert added_identity.provider_sub == "sub-1"

    @pytest.mark.asyncio
    async def test_no_identity_existing_organizer_non_authoritative_sends_confirmation(
        self, mock_db, make_organizer
    ):
        from app.routers.organizer_auth import _apply_google_linking_gate

        existing_organizer = make_organizer(organizer_id=5)
        mock_db.scalar = AsyncMock(side_effect=[None, existing_organizer, None])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.organizer_auth.send_magic_link", new_callable=AsyncMock
        ) as mock_send:
            outcome, organizer = await _apply_google_linking_gate(
                mock_db, GOOGLE_IDENTITY_NON_AUTHORITATIVE
            )

        assert outcome == "confirmation_sent"
        assert organizer is None
        mock_send.assert_called_once()
        added_link = mock_db.add.call_args.args[0]
        assert added_link.pending_google_sub == "sub-2"

    @pytest.mark.asyncio
    async def test_no_identity_no_organizer_non_authoritative_creates_unverified_row(
        self, mock_db
    ):
        from app.routers.organizer_auth import _apply_google_linking_gate

        mock_db.scalar = AsyncMock(side_effect=[None, None, None, None])

        def _add_side_effect(obj):
            if hasattr(obj, "id"):
                obj.id = 9

        mock_db.add = MagicMock(side_effect=_add_side_effect)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.organizer_auth.send_magic_link", new_callable=AsyncMock
        ) as mock_send:
            outcome, organizer = await _apply_google_linking_gate(
                mock_db, GOOGLE_IDENTITY_NON_AUTHORITATIVE
            )

        assert outcome == "confirmation_sent"
        assert organizer is None
        mock_send.assert_called_once()


class TestGoogleSigninStart:
    @pytest.mark.asyncio
    async def test_404_when_disabled(self, monkeypatch, make_request):
        from fastapi import HTTPException
        from app.config import settings
        from app.routers.organizer_auth import start_organizer_google_signin

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_ORGANIZER_ENABLED", False)
        with pytest.raises(HTTPException) as exc_info:
            await start_organizer_google_signin(
                make_request(method="GET", path="/organizer/auth/google/start")
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_redirects_to_google_and_sets_state_cookie(self, monkeypatch, make_request):
        from app.config import settings
        from app.routers.organizer_auth import start_organizer_google_signin

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_ORGANIZER_ENABLED", True)
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "cid")
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.com")

        response = await start_organizer_google_signin(
            make_request(method="GET", path="/organizer/auth/google/start")
        )

        assert response.status_code == http.HTTPStatus.FOUND
        assert response.headers["location"].startswith(
            "https://accounts.google.com/o/oauth2/v2/auth?"
        )
        set_cookie = response.headers["set-cookie"]
        assert "organizer_oauth_state=" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "Path=/api/organizer/auth/google/callback" in set_cookie


class TestGoogleSigninCallback:
    def _enable(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_ORGANIZER_ENABLED", True)
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.com")

    @pytest.mark.asyncio
    async def test_404_when_disabled(self, monkeypatch, make_request, mock_db):
        from fastapi import HTTPException
        from app.config import settings
        from app.routers.organizer_auth import organizer_google_callback

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_ORGANIZER_ENABLED", False)
        with pytest.raises(HTTPException) as exc_info:
            await organizer_google_callback(
                make_request(path="/organizer/auth/google/callback"),
                code="c",
                state="s",
                error=None,
                organizer_oauth_state=None,
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_google_denied_redirects_with_error(self, monkeypatch, make_request, mock_db):
        self._enable(monkeypatch)
        from app.routers.organizer_auth import organizer_google_callback

        response = await organizer_google_callback(
            make_request(path="/organizer/auth/google/callback"),
            code=None,
            state=None,
            error="access_denied",
            organizer_oauth_state=None,
            db=mock_db,
        )
        assert response.status_code == http.HTTPStatus.FOUND
        assert "google_error=access_denied" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_missing_state_cookie_redirects_with_error(
        self, monkeypatch, make_request, mock_db
    ):
        self._enable(monkeypatch)
        from app.routers.organizer_auth import organizer_google_callback

        response = await organizer_google_callback(
            make_request(path="/organizer/auth/google/callback"),
            code="c",
            state="s",
            error=None,
            organizer_oauth_state=None,
            db=mock_db,
        )
        assert "google_error=state_invalid" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_tampered_state_cookie_redirects_with_error(
        self, monkeypatch, make_request, mock_db
    ):
        self._enable(monkeypatch)
        from app.routers.organizer_auth import organizer_google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="organizer") + "x"
        response = await organizer_google_callback(
            make_request(path="/organizer/auth/google/callback"),
            code="c",
            state="s1",
            error=None,
            organizer_oauth_state=cookie,
            db=mock_db,
        )
        assert "google_error=state_invalid" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_state_param_mismatch_redirects_with_error(
        self, monkeypatch, make_request, mock_db
    ):
        self._enable(monkeypatch)
        from app.routers.organizer_auth import organizer_google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="organizer")
        response = await organizer_google_callback(
            make_request(path="/organizer/auth/google/callback"),
            code="c",
            state="different-state",
            error=None,
            organizer_oauth_state=cookie,
            db=mock_db,
        )
        assert "google_error=state_invalid" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_token_exchange_network_failure_redirects_never_500(
        self, monkeypatch, make_request, mock_db
    ):
        import httpx

        self._enable(monkeypatch)
        from app.routers.organizer_auth import organizer_google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="organizer")
        with patch(
            "app.routers.organizer_auth.exchange_code_for_id_token",
            new=AsyncMock(side_effect=httpx.ConnectError("boom")),
        ):
            response = await organizer_google_callback(
                make_request(path="/organizer/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                organizer_oauth_state=cookie,
                db=mock_db,
            )
        assert response.status_code == http.HTTPStatus.FOUND
        assert "google_error=token_exchange_failed" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_malformed_token_response_redirects_never_500(
        self, monkeypatch, make_request, mock_db
    ):
        from app.auth.google_oauth import GoogleTokenExchangeError

        self._enable(monkeypatch)
        from app.routers.organizer_auth import organizer_google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="organizer")
        with patch(
            "app.routers.organizer_auth.exchange_code_for_id_token",
            new=AsyncMock(side_effect=GoogleTokenExchangeError("no id_token")),
        ):
            response = await organizer_google_callback(
                make_request(path="/organizer/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                organizer_oauth_state=cookie,
                db=mock_db,
            )
        assert response.status_code == http.HTTPStatus.FOUND
        assert "google_error=token_exchange_failed" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_id_token_verification_failure_redirects(
        self, monkeypatch, make_request, mock_db
    ):
        import jwt as pyjwt

        self._enable(monkeypatch)
        from app.routers.organizer_auth import organizer_google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="organizer")
        with patch(
            "app.routers.organizer_auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.organizer_auth.verify_google_id_token",
            side_effect=pyjwt.InvalidTokenError("bad token"),
        ):
            response = await organizer_google_callback(
                make_request(path="/organizer/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                organizer_oauth_state=cookie,
                db=mock_db,
            )
        assert "google_error=verification_failed" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_jwks_fetch_failure_is_degraded_not_verification_failed(
        self, monkeypatch, make_request, mock_db
    ):
        import jwt as pyjwt

        self._enable(monkeypatch)
        from app.routers.organizer_auth import organizer_google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="organizer")
        with patch(
            "app.routers.organizer_auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.organizer_auth.verify_google_id_token",
            side_effect=pyjwt.PyJWKClientError("network"),
        ):
            response = await organizer_google_callback(
                make_request(path="/organizer/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                organizer_oauth_state=cookie,
                db=mock_db,
            )
        assert "google_error=token_exchange_failed" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_success_mints_session_and_clears_state_cookie(
        self, monkeypatch, make_request, mock_db, make_organizer
    ):
        self._enable(monkeypatch)
        from app.routers.organizer_auth import organizer_google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="organizer")
        organizer = make_organizer(organizer_id=7)
        with patch(
            "app.routers.organizer_auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.organizer_auth.verify_google_id_token",
            return_value=GOOGLE_IDENTITY_AUTHORITATIVE,
        ), patch(
            "app.routers.organizer_auth._apply_google_linking_gate",
            new=AsyncMock(return_value=("existing_login", organizer)),
        ):
            response = await organizer_google_callback(
                make_request(path="/organizer/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                organizer_oauth_state=cookie,
                db=mock_db,
            )

        assert response.status_code == http.HTTPStatus.FOUND
        assert response.headers["location"] == "https://app.example.com/organizer/dashboard"
        cookies = _set_cookie_headers(response)
        assert any("organizer_session=" in c and "HttpOnly" in c for c in cookies)
        assert any(
            "organizer_oauth_state=" in c and "Max-Age=0" in c for c in cookies
        )

    @pytest.mark.asyncio
    async def test_confirmation_sent_redirects_to_login_without_session(
        self, monkeypatch, make_request, mock_db
    ):
        self._enable(monkeypatch)
        from app.routers.organizer_auth import organizer_google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="organizer")
        with patch(
            "app.routers.organizer_auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.organizer_auth.verify_google_id_token",
            return_value=GOOGLE_IDENTITY_NON_AUTHORITATIVE,
        ), patch(
            "app.routers.organizer_auth._apply_google_linking_gate",
            new=AsyncMock(return_value=("confirmation_sent", None)),
        ):
            response = await organizer_google_callback(
                make_request(path="/organizer/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                organizer_oauth_state=cookie,
                db=mock_db,
            )

        assert response.status_code == http.HTTPStatus.FOUND
        assert response.headers["location"] == "https://app.example.com/organizer/login"
        cookies = _set_cookie_headers(response)
        assert not any("organizer_session=" in c for c in cookies)
        assert any("organizer_oauth_state=" in c and "Max-Age=0" in c for c in cookies)
