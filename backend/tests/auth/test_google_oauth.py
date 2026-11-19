"""Tests for app/auth/google_oauth.py — PKCE, authorization-URL
building, the code-for-token exchange, and ID-token verification."""

import base64
import hashlib
import time
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import settings


class TestGeneratePkcePair:
    def test_verifier_length_within_rfc7636_bounds(self):
        from app.auth.google_oauth import generate_pkce_pair

        code_verifier, _ = generate_pkce_pair()
        assert 43 <= len(code_verifier) <= 128

    def test_challenge_is_sha256_of_verifier(self):
        from app.auth.google_oauth import generate_pkce_pair

        code_verifier, code_challenge = generate_pkce_pair()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert code_challenge == expected
        assert "=" not in code_challenge

    def test_pairs_are_random(self):
        from app.auth.google_oauth import generate_pkce_pair

        a, _ = generate_pkce_pair()
        b, _ = generate_pkce_pair()
        assert a != b


class TestBuildAuthorizationUrl:
    def test_contains_required_params(self, monkeypatch):
        from app.auth.google_oauth import build_authorization_url

        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
        url = build_authorization_url(
            state="s1", code_challenge="c1", redirect_uri="https://example.com/cb"
        )
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=test-client-id" in url
        assert "code_challenge=c1" in url
        assert "code_challenge_method=S256" in url
        assert "state=s1" in url
        assert "scope=openid+email" in url or "scope=openid%20email" in url

    def test_never_requests_profile_scope(self, monkeypatch):
        from app.auth.google_oauth import build_authorization_url

        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
        url = build_authorization_url(
            state="s1", code_challenge="c1", redirect_uri="https://example.com/cb"
        )
        assert "profile" not in url


class TestIsAuthoritativeIdentity:
    def test_gmail_verified_is_authoritative(self):
        from app.auth.google_oauth import is_authoritative_identity

        assert is_authoritative_identity(
            {"sub": "1", "email": "a@gmail.com", "email_verified": True, "hd": None}
        )

    def test_googlemail_verified_is_authoritative(self):
        from app.auth.google_oauth import is_authoritative_identity

        assert is_authoritative_identity(
            {"sub": "1", "email": "a@googlemail.com", "email_verified": True, "hd": None}
        )

    def test_hosted_domain_claim_is_authoritative(self):
        from app.auth.google_oauth import is_authoritative_identity

        assert is_authoritative_identity(
            {
                "sub": "1",
                "email": "a@company.example",
                "email_verified": True,
                "hd": "company.example",
            }
        )

    def test_unverified_gmail_is_not_authoritative(self):
        from app.auth.google_oauth import is_authoritative_identity

        assert not is_authoritative_identity(
            {"sub": "1", "email": "a@gmail.com", "email_verified": False, "hd": None}
        )

    def test_third_party_no_hd_is_not_authoritative(self):
        from app.auth.google_oauth import is_authoritative_identity

        assert not is_authoritative_identity(
            {"sub": "1", "email": "a@yahoo.com", "email_verified": True, "hd": None}
        )


@pytest.fixture
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _sign_test_id_token(private_key, **overrides) -> str:
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id",
        "sub": "1234567890",
        "email": "person@gmail.com",
        "email_verified": True,
        "hd": None,
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})


class TestVerifyGoogleIdToken:
    def test_valid_token_returns_expected_claims_only(
        self, monkeypatch, rsa_keypair
    ):
        from app.auth import google_oauth

        private_key, public_key = rsa_keypair
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
        token = _sign_test_id_token(private_key, hd="acme.example")

        fake_signing_key = MagicMock(key=public_key)
        monkeypatch.setattr(
            google_oauth._jwks_client,
            "get_signing_key_from_jwt",
            MagicMock(return_value=fake_signing_key),
        )

        identity = google_oauth.verify_google_id_token(token)
        assert identity == {
            "sub": "1234567890",
            "email": "person@gmail.com",
            "email_verified": True,
            "hd": "acme.example",
        }
        assert set(identity.keys()) == {"sub", "email", "email_verified", "hd"}

    def test_wrong_audience_rejected(self, monkeypatch, rsa_keypair):
        from app.auth import google_oauth

        private_key, public_key = rsa_keypair
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
        token = _sign_test_id_token(private_key, aud="someone-elses-client-id")

        fake_signing_key = MagicMock(key=public_key)
        monkeypatch.setattr(
            google_oauth._jwks_client,
            "get_signing_key_from_jwt",
            MagicMock(return_value=fake_signing_key),
        )

        with pytest.raises(jwt.PyJWTError):
            google_oauth.verify_google_id_token(token)

    def test_wrong_issuer_rejected(self, monkeypatch, rsa_keypair):
        from app.auth import google_oauth

        private_key, public_key = rsa_keypair
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
        token = _sign_test_id_token(private_key, iss="https://evil.example.com")

        fake_signing_key = MagicMock(key=public_key)
        monkeypatch.setattr(
            google_oauth._jwks_client,
            "get_signing_key_from_jwt",
            MagicMock(return_value=fake_signing_key),
        )

        with pytest.raises(jwt.PyJWTError):
            google_oauth.verify_google_id_token(token)

    def test_expired_token_rejected(self, monkeypatch, rsa_keypair):
        from app.auth import google_oauth

        private_key, public_key = rsa_keypair
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
        now = int(time.time())
        token = _sign_test_id_token(private_key, iat=now - 7200, exp=now - 3600)

        fake_signing_key = MagicMock(key=public_key)
        monkeypatch.setattr(
            google_oauth._jwks_client,
            "get_signing_key_from_jwt",
            MagicMock(return_value=fake_signing_key),
        )

        with pytest.raises(jwt.PyJWTError):
            google_oauth.verify_google_id_token(token)


class TestExchangeCodeForIdToken:
    @pytest.mark.asyncio
    async def test_posts_to_token_endpoint_and_returns_id_token(
        self, monkeypatch, patch_client
    ):
        from app.auth import google_oauth

        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "cid")
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "secret")

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"id_token": "the.id.token"}
        post = patch_client(google_oauth, resp)

        result = await google_oauth.exchange_code_for_id_token(
            code="auth-code",
            code_verifier="verifier-value",
            redirect_uri="https://example.com/api/organizer/auth/google/callback",
        )

        assert result == "the.id.token"
        post.assert_called_once()
        _, kwargs = post.call_args
        assert kwargs["data"]["code"] == "auth-code"
        assert kwargs["data"]["client_id"] == "cid"
        assert kwargs["data"]["client_secret"] == "secret"
        assert kwargs["data"]["code_verifier"] == "verifier-value"
        assert kwargs["data"]["grant_type"] == "authorization_code"

    @pytest.mark.asyncio
    async def test_response_missing_id_token_raises_not_key_error(
        self, monkeypatch, patch_client
    ):
        """A 200 response with no id_token field (malformed/unexpected body)
        must raise a typed, catchable error — never an uncaught KeyError
        that would surface the callback as a 500."""
        from app.auth import google_oauth

        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "cid")
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "secret")

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"unexpected": "shape"}
        patch_client(google_oauth, resp)

        with pytest.raises(google_oauth.GoogleTokenExchangeError):
            await google_oauth.exchange_code_for_id_token(
                code="auth-code",
                code_verifier="verifier-value",
                redirect_uri="https://example.com/api/organizer/auth/google/callback",
            )

    @pytest.mark.asyncio
    async def test_non_json_response_raises_not_value_error(self, monkeypatch, patch_client):
        from app.auth import google_oauth

        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "cid")
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "secret")

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.side_effect = ValueError("not json")
        patch_client(google_oauth, resp)

        with pytest.raises(google_oauth.GoogleTokenExchangeError):
            await google_oauth.exchange_code_for_id_token(
                code="auth-code",
                code_verifier="verifier-value",
                redirect_uri="https://example.com/api/organizer/auth/google/callback",
            )
