"""Unit tests for app/claims/piletilevi_promoter.py (#412, #428) — resolving
a Piletilevi event's organizer @graph reference to a promoter page, and
extracting that promoter's controllable contact domain / raw mailbox.
Fixture shapes are grounded in the real JSON-LD Piletilevi serves (verified
live 2026-09-20)."""

import json

import httpx
import pytest

from app.claims.piletilevi_promoter import (
    extract_contact_domain,
    extract_contact_email,
    resolve_promoter_contact,
    resolve_promoter_url,
)

_EVENT_URL = "https://www.piletilevi.ee/en/tickets/VG7HG4DQLY/some-event"


def _event_page_with_promoter(promoter_url="/en/promoters/21-69-5910/nikulin-circus-ou"):
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@id": f"{_EVENT_URL}#event",
                "@type": "Event",
                "name": "Some Event",
                "organizer": {"@id": "https://www.piletilevi.ee/#/schema/organization/1"},
            },
            {
                "@id": "https://www.piletilevi.ee/#/schema/organization/1",
                "@type": "Organization",
                "name": "Nikulin Circus OÜ",
                "url": promoter_url,
            },
        ],
    }
    return (
        "<html><body>"
        f'<script type="application/ld+json">{json.dumps(graph)}</script>'
        "</body></html>"
    )


def _event_page_no_specific_promoter():
    """Organizer resolves back to Piletilevi's own site identity — the
    Yoast-generated default when no promoter is set."""
    graph = {
        "@graph": [
            {
                "@id": f"{_EVENT_URL}#event",
                "@type": "Event",
                "name": "Some Event",
                "organizer": {"@id": "https://www.piletilevi.ee/#identity"},
            },
            {
                "@id": "https://www.piletilevi.ee/#identity",
                "@type": ["Organization", "LocalBusiness"],
                "name": "Piletilevi",
                "url": "https://www.piletilevi.ee",
            },
        ]
    }
    return (
        "<html><body>"
        f'<script type="application/ld+json">{json.dumps(graph)}</script>'
        "</body></html>"
    )


def _promoter_page(mailto="mailto:nikulincircus@own-domain.ee"):
    return (
        "<html><body>"
        '<h3>Contacts and additional details</h3>'
        '<div><span>Nikulin Circus OÜ</span>'
        f'<a href="{mailto}">contact</a></div>'
        "</body></html>"
    )


class TestResolvePromoterUrl:
    def test_resolves_organizer_ref_to_absolute_promoter_url(self):
        html = _event_page_with_promoter()

        result = resolve_promoter_url(html, _EVENT_URL)

        assert result == "https://www.piletilevi.ee/en/promoters/21-69-5910/nikulin-circus-ou"

    def test_organizer_resolving_to_site_identity_returns_none(self):
        html = _event_page_no_specific_promoter()

        assert resolve_promoter_url(html, _EVENT_URL) is None

    def test_no_organizer_field_returns_none(self):
        html = "<html><body>no jsonld here</body></html>"

        assert resolve_promoter_url(html, _EVENT_URL) is None

    def test_off_host_promoter_url_is_rejected(self):
        """SSRF guard: an organizer node's `url` is untrusted page content —
        an absolute off-host URL must never be handed to http_get()."""
        html = _event_page_with_promoter(
            promoter_url="https://attacker.example/x/promoters/1"
        )

        assert resolve_promoter_url(html, _EVENT_URL) is None


class TestExtractContactEmail:
    def test_extracts_raw_mailto_address(self):
        html = _promoter_page("mailto:Nikulincircus@Own-Domain.ee")

        assert extract_contact_email(html) == "nikulincircus@own-domain.ee"

    def test_free_email_provider_address_is_not_excluded(self):
        """Unlike extract_contact_domain, the raw mailbox is kept even on a
        free/shared provider (#428) — the mailbox-match path checks exact
        account-email identity, not DNS control."""
        html = _promoter_page("mailto:nikulincircus@gmail.com")

        assert extract_contact_email(html) == "nikulincircus@gmail.com"

    def test_no_mailto_link_returns_none(self):
        html = "<html><body><p>no contact link</p></body></html>"

        assert extract_contact_email(html) is None


class TestExtractContactDomain:
    def test_extracts_domain_from_mailto(self):
        html = _promoter_page("mailto:nikulincircus@own-domain.ee")

        assert extract_contact_domain(html) == "own-domain.ee"

    def test_free_email_provider_domain_is_excluded(self):
        html = _promoter_page("mailto:nikulincircus@mail.ee")

        assert extract_contact_domain(html) is None

    def test_no_mailto_link_returns_none(self):
        html = "<html><body><p>no contact link</p></body></html>"

        assert extract_contact_domain(html) is None


class TestResolvePromoterContact:
    @pytest.mark.asyncio
    async def test_resolving_promoter_returns_controllable_domain(self):
        async def handler(request):
            return httpx.Response(200, text=_promoter_page("mailto:info@own-domain.ee"))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await resolve_promoter_contact(
                client, _event_page_with_promoter(), _EVENT_URL
            )

        assert result.domain == "own-domain.ee"
        assert result.email == "info@own-domain.ee"

    @pytest.mark.asyncio
    async def test_non_resolving_promoter_never_fetches_promoter_page(self):
        called = False

        async def handler(request):
            nonlocal called
            called = True
            return httpx.Response(200, text="")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await resolve_promoter_contact(
                client, _event_page_no_specific_promoter(), _EVENT_URL
            )

        assert result is None
        assert called is False

    @pytest.mark.asyncio
    async def test_promoter_page_with_only_free_email_has_no_domain_but_has_email(self):
        """(#428) A free-provider mailbox carries no DNS-provable domain, but
        the raw address survives as mailbox-match evidence."""
        async def handler(request):
            return httpx.Response(200, text=_promoter_page("mailto:info@gmail.com"))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await resolve_promoter_contact(
                client, _event_page_with_promoter(), _EVENT_URL
            )

        assert result.domain is None
        assert result.email == "info@gmail.com"

    @pytest.mark.asyncio
    async def test_promoter_page_with_no_contact_link_returns_empty_contact(self):
        async def handler(request):
            return httpx.Response(200, text="<html><body>no contact</body></html>")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await resolve_promoter_contact(
                client, _event_page_with_promoter(), _EVENT_URL
            )

        assert result.domain is None
        assert result.email is None
