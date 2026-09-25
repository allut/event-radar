"""Piletilevi promoter resolution (#412/#427): resolves a Piletilevi event
page's schema.org ``organizer`` reference to a promoter profile page
(``/en/promoters/{id}/{slug}``), then extracts that promoter's public contact
email domain as the domain-control target for
``app.claims.dns_txt.verify_dns_txt_token``, and (#427) the promoter's own
identity (profile URL + name) as the ``Publisher`` a Piletilevi claim resolves
against — see CONTEXT.md's Event Claiming glossary and models.py's
``Publisher`` docstring (the promoter profile URL is the ``external_id`` key
a Piletilevi Publisher resolves against).

Piletilevi's JSON-LD wraps ``organizer`` as an ``@id`` reference into the same
document's ``@graph`` rather than inlining it (unlike Fienta/KUMU/ECH, which
``app/ingestion/jsonld.py::organizer_from_jsonld_items`` already handles) — a
listing with no specific promoter set resolves that reference back to
Piletilevi's own site identity node, which carries no ``/promoters/`` url and
is treated as non-resolving (falls back to a Series claim target — see
CONTEXT.md's Event Claiming glossary — this is the *only* case that does).
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.constants import FREE_EMAIL_PROVIDER_DOMAINS, HTML_PARSER
from app.ingestion.http_client import http_get
from app.ingestion.jsonld import parse_jsonld_graph_items
from app.ingestion.selectors import PILETILEVI_HOST, PILETILEVI_PROMOTER_CONTACT_SELECTOR

_PROMOTER_URL_MARKER = "/promoters/"
_MAILTO_PREFIX = "mailto:"


@dataclass(frozen=True)
class PromoterIdentity:
    """A resolved promoter — ``external_id`` (the promoter's absolute profile
    URL) is the key a Piletilevi ``Publisher`` resolves against; ``name`` is
    the promoter's schema.org display name, when the organizer node carries
    one."""

    external_id: str
    name: str | None


def _is_piletilevi_host(url: str) -> bool:
    hostname = urlsplit(url).hostname
    return hostname is not None and (
        hostname == PILETILEVI_HOST or hostname.endswith(f".{PILETILEVI_HOST}")
    )


def _resolve_organizer_node(
    html: str, event_page_url: str
) -> tuple[str, dict[str, Any]] | None:
    """(resolved absolute promoter URL, its @graph node) or None when the
    organizer reference is absent, resolves back to Piletilevi's own site
    identity (no specific promoter), or — page content being untrusted
    input — resolves off Piletilevi's own host (SSRF guard; callers that
    fetch this URL server-side rely on this check)."""
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
    return resolved, organizer_node


def resolve_promoter_url(html: str, event_page_url: str) -> str | None:
    """The event page's organizer ``@id`` resolved against its own ``@graph``
    to an absolute promoter profile URL, or None when it doesn't resolve
    (`_resolve_organizer_node`'s docstring covers the non-resolving cases;
    `resolve_promoter_domain` fetches this URL server-side)."""
    resolved = _resolve_organizer_node(html, event_page_url)
    return resolved[0] if resolved is not None else None


def resolve_promoter_identity(html: str, event_page_url: str) -> PromoterIdentity | None:
    """(#427) The event page's promoter as a claim-target identity — the
    profile URL plus its schema.org ``name``, or None when the promoter
    reference doesn't resolve (see `_resolve_organizer_node`)."""
    resolved = _resolve_organizer_node(html, event_page_url)
    if resolved is None:
        return None
    url, organizer_node = resolved
    name_raw = organizer_node.get("name")
    name = name_raw.strip() if isinstance(name_raw, str) and name_raw.strip() else None
    return PromoterIdentity(external_id=url, name=name)


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
