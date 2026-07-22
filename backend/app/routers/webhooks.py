"""Inbound webhooks — Resend inbound email."""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import time
from email.utils import parseaddr

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Request,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    LOG_EVENT_WEBHOOK_REJECTED,
    NEWSLETTER_SENDER_ALLOWED_DOMAINS,
    RATE_LIMIT_WEBHOOK_INBOUND_MAIL,
    SVIX_ID_HEADER,
    SVIX_SECRET_PREFIX,
    SVIX_SIGNATURE_HEADER,
    SVIX_TIMESTAMP_HEADER,
    WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
)
from app.db import AsyncSessionLocal, get_db
from app.llm.newsletter_extractor import extract_events_from_email
from app.models.models import RawInboundEmail
from app.rate_limit import limiter
from app.routers.utils import require_configured_secret

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _timestamp_within_tolerance(svix_timestamp: str) -> bool:
    """True when svix_timestamp (Unix seconds) is within tolerance of now.

    Rejects both a stale header (replay of an old, legitimately-signed
    request) and a clock-skewed/garbage one.
    """
    try:
        ts = int(svix_timestamp)
    except ValueError:
        return False
    return abs(time.time() - ts) <= WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS


def _verify_svix_signature(
    secret: str, svix_id: str, svix_timestamp: str, body: bytes, signature_header: str
) -> bool:
    """Verify a Svix-signed webhook body.

    Per https://docs.svix.com/receiving/verifying-payloads/how-manual: the secret
    is "whsec_" + base64(key); the signed content is
    "{svix-id}.{svix-timestamp}.{raw body}" HMAC-SHA256'd with the decoded key and
    base64-encoded; the header carries one or more space-separated "v1,<sig>"
    entries (Svix rotates keys, so more than one may be present) — any match wins.
    """
    if not secret.startswith(SVIX_SECRET_PREFIX):
        log.error("RESEND_WEBHOOK_SECRET is not a valid Svix secret (missing %s prefix)", SVIX_SECRET_PREFIX)
        return False
    try:
        key = base64.b64decode(secret[len(SVIX_SECRET_PREFIX) :])
    except (ValueError, binascii.Error):
        return False
    signed_content = f"{svix_id}.{svix_timestamp}.".encode() + body
    expected = base64.b64encode(
        hmac.new(key, signed_content, hashlib.sha256).digest()
    ).decode()
    for entry in signature_header.split():
        _version, _, sig = entry.partition(",")
        if sig and hmac.compare_digest(sig, expected):
            return True
    return False


def _request_signature_valid(request: Request, body: bytes) -> bool:
    """All three Svix headers present, timestamp within tolerance, HMAC valid."""
    svix_id = request.headers.get(SVIX_ID_HEADER, "")
    svix_timestamp = request.headers.get(SVIX_TIMESTAMP_HEADER, "")
    svix_signature = request.headers.get(SVIX_SIGNATURE_HEADER, "")
    return bool(
        svix_id
        and svix_timestamp
        and svix_signature
        and _timestamp_within_tolerance(svix_timestamp)
        and _verify_svix_signature(
            settings.RESEND_WEBHOOK_SECRET, svix_id, svix_timestamp, body, svix_signature
        )
    )


def _sender_domain_allowed(from_addr: str) -> bool:
    """True when from_addr's domain is in NEWSLETTER_SENDER_ALLOWED_DOMAINS.

    The Svix signature only proves the request came from Resend, not who sent
    the underlying email — this is the layer that stops an arbitrary sender
    from injecting content into the newsletter-extraction LLM prompt.
    """
    _name, email = parseaddr(from_addr)
    domain = email.rpartition("@")[2].lower()
    return bool(domain) and domain in NEWSLETTER_SENDER_ALLOWED_DOMAINS


async def _run_extraction(email_id: int, subject: str, text_body: str) -> None:
    """Background task: extract events from email using a fresh DB session."""
    async with AsyncSessionLocal() as db:
        try:
            count = await extract_events_from_email(
                db, email_id=email_id, subject=subject, text_body=text_body
            )
            await db.commit()
            log.info(
                "Newsletter extraction committed: %d event(s) from email %d",
                count,
                email_id,
            )
        except Exception:
            await db.rollback()
            log.exception("Newsletter extraction failed for email %d", email_id)


@router.post("/inbound-mail", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_WEBHOOK_INBOUND_MAIL)
async def inbound_mail(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Resend Inbound webhook — receives parsed email, stores it, triggers LLM extraction.

    Verified via Svix signature (svix-id/svix-timestamp/svix-signature headers over
    the raw body) rather than a shared secret in the query string, which leaks into
    proxy/access logs and lets anyone who learns it inject fabricated events. Set
    RESEND_WEBHOOK_SECRET to the "whsec_..." signing secret shown on this webhook's
    page in the Resend dashboard (NOT passed as a URL query param). An empty secret
    fails closed outside development (require_configured_secret).
    """
    body = await request.body()

    if require_configured_secret(
        settings.RESEND_WEBHOOK_SECRET,
        feature="Webhook",
        setting_name="RESEND_WEBHOOK_SECRET",
        app_env=settings.APP_ENV,
    ) and not _request_signature_valid(request, body):
        log.warning(
            "inbound-mail: invalid or missing webhook signature",
            extra={"event": LOG_EVENT_WEBHOOK_REJECTED},
        )
        return JSONResponse(
            {"status": "rejected"}, status_code=status.HTTP_401_UNAUTHORIZED
        )

    try:
        payload = json.loads(body)
    except Exception:
        log.warning(
            "inbound-mail: invalid JSON body",
            extra={"event": LOG_EVENT_WEBHOOK_REJECTED},
        )
        return JSONResponse(
            {"status": "rejected", "reason": "invalid json"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    from_addr = str(payload.get("from", ""))
    to_raw = payload.get("to", "")
    to_addr = ", ".join(to_raw) if isinstance(to_raw, list) else str(to_raw)
    subject = str(payload.get("subject", ""))
    text_body = str(payload.get("text", "") or "")

    email = RawInboundEmail(
        from_addr=from_addr,
        to_addr=to_addr,
        subject=subject,
        raw_payload=payload,
    )
    db.add(email)
    await db.flush()
    email_id: int = email.id
    await db.commit()

    if not _sender_domain_allowed(from_addr):
        log.warning(
            "inbound-mail %d: sender domain not allowlisted, skipping extraction",
            email_id,
        )
    elif text_body or subject:
        background_tasks.add_task(_run_extraction, email_id, subject, text_body)
    else:
        log.info("inbound-mail %d: no text body, skipping extraction", email_id)

    return JSONResponse({"status": "accepted", "id": email_id})
