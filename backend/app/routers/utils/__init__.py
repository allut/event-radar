"""Shared serialization helpers for event routers."""

import logging


from app.constants.claims import (
    CLAIM_DNS_TXT_RECORD_LABEL,
    CLAIM_DNS_VERIFICATION_MECHANISMS,
)

log = logging.getLogger(__name__)


def claim_dns_record_name(mechanism: str | None, domain: str | None) -> str | None:
    """The TXT record name a DNS-TXT/Piletilevi-promoter claim's organizer is
    told to add (#412/#413) — shared by the organizer-facing pending screen
    (organizer_claims.py) and the admin claims queue (admin.py, #420) so the
    two never disagree on the record name shown for the same claim."""
    if mechanism in CLAIM_DNS_VERIFICATION_MECHANISMS and domain:
        return f"{CLAIM_DNS_TXT_RECORD_LABEL}.{domain}"
    return None
