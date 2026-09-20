"""DNS-TXT domain-control check via DNS-over-HTTPS (#412) — proves an
organizer controls a source's own domain: KUMU/Estonia Concert Hall's
hardcoded institutional host, or a Piletilevi promoter's resolved contact
domain (app/claims/piletilevi_promoter.py). Queries a fixed, hardcoded DoH
resolver — never a source-supplied URL — so this adds no new fetchable-
content SSRF surface; the ALLOWED_SOURCE_HOSTS allowlist doesn't apply here.
"""

import httpx

from app.constants import CLAIM_DNS_DOH_URL, CLAIM_DNS_TXT_RECORD_LABEL, DNS_RECORD_TYPE_TXT
from app.ingestion.http_client import http_get

_DOH_ACCEPT_HEADER = {"Accept": "application/dns-json"}


async def verify_dns_txt_token(client: httpx.AsyncClient, domain: str, token: str) -> bool:
    """True when `token` appears in any TXT record at
    ``{CLAIM_DNS_TXT_RECORD_LABEL}.{domain}``, resolved via DoH JSON."""
    response = await http_get(
        client,
        CLAIM_DNS_DOH_URL,
        params={
            "name": f"{CLAIM_DNS_TXT_RECORD_LABEL}.{domain}",
            "type": DNS_RECORD_TYPE_TXT,
        },
        headers=_DOH_ACCEPT_HEADER,
    )
    data = response.json()
    answers = data.get("Answer") or []
    return any(token in str(answer.get("data", "")) for answer in answers)
