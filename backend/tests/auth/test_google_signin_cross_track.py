"""Cross-track test for Google sign-in: the same Google
`sub` signing in on both the consumer and organizer tracks must produce two
independent rows — a `UserIdentity` and an `OrganizerIdentity` — that never
merge and never collide, mirroring how email already works across the two
tracks. Each track's `_apply_google_linking_gate` (tests/auth/
test_google_signin_consumer.py, tests/auth/test_organizer_auth.py) is
otherwise tested in isolation; this file is the one place both run against
the identical Google identity payload."""
from unittest.mock import AsyncMock, MagicMock

import pytest

GOOGLE_IDENTITY = {
    "sub": "same-sub-both-tracks",
    "email": "person@gmail.com",
    "email_verified": True,
    "hd": None,
}


def _new_account_db():
    """A DB with no existing identity or account row for this Google
    identity, so the linking gate takes the new_account branch on either
    track."""
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[None, None])
    added = []

    def _add_side_effect(obj):
        added.append(obj)
        if hasattr(obj, "id"):
            obj.id = len(added)

    db.add = MagicMock(side_effect=_add_side_effect)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db, added


class TestCrossTrackIndependence:
    @pytest.mark.asyncio
    async def test_same_sub_creates_independent_rows_on_each_track(self):
        from app.models.organizers import OrganizerIdentity
        from app.models.users import UserIdentity
        from app.routers.auth import _apply_google_linking_gate as user_gate
        from app.routers.organizer_auth import (
            _apply_google_linking_gate as organizer_gate,
        )

        user_db, user_added = _new_account_db()
        organizer_db, organizer_added = _new_account_db()

        user_outcome, user = await user_gate(user_db, GOOGLE_IDENTITY)
        organizer_outcome, organizer = await organizer_gate(
            organizer_db, GOOGLE_IDENTITY
        )

        assert user_outcome == "new_account"
        assert organizer_outcome == "new_account"

        user_identity = next(o for o in user_added if isinstance(o, UserIdentity))
        organizer_identity = next(
            o for o in organizer_added if isinstance(o, OrganizerIdentity)
        )

        # Same provider identity (sub) on both tracks...
        assert user_identity.provider_sub == GOOGLE_IDENTITY["sub"]
        assert organizer_identity.provider_sub == GOOGLE_IDENTITY["sub"]

        # ...but distinct row types in distinct tables, tied to distinct
        # accounts, on entirely separate DB sessions — nothing links them.
        assert type(user_identity) is not type(organizer_identity)
        assert user is not organizer
        assert not hasattr(user_identity, "organizer_id")
        assert not hasattr(organizer_identity, "user_id")

        # Each track only ever queried/wrote its own table's session —
        # neither gate looked at the other track's DB at all.
        assert user_db.scalar.await_count == 2
        assert organizer_db.scalar.await_count == 2
