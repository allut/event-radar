"""Claim-proof verification engine (#412): decides, per source, whether a
claim auto-grants or falls back to admin review. Standalone service with its
own test coverage — not yet wired into a claim lifecycle (#413 selects the
right function below by the claim's Publisher.source.slug / Claim.kind and
persists the outcome).

Google Workspace ``hd`` domain claims and Estonian Business Register/Smart-ID
auto-verification are deliberately not implemented here — ruled out per the
#409 spec.
"""

from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.dns_txt import verify_dns_txt_token
from app.claims.fienta_token import verify_fienta_token
from app.claims.piletilevi_promoter import resolve_promoter_domain
from app.constants import (
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
    CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
    CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
    CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
    ESTONIA_CONCERT_HALL_VERIFICATION_DOMAIN,
    KUMU_VERIFICATION_DOMAIN,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
)
from app.models.models import Claim, Publisher, Source

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
    return VerificationResult(CLAIM_VERIFICATION_MECHANISM_DNS_TXT, _outcome_for(verified))


async def verify_piletilevi_claim(
    client: httpx.AsyncClient,
    event_page_html: str,
    event_page_url: str,
    token: str,
) -> VerificationResult:
    """Resolving promoter: DNS-TXT against their contact domain. Non-resolving
    promoter falls straight to admin review — same bucket as every other
    Piletilevi fallback case (see `series_claim_result`)."""
    domain = await resolve_promoter_domain(client, event_page_html, event_page_url)
    if domain is None:
        return VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
            CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
        )
    verified = await verify_dns_txt_token(client, domain, token)
    return VerificationResult(
        CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER, _outcome_for(verified)
    )


def series_claim_result() -> VerificationResult:
    """Series claims (Piletilevi listings whose promoter never resolved) carry
    no verifiable identity — always admin review. A Trusted claimant
    fast-tracks around this at the claim-lifecycle layer (#413), not here —
    see `is_trusted_claimant`."""
    return VerificationResult(
        CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
        CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
    )


async def is_trusted_claimant(db: AsyncSession, organizer_id: int) -> bool:
    """True when `organizer_id` holds at least one admin-approved claim other
    than an automated Fienta-token Publisher claim — CONTEXT.md's Trusted
    claimant glossary entry. Revoking a claim already excludes it (its status
    moves off CLAIM_STATUS_APPROVED), so no separate "removed from the count"
    step is needed.

    Derived from the existing Claim/Publisher/Source columns rather than a
    dedicated verification-mechanism column: a Publisher claim against Fienta
    is 1:1 with the Fienta-token mechanism (#412 wires up no alternative for
    that source), so excluding Fienta-sourced Publisher claims is equivalent
    to excluding Fienta-token-verified claims.
    """
    fienta_publisher_ids = (
        select(Publisher.id)
        .join(Source, Source.id == Publisher.source_id)
        .where(Source.slug == SOURCE_SLUG_FIENTA)
    )
    result = await db.scalars(
        select(Claim.id)
        .where(Claim.organizer_id == organizer_id, Claim.status == CLAIM_STATUS_APPROVED)
        .where(
            (Claim.kind == CLAIM_KIND_SERIES)
            | Claim.publisher_id.not_in(fienta_publisher_ids)
        )
        .limit(1)
    )
    return result.first() is not None
