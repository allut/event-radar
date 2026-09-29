"""Unit tests for the admin console TOTP verification functions
(app/auth/totp.py) — per issue #154's acceptance criteria, unit-tested
directly rather than only through the login endpoint."""

import pyotp
import pytest

import app.auth.totp as totp_module
from app.auth.totp import check_totp_code, record_totp_step


@pytest.fixture(autouse=True)
def _reset_replay_state():
    """_last_accepted_step is process-global — isolate each test."""
    totp_module._last_accepted_step = None
    yield
    totp_module._last_accepted_step = None


def _verify(secret: str, code: str) -> bool:
    """Mirror the caller's real usage: check, then record only on success."""
    step = check_totp_code(secret, code)
    if step is not None:
        record_totp_step(step)
    return step is not None


class TestCheckTotpCode:
    def test_current_code_is_valid(self):
        secret = pyotp.random_base32()
        code = pyotp.TOTP(secret).now()
        assert _verify(secret, code) is True

    def test_wrong_code_is_invalid(self):
        secret = pyotp.random_base32()
        wrong = pyotp.TOTP(pyotp.random_base32()).now()
        # Astronomically unlikely to collide with a random different secret's code.
        assert _verify(secret, wrong) is False

    def test_empty_secret_is_invalid(self):
        assert _verify("", "123456") is False

    def test_empty_code_is_invalid(self):
        secret = pyotp.random_base32()
        assert _verify(secret, "") is False

    def test_malformed_secret_does_not_raise(self):
        assert _verify("not-valid-base32!!!", "123456") is False

    def test_malformed_code_does_not_raise(self):
        secret = pyotp.random_base32()
        assert _verify(secret, "not-six-digits") is False

    def test_reusing_an_accepted_code_is_rejected(self):
        """Anti-replay: a code already accepted once must not verify again,
        even though it's still inside its own ADMIN_TOTP_VALID_WINDOW."""
        secret = pyotp.random_base32()
        code = pyotp.TOTP(secret).now()
        assert _verify(secret, code) is True
        assert _verify(secret, code) is False

    def test_checking_without_recording_does_not_burn_the_code(self):
        """A failed login (e.g. wrong password) must not consume the code —
        check_totp_code alone has no side effect."""
        secret = pyotp.random_base32()
        code = pyotp.TOTP(secret).now()
        assert check_totp_code(secret, code) is not None
        # Not recorded — still valid on the next check.
        assert check_totp_code(secret, code) is not None

    def test_older_still_in_window_code_is_rejected_after_a_newer_one_is_recorded(self):
        """A code from an earlier step, still inside ADMIN_TOTP_VALID_WINDOW,
        must be rejected once a later step has been accepted — closes the
        window exactly, not just for the exact code string reused."""
        import time

        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        step_now = int(time.time() / totp.interval)
        older_code = totp.generate_otp(step_now - 1)
        newer_code = totp.generate_otp(step_now)

        assert _verify(secret, newer_code) is True
        # older_code's step (step_now - 1) is now <= last accepted step.
        assert _verify(secret, older_code) is False


class TestMalformedSecretLogging:
    def test_malformed_secret_is_logged_not_swallowed_silently(self, caplog):
        """A bad ADMIN_TOTP_SECRET would otherwise fail every admin login with
        nothing in the logs. Only the exception class is logged — the message
        could echo the secret."""
        with caplog.at_level("WARNING", logger="app.auth.totp"):
            step = check_totp_code("not base32 !!!", "123456")

        assert step is None
        assert any("admin TOTP check raised" in r.getMessage() for r in caplog.records)
        assert all("not base32" not in r.getMessage() for r in caplog.records)
