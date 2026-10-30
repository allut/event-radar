"""Tests for the admin console session token (app/auth/tokens.py) —
generate_admin_session_token/verify_admin_session_token. No id/version claim
(no admins table — see the functions' own docstrings), unlike the consumer
and organizer session tokens, so coverage is narrower: just roundtrip,
tamper-rejection, cross-track isolation, and the "e" (epoch) revocation
claim added for M-1 in the OWASP audit."""

import hashlib
from unittest.mock import patch

from itsdangerous import BadSignature

import pytest

from app.auth.tokens import (
    _serializer,
    generate_admin_session_token,
    generate_organizer_session_token,
    generate_session_token,
    verify_admin_session_token,
)
from app.config import settings
from app.constants.auth import ADMIN_SESSION_EPOCH_HASH_LEN, AUTH_ADMIN_SESSION_SALT


class TestAdminSessionToken:
    def test_roundtrip_does_not_raise(self):
        token = generate_admin_session_token()
        verify_admin_session_token(token)  # no return value; success = no raise

    def test_bad_signature_raises(self):
        token = generate_admin_session_token()
        with pytest.raises(BadSignature):
            verify_admin_session_token(token + "x")

    def test_user_session_token_rejected_as_admin_token(self):
        user_session = generate_session_token(1, 1)
        with pytest.raises(BadSignature):
            verify_admin_session_token(user_session)

    def test_organizer_session_token_rejected_as_admin_token(self):
        organizer_session = generate_organizer_session_token(1, 1)
        with pytest.raises(BadSignature):
            verify_admin_session_token(organizer_session)

    def test_bumping_session_epoch_invalidates_outstanding_session(self):
        """M-1 in the OWASP audit: rotating ADMIN_SESSION_EPOCH is the
        durable revocation this no-admins-table design supports — a session
        minted under the old epoch must stop verifying once it changes."""
        with patch("app.auth.tokens.settings.ADMIN_SESSION_EPOCH", "epoch-1"):
            token = generate_admin_session_token()
            verify_admin_session_token(token)  # still valid under the same epoch

        with patch("app.auth.tokens.settings.ADMIN_SESSION_EPOCH", "epoch-2"):
            with pytest.raises(BadSignature):
                verify_admin_session_token(token)

    def test_epoch_claim_is_keyed_not_a_bare_credential_hash(self):
        """The payload is readable by anyone holding the cookie, so "e" must
        not be a plain hash of the credentials (an offline password oracle),
        and a token minted with that old derivation must stop verifying."""
        bare = hashlib.sha256(
            f"{settings.ADMIN_SESSION_EPOCH}:{settings.ADMIN_PASSWORD}:{settings.ADMIN_TOTP_SECRET}".encode()
        ).hexdigest()[:ADMIN_SESSION_EPOCH_HASH_LEN]
        token = generate_admin_session_token()
        payload = _serializer().loads(token, salt=AUTH_ADMIN_SESSION_SALT)
        assert payload["e"] != bare

        legacy = _serializer().dumps({"admin": True, "e": bare}, salt=AUTH_ADMIN_SESSION_SALT)
        with pytest.raises(BadSignature):
            verify_admin_session_token(legacy)
