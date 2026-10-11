"""Unit tests for app/claims/fienta_token.py (#412) — the Fienta token
round-trip: description/notes_about_time success/failure."""

import httpx
import pytest

from app.claims.fienta_token import generate_claim_token, verify_fienta_token
from app.constants.claims import CLAIM_TOKEN_PREFIX

_BASE_URL = "https://fienta.com/api/v1/public/events"


def test_generate_claim_token_has_prefix_and_is_unique():
    a = generate_claim_token()
    b = generate_claim_token()

    assert a.startswith(CLAIM_TOKEN_PREFIX)
    assert a != b


class TestVerifyFientaToken:
    @pytest.mark.asyncio
    async def test_token_found_in_description_survives_p_wrap(self):
        token = "er-verify-abc123"
        events = [
            {"id": "100", "description": f"<p>Intro</p><p>{token}</p>", "notes_about_time": ""}
        ]

        async def handler(request):
            return httpx.Response(200, json={"events": events})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify_fienta_token(client, _BASE_URL, "42", "100", token)

        assert result is True

    @pytest.mark.asyncio
    async def test_token_found_in_notes_about_time(self):
        token = "er-verify-xyz789"
        events = [{"id": "100", "description": "", "notes_about_time": token}]

        async def handler(request):
            return httpx.Response(200, json={"events": events})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify_fienta_token(client, _BASE_URL, "42", "100", token)

        assert result is True

    @pytest.mark.asyncio
    async def test_token_absent_returns_false(self):
        events = [{"id": "100", "description": "no token here", "notes_about_time": ""}]

        async def handler(request):
            return httpx.Response(200, json={"events": events})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify_fienta_token(
                client, _BASE_URL, "42", "100", "er-verify-missing"
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_event_id_not_in_listing_returns_false(self):
        events = [{"id": "999", "description": "er-verify-abc123", "notes_about_time": ""}]

        async def handler(request):
            return httpx.Response(200, json={"events": events})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify_fienta_token(
                client, _BASE_URL, "42", "100", "er-verify-abc123"
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_data_key_response_shape_is_also_supported(self):
        token = "er-verify-abc123"
        events = [{"id": "100", "description": token, "notes_about_time": ""}]

        async def handler(request):
            return httpx.Response(200, json={"data": events})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify_fienta_token(client, _BASE_URL, "42", "100", token)

        assert result is True
