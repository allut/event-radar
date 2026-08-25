"""RFC 6238 TOTP verification for the admin console login (routers/admin_auth.py).

Secret enrollment is a separate one-time local script (scripts/admin_totp_enroll.py) —
this module only verifies a submitted 6-digit code against the configured secret.
"""

import pyotp

from app.constants import ADMIN_TOTP_VALID_WINDOW

# Single-admin credential (no admins table — see auth/tokens.py's
# generate_admin_session_token), so one process-wide "last accepted code"
# is enough to close the replay window: without it, a code observed once
# (shoulder-surf, a leaked log line, a slow MITM) stays valid for the rest
# of its ±ADMIN_TOTP_VALID_WINDOW-step window and could mint a second,
# independent session. In-memory only, like the admin auth lockout dict
# (routers/admin.py) — resets on deploy/restart, which just means one lost
# accepted-code memory, not a security regression.
_last_accepted_code: str | None = None


def verify_totp_code(secret: str, code: str) -> bool:
    """True if `code` is a valid, not-yet-used current (±ADMIN_TOTP_VALID_WINDOW
    step) TOTP for `secret`. Rejects an exact code reuse even within its still-
    valid window (see _last_accepted_code above).

    Never raises — a malformed secret or code is just an invalid login attempt,
    not a server error.
    """
    global _last_accepted_code
    if not secret or not code:
        return False
    if code == _last_accepted_code:
        return False
    try:
        valid = pyotp.TOTP(secret).verify(code, valid_window=ADMIN_TOTP_VALID_WINDOW)
    except Exception:
        return False
    if valid:
        _last_accepted_code = code
    return valid
