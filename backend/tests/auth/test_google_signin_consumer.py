"""Tests for the consumer-track Google sign-in endpoints (ADR 0002, #296) —
_apply_google_linking_gate, /auth/google/start, /auth/google/callback.
Mirrors tests/auth/test_organizer_auth.py's Google-sign-in sections; the
extra TestApplyGoogleLinkingGate cases cover the consumer-only
email_verified flip on the auto-link/absorb paths (no organizer equivalent —
Organizer has no email_verified column)."""
import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.auth.tokens import generate_oauth_state_token


def _set_cookie_headers(response):
    """A callback response can set two cookies (session and clearing
    oauth_state) in one response, which response.headers["set-cookie"] (a
    single-value lookup) can't see."""
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
    async def test_existing_identity_returns_existing_login(self, mock_db, make_user):
        from app.routers.auth import _apply_google_linking_gate

        identity_row = MagicMock(user_id=7)
        mock_db.scalar = AsyncMock(return_value=identity_row)
        user = make_user(user_id=7)
        mock_db.get = AsyncMock(return_value=user)

        outcome, result_user = await _apply_google_linking_gate(
            mock_db, GOOGLE_IDENTITY_AUTHORITATIVE
        )

        assert outcome == "existing_login"
        assert result_user is user
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_identity_no_user_authoritative_creates_new_account(self, mock_db):
        from app.routers.auth import _apply_google_linking_gate

        mock_db.scalar = AsyncMock(side_effect=[None, None])

        def _add_side_effect(obj):
            if hasattr(obj, "id"):
                obj.id = 1

        mock_db.add = MagicMock(side_effect=_add_side_effect)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        outcome, user = await _apply_google_linking_gate(
            mock_db, GOOGLE_IDENTITY_AUTHORITATIVE
        )

        assert outcome == "new_account"
        assert user is not None
        assert user.email == "person@gmail.com"
        assert user.email_verified is True
        assert mock_db.add.call_count == 2  # User, then UserIdentity
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_concurrent_identity_insert_falls_back_to_existing_login(
        self, mock_db, make_user
    ):
        """Two concurrent callbacks for the same Google account (double-click,
        two tabs) both try to INSERT the identity row; the loser's commit
        hits the UniqueConstraint("provider", "provider_sub") and must fall
        back gracefully, never surface a 500."""
        from sqlalchemy.exc import IntegrityError

        from app.routers.auth import _apply_google_linking_gate

        user = make_user(user_id=7)
        winning_identity_row = MagicMock(user_id=7)
        mock_db.scalar = AsyncMock(side_effect=[None, None, winning_identity_row])
        mock_db.get = AsyncMock(return_value=user)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("dup")))
        mock_db.rollback = AsyncMock()

        outcome, result_user = await _apply_google_linking_gate(
            mock_db, GOOGLE_IDENTITY_AUTHORITATIVE
        )

        assert outcome == "existing_login"
        assert result_user is user
        mock_db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_identity_existing_user_authoritative_auto_links(
        self, mock_db, make_user
    ):
        from app.routers.auth import _apply_google_linking_gate

        existing_user = make_user(user_id=5, email_verified=True)
        mock_db.scalar = AsyncMock(side_effect=[None, existing_user])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        outcome, user = await _apply_google_linking_gate(
            mock_db, GOOGLE_IDENTITY_AUTHORITATIVE
        )

        assert outcome == "auto_linked"
        assert user is existing_user
        mock_db.add.assert_called_once()
        added_identity = mock_db.add.call_args.args[0]
        assert added_identity.user_id == 5
        assert added_identity.provider_sub == "sub-1"

    @pytest.mark.asyncio
    async def test_no_identity_existing_user_non_authoritative_sends_confirmation(
        self, mock_db, make_user
    ):
        from app.routers.auth import _apply_google_linking_gate

        existing_user = make_user(user_id=5, email_verified=True)
        mock_db.scalar = AsyncMock(side_effect=[None, existing_user, None])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.auth.send_google_link_confirmation", new_callable=AsyncMock
        ) as mock_send:
            outcome, user = await _apply_google_linking_gate(
                mock_db, GOOGLE_IDENTITY_NON_AUTHORITATIVE
            )

        assert outcome == "confirmation_sent"
        assert user is None
        mock_send.assert_called_once()
        added_link = mock_db.add.call_args.args[0]
        assert added_link.pending_google_sub == "sub-2"

    @pytest.mark.asyncio
    async def test_no_identity_no_user_non_authoritative_creates_unverified_row(
        self, mock_db
    ):
        from app.routers.auth import _apply_google_linking_gate

        mock_db.scalar = AsyncMock(side_effect=[None, None, None, None])

        def _add_side_effect(obj):
            if hasattr(obj, "id"):
                obj.id = 9

        mock_db.add = MagicMock(side_effect=_add_side_effect)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.auth.send_google_link_confirmation", new_callable=AsyncMock
        ) as mock_send:
            outcome, user = await _apply_google_linking_gate(
                mock_db, GOOGLE_IDENTITY_NON_AUTHORITATIVE
            )

        assert outcome == "confirmation_sent"
        assert user is None
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_unverified_existing_row_non_authoritative_requires_confirmation(
        self, mock_db, make_user
    ):
        """OWASP audit M-1 fix: a non-authoritative Google identity must
        never absorb an existing unverified User row outright — the row's
        email address is the very thing being claimed, and Google is not
        authoritative for it. It must fall through to the confirmation
        magic-link path instead, exactly like the no-existing-user case, and
        create no UserIdentity row / session for the caller."""
        from app.routers.auth import _apply_google_linking_gate

        existing_user = make_user(user_id=5, email_verified=False)
        mock_db.scalar = AsyncMock(side_effect=[None, existing_user])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.auth._send_google_confirmation_link", new=AsyncMock()
        ) as mock_send:
            outcome, user = await _apply_google_linking_gate(
                mock_db, GOOGLE_IDENTITY_NON_AUTHORITATIVE
            )

        assert outcome == "confirmation_sent"
        assert user is None
        mock_db.add.assert_not_called()
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_unverified_existing_row_authoritative_auto_links(
        self, mock_db, make_user
    ):
        """An authoritative identity (e.g. @gmail.com) may still absorb an
        unverified existing row — that path is gated on authoritative-ness,
        not bypassed for it."""
        from app.routers.auth import _apply_google_linking_gate

        existing_user = make_user(user_id=5, email_verified=False)
        mock_db.scalar = AsyncMock(side_effect=[None, existing_user])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        outcome, user = await _apply_google_linking_gate(
            mock_db, GOOGLE_IDENTITY_AUTHORITATIVE
        )

        assert outcome == "auto_linked"
        assert user is existing_user
        assert existing_user.email_verified is True
        added_identity = mock_db.add.call_args.args[0]
        assert added_identity.user_id == 5
        assert added_identity.provider_sub == "sub-1"

    @pytest.mark.asyncio
    async def test_unverified_existing_row_authoritative_race_falls_back(
        self, mock_db, make_user
    ):
        from sqlalchemy.exc import IntegrityError

        from app.routers.auth import _apply_google_linking_gate

        existing_user = make_user(user_id=5, email_verified=False)
        winning_identity_row = MagicMock(user_id=5)
        mock_db.scalar = AsyncMock(side_effect=[None, existing_user, winning_identity_row])
        mock_db.get = AsyncMock(return_value=existing_user)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("dup")))
        mock_db.rollback = AsyncMock()

        outcome, user = await _apply_google_linking_gate(
            mock_db, GOOGLE_IDENTITY_AUTHORITATIVE
        )

        assert outcome == "existing_login"
        assert user is existing_user
        mock_db.rollback.assert_awaited_once()


class TestGoogleSigninStart:
    @pytest.mark.asyncio
    async def test_404_when_disabled(self, monkeypatch, make_request):
        from fastapi import HTTPException
        from app.config import settings
        from app.routers.auth import start_google_signin

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_CONSUMER_ENABLED", False)
        with pytest.raises(HTTPException) as exc_info:
            await start_google_signin(
                make_request(method="GET", path="/auth/google/start")
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_redirects_to_google_and_sets_state_cookie(self, monkeypatch, make_request):
        from app.config import settings
        from app.routers.auth import start_google_signin

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_CONSUMER_ENABLED", True)
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "cid")
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.com")

        response = await start_google_signin(
            make_request(method="GET", path="/auth/google/start")
        )

        assert response.status_code == http.HTTPStatus.FOUND
        assert response.headers["location"].startswith(
            "https://accounts.google.com/o/oauth2/v2/auth?"
        )
        set_cookie = response.headers["set-cookie"]
        assert "oauth_state=" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "Path=/api/auth/google/callback" in set_cookie


class TestGoogleSigninCallback:
    def _enable(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_CONSUMER_ENABLED", True)
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.com")

    @pytest.mark.asyncio
    async def test_404_when_disabled(self, monkeypatch, make_request, mock_db):
        from fastapi import HTTPException
        from app.config import settings
        from app.routers.auth import google_callback

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_CONSUMER_ENABLED", False)
        with pytest.raises(HTTPException) as exc_info:
            await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s",
                error=None,
                oauth_state=None,
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_google_denied_redirects_with_error(self, monkeypatch, make_request, mock_db):
        self._enable(monkeypatch)
        from app.routers.auth import google_callback

        response = await google_callback(
            make_request(path="/auth/google/callback"),
            code=None,
            state=None,
            error="access_denied",
            oauth_state=None,
            db=mock_db,
        )
        assert response.status_code == http.HTTPStatus.FOUND
        assert "google_error=access_denied" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_missing_state_cookie_redirects_with_error(
        self, monkeypatch, make_request, mock_db
    ):
        self._enable(monkeypatch)
        from app.routers.auth import google_callback

        response = await google_callback(
            make_request(path="/auth/google/callback"),
            code="c",
            state="s",
            error=None,
            oauth_state=None,
            db=mock_db,
        )
        assert "google_error=state_invalid" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_tampered_state_cookie_redirects_with_error(
        self, monkeypatch, make_request, mock_db
    ):
        self._enable(monkeypatch)
        from app.routers.auth import google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="user") + "x"
        response = await google_callback(
            make_request(path="/auth/google/callback"),
            code="c",
            state="s1",
            error=None,
            oauth_state=cookie,
            db=mock_db,
        )
        assert "google_error=state_invalid" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_state_param_mismatch_redirects_with_error(
        self, monkeypatch, make_request, mock_db
    ):
        self._enable(monkeypatch)
        from app.routers.auth import google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="user")
        response = await google_callback(
            make_request(path="/auth/google/callback"),
            code="c",
            state="different-state",
            error=None,
            oauth_state=cookie,
            db=mock_db,
        )
        assert "google_error=state_invalid" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_organizer_state_token_rejected_on_consumer_callback(
        self, monkeypatch, make_request, mock_db
    ):
        """Cross-track independence (#296): a state token minted for the
        organizer track's callback must never be replayed against the
        consumer callback, and vice versa."""
        self._enable(monkeypatch)
        from app.routers.auth import google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="organizer")
        response = await google_callback(
            make_request(path="/auth/google/callback"),
            code="c",
            state="s1",
            error=None,
            oauth_state=cookie,
            db=mock_db,
        )
        assert "google_error=state_invalid" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_token_exchange_network_failure_redirects_never_500(
        self, monkeypatch, make_request, mock_db
    ):
        import httpx

        self._enable(monkeypatch)
        from app.routers.auth import google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="user")
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(side_effect=httpx.ConnectError("boom")),
        ):
            response = await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
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
        from app.routers.auth import google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="user")
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(side_effect=GoogleTokenExchangeError("no id_token")),
        ):
            response = await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
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
        from app.routers.auth import google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="user")
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.auth.verify_google_id_token",
            side_effect=pyjwt.InvalidTokenError("bad token"),
        ):
            response = await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
                db=mock_db,
            )
        assert "google_error=verification_failed" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_jwks_fetch_failure_is_degraded_not_verification_failed(
        self, monkeypatch, make_request, mock_db
    ):
        import jwt as pyjwt

        self._enable(monkeypatch)
        from app.routers.auth import google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="user")
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.auth.verify_google_id_token",
            side_effect=pyjwt.PyJWKClientError("network"),
        ):
            response = await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
                db=mock_db,
            )
        assert "google_error=token_exchange_failed" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_new_account_redirects_to_onboarding(
        self, monkeypatch, make_request, mock_db, make_user
    ):
        self._enable(monkeypatch)
        from app.routers.auth import google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="user")
        user = make_user(user_id=7)
        user.session_token_version = 1
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.auth.verify_google_id_token",
            return_value=GOOGLE_IDENTITY_AUTHORITATIVE,
        ), patch(
            "app.routers.auth._apply_google_linking_gate",
            new=AsyncMock(return_value=("new_account", user)),
        ):
            response = await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
                db=mock_db,
            )

        assert response.status_code == http.HTTPStatus.FOUND
        assert (
            response.headers["location"]
            == "https://app.example.com/onboarding?google_signin=user"
        )
        cookies = _set_cookie_headers(response)
        assert any("session=" in c and "HttpOnly" in c for c in cookies)
        assert any("oauth_state=" in c and "Max-Age=0" in c for c in cookies)

    @pytest.mark.asyncio
    async def test_existing_login_redirects_to_home(
        self, monkeypatch, make_request, mock_db, make_user
    ):
        self._enable(monkeypatch)
        from app.routers.auth import google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="user")
        user = make_user(user_id=7)
        user.session_token_version = 1
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.auth.verify_google_id_token",
            return_value=GOOGLE_IDENTITY_AUTHORITATIVE,
        ), patch(
            "app.routers.auth._apply_google_linking_gate",
            new=AsyncMock(return_value=("existing_login", user)),
        ):
            response = await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
                db=mock_db,
            )

        assert response.status_code == http.HTTPStatus.FOUND
        assert response.headers["location"] == "https://app.example.com/?google_signin=user"
        cookies = _set_cookie_headers(response)
        assert any("session=" in c and "HttpOnly" in c for c in cookies)

    @pytest.mark.asyncio
    async def test_confirmation_sent_redirects_to_login_without_session(
        self, monkeypatch, make_request, mock_db
    ):
        self._enable(monkeypatch)
        from app.routers.auth import google_callback

        cookie = generate_oauth_state_token("s1", "v1", track="user")
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.auth.verify_google_id_token",
            return_value=GOOGLE_IDENTITY_NON_AUTHORITATIVE,
        ), patch(
            "app.routers.auth._apply_google_linking_gate",
            new=AsyncMock(return_value=("confirmation_sent", None)),
        ):
            response = await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
                db=mock_db,
            )

        assert response.status_code == http.HTTPStatus.FOUND
        assert response.headers["location"] == "https://app.example.com/login"
        cookies = _set_cookie_headers(response)
        assert not any("session=" in c for c in cookies)


GOOGLE_IDENTITY_UNVERIFIED = {
    "sub": "sub-3",
    "email": "person@yahoo.com",
    "email_verified": False,
    "hd": None,
}


class TestGoogleLinkHardening:
    """OWASP audit #3 — consumer track."""

    @pytest.mark.asyncio
    async def test_gate_unverified_non_authoritative_sends_nothing(self, mock_db):
        from app.routers.auth import _apply_google_linking_gate

        mock_db.scalar = AsyncMock(side_effect=[None, None])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.auth.send_google_link_confirmation", new_callable=AsyncMock
        ) as mock_send:
            outcome, user = await _apply_google_linking_gate(
                mock_db, GOOGLE_IDENTITY_UNVERIFIED
            )

        assert outcome == "unverified_email"
        assert user is None
        mock_send.assert_not_called()
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_unverified_redirects_with_error_and_no_cookie(
        self, monkeypatch, make_request, mock_db
    ):
        from app.config import settings
        from app.routers.auth import google_callback

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_CONSUMER_ENABLED", True)
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.com")
        cookie = generate_oauth_state_token("s1", "v1", track="user")
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.auth.verify_google_id_token",
            return_value=GOOGLE_IDENTITY_UNVERIFIED,
        ), patch(
            "app.routers.auth._apply_google_linking_gate",
            new=AsyncMock(return_value=("unverified_email", None)),
        ):
            response = await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
                db=mock_db,
            )

        assert "google_error=verification_failed" in response.headers["location"]
        assert not any(
            "google_link_binding=" in c and "Max-Age=0" not in c
            for c in _set_cookie_headers(response)
        )

    @pytest.mark.asyncio
    async def test_confirmation_sent_sets_binding_cookie_for_pending_sub(
        self, monkeypatch, make_request, mock_db
    ):
        from app.auth.tokens import google_link_binding_matches
        from app.config import settings
        from app.routers.auth import google_callback

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_CONSUMER_ENABLED", True)
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.com")
        cookie = generate_oauth_state_token("s1", "v1", track="user")
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.auth.verify_google_id_token",
            return_value=GOOGLE_IDENTITY_NON_AUTHORITATIVE,
        ), patch(
            "app.routers.auth._apply_google_linking_gate",
            new=AsyncMock(return_value=("confirmation_sent", None)),
        ):
            response = await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
                db=mock_db,
            )

        binding_cookies = [
            c for c in _set_cookie_headers(response) if c.startswith("google_link_binding=")
        ]
        assert len(binding_cookies) == 1
        set_cookie = binding_cookies[0]
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "SameSite=strict" in set_cookie
        assert "Path=/api/auth/verify" in set_cookie
        value = set_cookie.split("google_link_binding=", 1)[1].split(";", 1)[0]
        assert google_link_binding_matches(value, sub="sub-2", track="user")
        assert not google_link_binding_matches(value, sub="sub-2", track="organizer")

    @pytest.mark.asyncio
    async def test_auto_link_sends_identity_linked_notice(
        self, monkeypatch, make_request, mock_db, make_user
    ):
        from app.config import settings
        from app.routers.auth import google_callback

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_CONSUMER_ENABLED", True)
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.com")
        cookie = generate_oauth_state_token("s1", "v1", track="user")
        user = make_user(user_id=7)
        user.email = "owner@gmail.com"
        user.session_token_version = 1
        user.locale = "et"
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.auth.verify_google_id_token",
            return_value=GOOGLE_IDENTITY_AUTHORITATIVE,
        ), patch(
            "app.routers.auth._apply_google_linking_gate",
            new=AsyncMock(return_value=("auto_linked", user)),
        ), patch(
            "app.routers.auth.send_identity_linked_notice", new_callable=AsyncMock
        ) as mock_notice:
            await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
                db=mock_db,
            )

        mock_notice.assert_awaited_once_with("owner@gmail.com", "et")

    @pytest.mark.asyncio
    async def test_notice_send_failure_does_not_break_sign_in(
        self, monkeypatch, make_request, mock_db, make_user
    ):
        from app.config import settings
        from app.routers.auth import google_callback

        monkeypatch.setattr(settings, "GOOGLE_SIGNIN_CONSUMER_ENABLED", True)
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.com")
        cookie = generate_oauth_state_token("s1", "v1", track="user")
        user = make_user(user_id=7)
        user.session_token_version = 1
        with patch(
            "app.routers.auth.exchange_code_for_id_token",
            new=AsyncMock(return_value="raw.id.token"),
        ), patch(
            "app.routers.auth.verify_google_id_token",
            return_value=GOOGLE_IDENTITY_AUTHORITATIVE,
        ), patch(
            "app.routers.auth._apply_google_linking_gate",
            new=AsyncMock(return_value=("auto_linked", user)),
        ), patch(
            "app.routers.auth.send_identity_linked_notice",
            new=AsyncMock(side_effect=RuntimeError("resend down")),
        ):
            response = await google_callback(
                make_request(path="/auth/google/callback"),
                code="c",
                state="s1",
                error=None,
                oauth_state=cookie,
                db=mock_db,
            )

        assert response.status_code == http.HTTPStatus.FOUND
        assert any("session=" in c for c in _set_cookie_headers(response))
