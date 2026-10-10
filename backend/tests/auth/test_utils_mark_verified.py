"""mark_organizer_verified stamps once and reports whether to commit."""

from types import SimpleNamespace

from app.auth.utils import mark_organizer_verified


def test_stamps_first_time_only():
    org = SimpleNamespace(email_verified_at=None)
    assert mark_organizer_verified(org) is True
    stamped = org.email_verified_at
    assert stamped is not None and stamped.tzinfo is not None
    assert mark_organizer_verified(org) is False
    assert org.email_verified_at == stamped
