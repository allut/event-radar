"""Daily Five digest subscription — the one place the opt-in is written."""

from app.models.models import User


def set_digest_subscription(user: User, enabled: bool) -> None:
    """Turn the user's Daily Five digest on or off (caller commits)."""
    user.email_digest_opt_in = enabled
