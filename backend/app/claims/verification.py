"""Claim-proof verification engine (#412, two-tier Piletilevi path added by
#428): decides, per source, whether a claim auto-grants or falls back to
admin review. Standalone service with its own test coverage — not yet wired
into a claim lifecycle (#413 selects the right function below by the claim's
Publisher.source.slug / Claim.kind and persists the outcome).

Google Workspace ``hd`` domain claims and Estonian Business Register/Smart-ID
auto-verification are deliberately not implemented here — ruled out per the
#409 spec.
"""

from dataclasses import dataclass

import httpx

from app.claims.dns_txt import verify_dns_txt_token
from app.claims.fienta_token import verify_fienta_token
from app.claims.piletilevi_promoter import resolve_promoter_contact
from app.constants import (
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
    CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
    CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
    CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
    CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
    ESTONIA_CONCERT_HALL_VERIFICATION_DOMAIN,
    KUMU_VERIFICATION_DOMAIN,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_KUMU,
)

# KUMU and Estonia Concert Hall are each a single institution with one
# hardcoded verification domain — see CONTEXT.md's Publisher glossary entry.
INSTITUTIONAL_VERIFICATION_DOMAINS: dict[str, str] = {
    SOURCE_SLUG_KUMU: KUMU_VERIFICATION_DOMAIN,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL: ESTONIA_CONCERT_HALL_VERIFICATION_DOMAIN,
}


@dataclass(frozen=True)
class VerificationResult:
    mechanism: str
    outcome: str
    # DNS-TXT domain the check ran against (#415's pending screen) — None for
    # fienta_token/admin_review, which have no domain to show.
    domain: str | None = None
    # (#428) The resolved Piletilevi promoter contact mailbox the claimant's
    # account email was compared against — set only for the
    # piletilevi_mailbox mechanism (both on match and mismatch, so the admin
    # queue can show the evidence either way), None otherwise.
    contact: str | None = None


def _outcome_for(verified: bool) -> str:
    return (
        CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT
        if verified
        else CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW
    )


async def verify_fienta_publisher_claim(
    client: httpx.AsyncClient,
    base_url: str,
    organizer_external_id: str,
    event_external_id: str,
    token: str,
) -> VerificationResult:
    verified = await verify_fienta_token(
        client, base_url, organizer_external_id, event_external_id, token
    )
    return VerificationResult(CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN, _outcome_for(verified))


async def verify_institutional_publisher_claim(
    client: httpx.AsyncClient, source_slug: str, token: str
) -> VerificationResult:
    """KUMU/Estonia Concert Hall: DNS-TXT against the hardcoded institutional domain."""
    domain = INSTITUTIONAL_VERIFICATION_DOMAINS[source_slug]
    verified = await verify_dns_txt_token(client, domain, token)
    return VerificationResult(
        CLAIM_VERIFICATION_MECHANISM_DNS_TXT, _outcome_for(verified), domain=domain
    )


async def verify_piletilevi_claim(
    client: httpx.AsyncClient,
    event_page_html: str,
    event_page_url: str,
    token: str,
    claimant_email: str,
) -> VerificationResult:
    """(#428) Two-tier Piletilevi Publisher auto-grant, in priority order:

    1. A resolved promoter with a DNS-provable contact domain (not a free/
       shared provider) — DNS-TXT against that domain, same mechanism KUMU/
       ECH use.
    2. A resolved promoter with only a plain contact mailbox — auto-grants
       only on an exact (case-insensitive) match against `claimant_email`;
       any other outcome (mismatch, or no contact info at all) falls to
       admin review with both emails preserved as evidence.

    A promoter that doesn't resolve at all falls straight to admin review
    with no evidence — same bucket as every other Piletilevi fallback case
    (see `series_claim_result`)."""
    contact = await resolve_promoter_contact(client, event_page_html, event_page_url)
    if contact is None:
        return VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
            CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
        )
    if contact.domain is not None:
        verified = await verify_dns_txt_token(client, contact.domain, token)
        return VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
            _outcome_for(verified),
            domain=contact.domain,
        )
    matched = contact.email is not None and contact.email == claimant_email.strip().lower()
    return VerificationResult(
        CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
        _outcome_for(matched),
        contact=contact.email,
    )


def series_claim_result() -> VerificationResult:
    """Series claims (Piletilevi listings whose promoter never resolved) carry
    no verifiable identity — always admin review. There is no auto-grant
    fast-track for them (#428 removed the Trusted-claimant mechanism that
    used to provide one)."""
    return VerificationResult(
        CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
        CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
    )
