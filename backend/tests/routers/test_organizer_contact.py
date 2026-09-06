"""Tests for POST /organizer/contact (app/routers/organizer_contact.py)."""
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.constants import CONTACT_MESSAGE_MAX_LEN
from app.routers.organizer_contact import (
    OrganizerContactBody,
    submit_organizer_contact,
)


class TestSubmitOrganizerContact:
    @pytest.mark.asyncio
    async def test_valid_submit_sends_message_with_organizer_identity(
        self, make_request, make_organizer, monkeypatch
    ):
        mock_send = AsyncMock()
        monkeypatch.setattr("app.routers.organizer_contact.send_contact_message", mock_send)
        organizer = make_organizer(organizer_id=5, name="Tallinn Live")

        body = OrganizerContactBody(message="Hello there")
        result = await submit_organizer_contact(
            body, make_request(method="POST", path="/organizer/contact"), organizer
        )

        assert result["detail"] == "Message sent."
        mock_send.assert_awaited_once_with("Tallinn Live", organizer.email, "Hello there")

    @pytest.mark.asyncio
    async def test_falls_back_to_email_when_name_unset(
        self, make_request, make_organizer, monkeypatch
    ):
        mock_send = AsyncMock()
        monkeypatch.setattr("app.routers.organizer_contact.send_contact_message", mock_send)
        organizer = make_organizer(organizer_id=5)

        body = OrganizerContactBody(message="Hello there")
        await submit_organizer_contact(
            body, make_request(method="POST", path="/organizer/contact"), organizer
        )

        mock_send.assert_awaited_once_with(organizer.email, organizer.email, "Hello there")

    @pytest.mark.asyncio
    async def test_send_failure_does_not_propagate(
        self, make_request, make_organizer, monkeypatch
    ):
        mock_send = AsyncMock(side_effect=RuntimeError("resend down"))
        monkeypatch.setattr("app.routers.organizer_contact.send_contact_message", mock_send)
        organizer = make_organizer(organizer_id=5)

        body = OrganizerContactBody(message="Hello there")
        result = await submit_organizer_contact(
            body, make_request(method="POST", path="/organizer/contact"), organizer
        )

        assert result["detail"] == "Message sent."
        mock_send.assert_awaited_once()

    def test_oversized_message_rejected(self):
        with pytest.raises(ValidationError):
            OrganizerContactBody(message="x" * (CONTACT_MESSAGE_MAX_LEN + 1))

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            OrganizerContactBody(message="")
