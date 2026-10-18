"""set_digest_subscription — the single write path for the digest opt-in."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.email.subscription import set_digest_subscription


def test_turns_digest_subscription_off_and_on() -> None:
    user = SimpleNamespace(email_digest_opt_in=True, email_ad_consent=False)
    set_digest_subscription(user, False, MagicMock())  # type: ignore[arg-type]
    assert user.email_digest_opt_in is False
    set_digest_subscription(user, True, MagicMock())  # type: ignore[arg-type]
    assert user.email_digest_opt_in is True
