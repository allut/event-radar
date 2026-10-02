"""RFC 6238 TOTP verification for the admin console login (routers/admin_auth.py).

Secret enrollment is a separate one-time local script (scripts/admin_totp_enroll.py) —
this module only verifies a submitted 6-digit code against the configured secret.
"""

import hmac
import logging
import time

import pyotp

from app.constants import ADMIN_TOTP_VALID_WINDOW

log = logging.getLogger(__name__)

# Single-admin credential (no admins table — see auth/tokens.py's
# generate_admin_session_token), so one process-wide "last accepted step"
# is enough to close the replay window: without it, a code observed once
# (shoulder-surf, a leaked log line, a slow MITM) stays valid for the rest
# of its ±ADMIN_TOTP_VALID_WINDOW-step window and could mint a second,
# independent session. Tracking the timestep counter (not the code string)
# closes the window exactly, including for a still-valid *older* code once a
# *newer* one has been accepted — a code string check alone doesn't catch
# that case. In-memory only, like the admin auth lockout dict
# (routers/admin.py) — resets on deploy/restart, which just means one lost
# accepted-step memory, not a security regression.
_last_accepted_step: int | None = None


def check_totp_code(secret: str, code: str) -> int | None:
    """Return the matched timestep if `code` is a valid, not-yet-accepted
    current (±ADMIN_TOTP_VALID_WINDOW step) TOTP for `secret`, else None.

    Pure check — does not record anything. The caller must invoke
    record_totp_step() with the returned step only after deciding the overall
    login succeeded (see routers/admin_auth.py); recording as a side effect of
    verification would burn a valid code even on a failed-password attempt.

    Never raises — a malformed secret or code is just an invalid login attempt,
    not a server error.
    """
    if not secret or not code:
        return None
    try:
        totp = pyotp.TOTP(secret)
        current_step = int(time.time() / totp.interval)
        for offset in range(-ADMIN_TOTP_VALID_WINDOW, ADMIN_TOTP_VALID_WINDOW + 1):
            step = current_step + offset
            if _last_accepted_step is not None and step <= _last_accepted_step:
                continue  # already-accepted or older step — reject even if the code matches
            if hmac.compare_digest(totp.generate_otp(step), code):
                return step
    except Exception as exc:
        # Class name only — the message could echo the malformed secret. A bad
        # ADMIN_TOTP_SECRET would otherwise fail every admin login silently.
        log.warning("admin TOTP check raised %s", type(exc).__name__)
        return None
    return None


def record_totp_step(step: int) -> None:
    """Record `step` (from check_totp_code) as accepted, closing replay for
    it and every earlier step. Call only after the caller has confirmed the
    overall login succeeded (credentials_ok and totp_ok)."""
    global _last_accepted_step
    if _last_accepted_step is None or step > _last_accepted_step:
        _last_accepted_step = step
