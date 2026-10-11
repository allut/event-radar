"""Unit tests for app/claims/dns_txt.py (#412) — DNS-TXT domain-control
check success/failure over DNS-over-HTTPS."""

import httpx
import pytest

from app.claims.dns_txt import verify_dns_txt_token
from app.constants.claims import CLAIM_DNS_DOH_URL, CLAIM_DNS_TXT_RECORD_LABEL


class TestVerifyDnsTxtToken:
    @pytest.mark.asyncio
    async def test_token_present_in_txt_answer_returns_true(self):
        token = "er-verify-abc123"

        async def handler(request):
            assert str(request.url).startswith(CLAIM_DNS_DOH_URL)
            assert request.url.params["name"] == f"{CLAIM_DNS_TXT_RECORD_LABEL}.kumu.ekm.ee"
            assert request.url.params["type"] == "TXT"
            return httpx.Response(
                200, json={"Answer": [{"type": 16, "data": f'"{token}"'}]}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify_dns_txt_token(client, "kumu.ekm.ee", token)

        assert result is True

    @pytest.mark.asyncio
    async def test_no_matching_txt_record_returns_false(self):
        async def handler(request):
            return httpx.Response(200, json={"Answer": [{"type": 16, "data": '"unrelated"'}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify_dns_txt_token(client, "concert.ee", "er-verify-abc123")

        assert result is False

    @pytest.mark.asyncio
    async def test_no_answer_section_returns_false(self):
        async def handler(request):
            return httpx.Response(200, json={"Status": 3})  # NXDOMAIN, no Answer key

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify_dns_txt_token(client, "concert.ee", "er-verify-abc123")

        assert result is False
