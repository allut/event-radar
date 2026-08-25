"""Tests for the admin console session token (app/auth/tokens.py) —
generate_admin_session_token/verify_admin_session_token. No id/version claim
(no admins table — see the functions' own docstrings), unlike the consumer
and organizer session tokens, so coverage is narrower: just roundtrip,
tamper-rejection, and cross-track isolation."""

from itsdangerous import BadSignature

import pytest

from app.auth.tokens import (
    generate_admin_session_token,
    generate_organizer_session_token,
    generate_session_token,
    verify_admin_session_token,
)


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
