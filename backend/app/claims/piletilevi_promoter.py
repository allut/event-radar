"""Piletilevi promoter resolution (#412/#427/#428): resolves a Piletilevi
event page's schema.org ``organizer`` reference to a promoter profile page
(``/en/promoters/{id}/{slug}``), then extracts that promoter's public contact
details as the two-tier auto-grant evidence ``verify_piletilevi_claim``
(#428) evaluates: a non-free-provider mailto domain as the domain-control
target for ``app.claims.dns_txt.verify_dns_txt_token``, or (no such domain)
the raw mailto address for an exact-match check against the claiming
organizer's own account email. Also resolves (#427) the promoter's own
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

from app.constants.claims import (
    FREE_EMAIL_PROVIDER_DOMAINS,
    PILETILEVI_PROMOTER_URL_MARKER,
)
from app.constants.core import HTML_PARSER, MAILTO_PREFIX
from app.constants.ingestion import JSONLD_ID_KEY, JSONLD_TYPE_KEY
from app.ingestion.http_client import host_matches_domain, http_get_stored_url
from app.ingestion.jsonld import parse_jsonld_graph_items
from app.ingestion.selectors import (
    JSONLD_EVENT_TYPE,
    PILETILEVI_HOST,
    PILETILEVI_PROMOTER_CONTACT_SELECTOR,
)
from app.auth.utils import normalize_email


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
    return hostname is not None and host_matches_domain(hostname, PILETILEVI_HOST)


def _resolve_organizer_node(
    html: str, event_page_url: str
) -> tuple[str, dict[str, Any]] | None:
    """(resolved absolute promoter URL, its @graph node) or None when the
    organizer reference is absent, resolves back to Piletilevi's own site
    identity (no specific promoter), or — page content being untrusted
    input — resolves off Piletilevi's own host (SSRF guard; callers that
    fetch this URL server-side rely on this check)."""
    items = parse_jsonld_graph_items(BeautifulSoup(html, HTML_PARSER))
    by_id = {item[JSONLD_ID_KEY]: item for item in items if JSONLD_ID_KEY in item}

    organizer_ref: str | None = None
    for item in items:
        if item.get(JSONLD_TYPE_KEY) == JSONLD_EVENT_TYPE and isinstance(item.get("organizer"), dict):
            organizer_ref = item["organizer"].get(JSONLD_ID_KEY)
            break
    if not organizer_ref:
        return None

    organizer_node = by_id.get(organizer_ref)
    if not organizer_node:
        return None
    url = organizer_node.get("url")
    if not url or PILETILEVI_PROMOTER_URL_MARKER not in str(url):
        return None
    resolved = urljoin(event_page_url, str(url))
    if not _is_piletilevi_host(resolved):
        return None
    return resolved, organizer_node


def resolve_promoter_url(html: str, event_page_url: str) -> str | None:
    """The event page's organizer ``@id`` resolved against its own ``@graph``
    to an absolute promoter profile URL, or None when it doesn't resolve
    (`_resolve_organizer_node`'s docstring covers the non-resolving cases;
    `resolve_promoter_contact` fetches this URL server-side)."""
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


def extract_contact_email(promoter_html: str) -> str | None:
    """The promoter page's contact-details mailto address, lowercased, or
    None when there is no mailto link — every domain included (unlike
    `extract_contact_domain`, which drops a free/shared-provider domain since
    that path proves DNS control, not account-email identity)."""
    soup = BeautifulSoup(promoter_html, HTML_PARSER)
    link = soup.select_one(PILETILEVI_PROMOTER_CONTACT_SELECTOR)
    if not link:
        return None
    href = str(link.get("href", ""))
    if not href.startswith(MAILTO_PREFIX):
        return None
    email = normalize_email(href[len(MAILTO_PREFIX) :].split("?", 1)[0])
    if "@" not in email:
        return None
    return email


def _domain_if_provable(email: str) -> str | None:
    """`email`'s domain, or None when it's a free/shared provider the
    promoter can't prove DNS control of — the shared tail of
    `extract_contact_domain` and `resolve_promoter_contact`, split out so the
    latter can derive it from an email it already extracted instead of
    re-parsing the promoter page a second time."""
    domain = email.rsplit("@", 1)[1]
    return domain if domain and domain not in FREE_EMAIL_PROVIDER_DOMAINS else None


def extract_contact_domain(promoter_html: str) -> str | None:
    """The promoter page's contact-details mailto domain, or None when there
    is no mailto link or its domain is a free/shared provider the promoter
    can't prove DNS control of."""
    email = extract_contact_email(promoter_html)
    return _domain_if_provable(email) if email is not None else None


@dataclass(frozen=True)
class PromoterContact:
    """(#428) A resolved promoter's contact evidence — `domain` is set only
    for a DNS-provable (non-free-provider) mailto domain; `email` is the raw
    mailto address regardless, for the exact-account-email-match auto-grant
    path. Both None when the promoter page carries no mailto contact link at
    all."""

    domain: str | None
    email: str | None


async def resolve_promoter_contact(
    client: httpx.AsyncClient, event_page_html: str, event_page_url: str
) -> PromoterContact | None:
    """End-to-end: event page -> promoter page -> its contact evidence
    (`PromoterContact`), fetching the promoter page once — `verify_piletilevi_claim`
    (#428) needs both the domain and the raw mailbox off the one page, not two
    separate fetches. None when the promoter reference doesn't resolve at
    all."""
    promoter_url = resolve_promoter_url(event_page_html, event_page_url)
    if promoter_url is None:
        return None
    try:
        # Full SSRF guard (https/443, allowlisted host, public IP) — the
        # promoter URL is page-derived, so hostname equality alone is not
        # enough on a request path (OWASP audit L-3).
        response = await http_get_stored_url(client, promoter_url)
    except ValueError:
        return None
    email = extract_contact_email(response.text)
    domain = _domain_if_provable(email) if email is not None else None
    return PromoterContact(domain=domain, email=email)
