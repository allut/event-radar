"""Unit tests for app.routers.utils.auth."""

from unittest.mock import AsyncMock

import pytest

from app.routers.utils.auth import recent_unused_link_exists


class TestRecentUnusedLinkExists:
    @pytest.mark.asyncio
    async def test_extra_predicate_is_applied_to_the_query(self, mock_db):
        """Google sign-in's confirmation-link cooldown (organizer_auth.py)
        must only match a pending link for the *same* sub — not any unused
        link for the organizer — or it can silently suppress the
        confirmation email while reporting it as sent."""
        from app.models.organizers import OrganizerMagicLink

        mock_db.scalar = AsyncMock(return_value=None)

        await recent_unused_link_exists(
            mock_db,
            OrganizerMagicLink,
            OrganizerMagicLink.organizer_id,
            5,
            900,
            extra_predicate=OrganizerMagicLink.pending_google_sub == "sub-123",
        )

        stmt = mock_db.scalar.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "pending_google_sub" in compiled
        assert "sub-123" in compiled

    @pytest.mark.asyncio
    async def test_no_extra_predicate_omits_it_from_the_query(self, mock_db):
        """Existing callers (plain magic-link resend cooldown) must keep
        matching on the fk alone — the new parameter is additive."""
        from app.models.organizers import OrganizerMagicLink

        mock_db.scalar = AsyncMock(return_value=None)

        await recent_unused_link_exists(
            mock_db, OrganizerMagicLink, OrganizerMagicLink.organizer_id, 5, 900
        )

        stmt = mock_db.scalar.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        where_clause = compiled.split("WHERE", 1)[1]
        assert "pending_google_sub" not in where_clause
