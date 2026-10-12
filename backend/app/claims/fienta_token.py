"""Fienta claim-proof mechanism (#412): a system-generated token round-tripped
through the organizer's own listing (``description`` or ``notes_about_time``)
and read back via Fienta's unauthenticated public events API — the same
``?organizer=<id>`` endpoint ``app/ingestion/sources/fienta.py::fetch_organizer``
already polls, so this adds no new host/SSRF surface and sits behind no CDN.
"""

import secrets

import httpx

from app.constants.claims import CLAIM_TOKEN_BYTE_LENGTH, CLAIM_TOKEN_PREFIX
from app.ingestion.http_client import http_get


def generate_claim_token() -> str:
    """A random, URL-safe token an organizer pastes into their Fienta listing."""
    return f"{CLAIM_TOKEN_PREFIX}{secrets.token_hex(CLAIM_TOKEN_BYTE_LENGTH)}"


async def verify_fienta_token(
    client: httpx.AsyncClient,
    base_url: str,
    organizer_external_id: str,
    event_external_id: str,
    token: str,
) -> bool:
    """True when `token` appears in the matching event's ``description`` or
    ``notes_about_time``, read from a live re-fetch of the organizer's public
    listing. ``notes_about_time`` is plain text; ``description`` is organizer-
    authored HTML wrapped in ``<p>`` — a plain substring check tolerates that
    wrap without needing to parse it, so long as the token itself carries no
    characters an HTML serializer would escape (``generate_claim_token()``'s
    hex output never does).
    """
    response = await http_get(client, base_url, params={"organizer": organizer_external_id})
    data = response.json()
    events = data.get("events", data.get("data", []))
    for event in events:
        if str(event.get("id", "")) != str(event_external_id):
            continue
        description = event.get("description") or ""
        notes = event.get("notes_about_time") or ""
        return token in description or token in notes
    return False
