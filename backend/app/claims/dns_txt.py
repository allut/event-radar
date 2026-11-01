"""DNS-TXT domain-control check via DNS-over-HTTPS (#412) — proves an
organizer controls a source's own domain: KUMU/Estonia Concert Hall's
hardcoded institutional host, or a Piletilevi promoter's resolved contact
domain (app/claims/piletilevi_promoter.py). Queries a fixed, hardcoded DoH
resolver — never a source-supplied URL — so this adds no new fetchable-
content SSRF surface; the ALLOWED_SOURCE_HOSTS allowlist doesn't apply here.
"""

import httpx

from app.constants.claims import (
    CLAIM_DNS_DOH_ACCEPT_HEADER,
    CLAIM_DNS_DOH_URL,
    CLAIM_DNS_TXT_RECORD_LABEL,
    CLAIM_DNS_VERIFICATION_MECHANISMS,
    DNS_RECORD_TYPE_TXT,
)
from app.ingestion.http_client import http_get


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
        headers=CLAIM_DNS_DOH_ACCEPT_HEADER,
    )
    data = response.json()
    answers = data.get("Answer") or []
    return any(token in str(answer.get("data", "")) for answer in answers)


def claim_dns_record_name(mechanism: str | None, domain: str | None) -> str | None:
    """The TXT record name a DNS-TXT/Piletilevi-promoter claim's organizer is
    told to add (#412/#413) — shared by the organizer-facing pending screen
    (organizer_claims.py) and the admin claims queue (admin_claims.py, #420) so
    the two never disagree on the record name shown for the same claim."""
    if mechanism in CLAIM_DNS_VERIFICATION_MECHANISMS and domain:
        return f"{CLAIM_DNS_TXT_RECORD_LABEL}.{domain}"
    return None
