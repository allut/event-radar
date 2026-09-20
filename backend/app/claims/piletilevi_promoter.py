"""Piletilevi promoter resolution (#412): resolves a Piletilevi event page's
schema.org ``organizer`` reference to a promoter profile page
(``/en/promoters/{id}/{slug}``), then extracts that promoter's public contact
email domain as the domain-control target for
``app.claims.dns_txt.verify_dns_txt_token``.

Piletilevi's JSON-LD wraps ``organizer`` as an ``@id`` reference into the same
document's ``@graph`` rather than inlining it (unlike Fienta/KUMU/ECH, which
``app/ingestion/jsonld.py::organizer_from_jsonld_items`` already handles) — a
listing with no specific promoter set resolves that reference back to
Piletilevi's own site identity node, which carries no ``/promoters/`` url and
is treated as non-resolving (falls back to admin review, same as an
unresolved promoter or a Series claim — see CONTEXT.md's Event Claiming
glossary).
"""

from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.constants import FREE_EMAIL_PROVIDER_DOMAINS, HTML_PARSER
from app.ingestion.http_client import http_get
from app.ingestion.jsonld import parse_jsonld_graph_items
from app.ingestion.selectors import PILETILEVI_HOST, PILETILEVI_PROMOTER_CONTACT_SELECTOR

_PROMOTER_URL_MARKER = "/promoters/"
_MAILTO_PREFIX = "mailto:"


def _is_piletilevi_host(url: str) -> bool:
    hostname = urlsplit(url).hostname
    return hostname is not None and (
        hostname == PILETILEVI_HOST or hostname.endswith(f".{PILETILEVI_HOST}")
    )


def resolve_promoter_url(html: str, event_page_url: str) -> str | None:
    """The event page's organizer ``@id`` resolved against its own ``@graph``
    to an absolute promoter profile URL, or None when it isn't present,
    resolves back to Piletilevi's own site identity (no specific promoter),
    or — page content being untrusted input — resolves off Piletilevi's own
    host (SSRF guard; `resolve_promoter_domain` fetches this URL server-side)."""
    items = parse_jsonld_graph_items(BeautifulSoup(html, HTML_PARSER))
    by_id = {item["@id"]: item for item in items if "@id" in item}

    organizer_ref: str | None = None
    for item in items:
        if item.get("@type") == "Event" and isinstance(item.get("organizer"), dict):
            organizer_ref = item["organizer"].get("@id")
            break
    if not organizer_ref:
        return None

    organizer_node = by_id.get(organizer_ref)
    if not organizer_node:
        return None
    url = organizer_node.get("url")
    if not url or _PROMOTER_URL_MARKER not in str(url):
        return None
    resolved = urljoin(event_page_url, str(url))
    if not _is_piletilevi_host(resolved):
        return None
    return resolved


def extract_contact_domain(promoter_html: str) -> str | None:
    """The promoter page's contact-details mailto domain, or None when there
    is no mailto link or its domain is a free/shared provider the promoter
    can't prove DNS control of."""
    soup = BeautifulSoup(promoter_html, HTML_PARSER)
    link = soup.select_one(PILETILEVI_PROMOTER_CONTACT_SELECTOR)
    if not link:
        return None
    href = str(link.get("href", ""))
    if not href.startswith(_MAILTO_PREFIX):
        return None
    email = href[len(_MAILTO_PREFIX) :].split("?", 1)[0]
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    if not domain or domain in FREE_EMAIL_PROVIDER_DOMAINS:
        return None
    return domain


async def resolve_promoter_domain(
    client: httpx.AsyncClient, event_page_html: str, event_page_url: str
) -> str | None:
    """End-to-end: event page -> promoter page -> controllable contact domain,
    or None at any non-resolving step (falls back to admin review)."""
    promoter_url = resolve_promoter_url(event_page_html, event_page_url)
    if promoter_url is None:
        return None
    response = await http_get(client, promoter_url)
    return extract_contact_domain(response.text)
