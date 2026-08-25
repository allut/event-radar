"""Unit tests for the admin console TOTP verification function
(app/auth/totp.py) — per issue #154's acceptance criteria, unit-tested
directly rather than only through the login endpoint."""

import pyotp

from app.auth.totp import verify_totp_code


class TestVerifyTotpCode:
    def test_current_code_is_valid(self):
        secret = pyotp.random_base32()
        code = pyotp.TOTP(secret).now()
        assert verify_totp_code(secret, code) is True

    def test_wrong_code_is_invalid(self):
        secret = pyotp.random_base32()
        wrong = pyotp.TOTP(pyotp.random_base32()).now()
        # Astronomically unlikely to collide with a random different secret's code.
        assert verify_totp_code(secret, wrong) is False

    def test_empty_secret_is_invalid(self):
        assert verify_totp_code("", "123456") is False

    def test_empty_code_is_invalid(self):
        secret = pyotp.random_base32()
        assert verify_totp_code(secret, "") is False

    def test_malformed_secret_does_not_raise(self):
        assert verify_totp_code("not-valid-base32!!!", "123456") is False

    def test_malformed_code_does_not_raise(self):
        secret = pyotp.random_base32()
        assert verify_totp_code(secret, "not-six-digits") is False

    def test_reusing_an_accepted_code_is_rejected(self):
        """Anti-replay: a code already accepted once must not verify again,
        even though it's still inside its own ADMIN_TOTP_VALID_WINDOW."""
        secret = pyotp.random_base32()
        code = pyotp.TOTP(secret).now()
        assert verify_totp_code(secret, code) is True
        assert verify_totp_code(secret, code) is False
