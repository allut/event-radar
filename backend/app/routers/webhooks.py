"""Inbound webhooks — Resend inbound email."""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import time
from collections import OrderedDict
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
    FEATURE_INBOUND_WEBHOOK,
    LOG_EVENT_WEBHOOK_REJECTED,
    NEWSLETTER_SENDER_ALLOWED_DOMAINS,
    RATE_LIMIT_WEBHOOK_INBOUND_MAIL,
    SETTING_NAME_RESEND_WEBHOOK_SECRET,
    SVIX_ID_HEADER,
    SVIX_SECRET_PREFIX,
    SVIX_SIGNATURE_HEADER,
    SVIX_TIMESTAMP_HEADER,
    WEBHOOK_REASON_INVALID_JSON,
    WEBHOOK_REASON_REPLAY,
    WEBHOOK_REASON_SENDER_NOT_ALLOWLISTED,
    WEBHOOK_SEEN_IDS_MAX_ENTRIES,
    WEBHOOK_STATUS_ACCEPTED,
    WEBHOOK_STATUS_REJECTED,
    WEBHOOK_STATUS_SKIPPED,
    WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
)
from app.db import AsyncSessionLocal, get_db
from app.llm.newsletter_extractor import extract_events_from_email
from app.models.models import RawInboundEmail
from app.rate_limit import limiter
from app.auth.utils import require_configured_secret

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# In-memory, single-process nonce store (svix_id -> None, insertion order)
# closing the replay window described in OWASP audit G-6: a captured,
# validly-signed request replayed inside WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS
# re-verifies and would otherwise re-trigger extraction. Bounded LRU mirrors
# admin.py's _admin_auth_failures pattern — resets on deploy/restart, which
# is fine since the replay window itself is only 5 minutes.
_seen_webhook_ids: OrderedDict[str, None] = OrderedDict()


def _webhook_id_already_seen(svix_id: str) -> bool:
    """True (and records the id) the first time; True again on replay."""
    if svix_id in _seen_webhook_ids:
        _seen_webhook_ids.move_to_end(svix_id)
        return True
    _seen_webhook_ids[svix_id] = None
    while len(_seen_webhook_ids) > WEBHOOK_SEEN_IDS_MAX_ENTRIES:
        _seen_webhook_ids.popitem(last=False)
    return False


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

    secret_configured = require_configured_secret(
        settings.RESEND_WEBHOOK_SECRET,
        feature=FEATURE_INBOUND_WEBHOOK,
        setting_name=SETTING_NAME_RESEND_WEBHOOK_SECRET,
        app_env=settings.APP_ENV,
        allow_insecure_dev=settings.ALLOW_INSECURE_DEV,
    )
    if secret_configured and not _request_signature_valid(request, body):
        log.warning(
            "inbound-mail: invalid or missing webhook signature",
            extra={"event": LOG_EVENT_WEBHOOK_REJECTED},
        )
        return JSONResponse(
            {"status": WEBHOOK_STATUS_REJECTED}, status_code=status.HTTP_401_UNAUTHORIZED
        )

    # OWASP audit G-6: a captured, validly-signed request replayed inside
    # WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS otherwise re-verifies and creates a
    # duplicate RawInboundEmail row — nothing else collapses the duplicate
    # (no message-id unique constraint, and RawEvent.external_id is derived
    # from a fresh email_id per replay). Only enforced once signature
    # verification itself is enforced — an unsigned dev request has no
    # meaningful nonce to dedupe against.
    svix_id = request.headers.get(SVIX_ID_HEADER, "")
    if secret_configured and svix_id and _webhook_id_already_seen(svix_id):
        log.warning(
            "inbound-mail: replayed svix-id, rejecting",
            extra={"event": LOG_EVENT_WEBHOOK_REJECTED},
        )
        return JSONResponse(
            {"status": WEBHOOK_STATUS_REJECTED, "reason": WEBHOOK_REASON_REPLAY},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        payload = json.loads(body)
    except Exception:
        log.warning(
            "inbound-mail: invalid JSON body",
            extra={"event": LOG_EVENT_WEBHOOK_REJECTED},
        )
        return JSONResponse(
            {"status": WEBHOOK_STATUS_REJECTED, "reason": WEBHOOK_REASON_INVALID_JSON},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    from_addr = str(payload.get("from", ""))

    # OWASP audit G-6: checked (and, on failure, returned early) BEFORE the
    # RawInboundEmail insert below — previously every inbound mail was stored
    # in full regardless of sender, a data-minimisation cost with no
    # corresponding benefit while NEWSLETTER_SENDER_ALLOWED_DOMAINS is empty
    # (extraction never runs today) and an unnecessary retention cost once it
    # isn't.
    if not _sender_domain_allowed(from_addr):
        log.warning("inbound-mail: sender domain not allowlisted, skipping")
        return JSONResponse(
            {"status": WEBHOOK_STATUS_SKIPPED, "reason": WEBHOOK_REASON_SENDER_NOT_ALLOWLISTED}
        )

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

    if text_body or subject:
        background_tasks.add_task(_run_extraction, email_id, subject, text_body)
    else:
        log.info("inbound-mail %d: no text body, skipping extraction", email_id)

    return JSONResponse({"status": WEBHOOK_STATUS_ACCEPTED, "id": email_id})
