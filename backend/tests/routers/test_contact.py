"""Tests for POST /contact (app/routers/contact.py)."""
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.constants import CONTACT_MESSAGE_MAX_LEN, CONTACT_NAME_MAX_LEN
from app.routers.contact import ContactBody, submit_contact


class TestSubmitContact:
    @pytest.mark.asyncio
    async def test_valid_submit_sends_message(self, make_request, monkeypatch):
        mock_send = AsyncMock()
        monkeypatch.setattr("app.routers.contact.send_contact_message", mock_send)

        body = ContactBody(name="Jane", email="jane@example.com", message="Hello there")
        result = await submit_contact(body, make_request(method="POST"))

        assert result["detail"] == "Message sent."
        mock_send.assert_awaited_once_with("Jane", "jane@example.com", "Hello there")

    @pytest.mark.asyncio
    async def test_honeypot_tripped_skips_send(self, make_request, monkeypatch):
        mock_send = AsyncMock()
        monkeypatch.setattr("app.routers.contact.send_contact_message", mock_send)

        body = ContactBody(
            name="Bot", email="bot@example.com", message="spam", website="http://spam.example"
        )
        result = await submit_contact(body, make_request(method="POST"))

        assert result["detail"] == "Message sent."
        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_failure_does_not_propagate(self, make_request, monkeypatch):
        mock_send = AsyncMock(side_effect=RuntimeError("resend down"))
        monkeypatch.setattr("app.routers.contact.send_contact_message", mock_send)

        body = ContactBody(name="Jane", email="jane@example.com", message="Hello there")
        result = await submit_contact(body, make_request(method="POST"))

        assert result["detail"] == "Message sent."
        mock_send.assert_awaited_once()

    def test_oversized_message_rejected(self):
        with pytest.raises(ValidationError):
            ContactBody(
                name="Jane",
                email="jane@example.com",
                message="x" * (CONTACT_MESSAGE_MAX_LEN + 1),
            )

    def test_oversized_name_rejected(self):
        with pytest.raises(ValidationError):
            ContactBody(
                name="x" * (CONTACT_NAME_MAX_LEN + 1),
                email="jane@example.com",
                message="hello",
            )

    def test_bad_email_rejected(self):
        with pytest.raises(ValidationError):
            ContactBody(name="Jane", email="not-an-email", message="hello")

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            ContactBody(name="Jane", email="jane@example.com", message="")
