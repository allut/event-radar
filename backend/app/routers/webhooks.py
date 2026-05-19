"""Inbound webhooks — Resend inbound email."""

import hmac
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import AsyncSessionLocal, get_db
from app.llm.newsletter_extractor import extract_events_from_email
from app.models.models import RawInboundEmail

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


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
async def inbound_mail(
    request: Request,
    background_tasks: BackgroundTasks,
    secret: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Resend Inbound webhook — receives parsed email, stores it, triggers LLM extraction.

    Set RESEND_WEBHOOK_SECRET and append ?secret=<value> to the Resend inbound URL
    to guard the endpoint in production. Empty secret disables verification (dev only).
    """
    if settings.RESEND_WEBHOOK_SECRET and not hmac.compare_digest(
        secret, settings.RESEND_WEBHOOK_SECRET
    ):
        log.warning("inbound-mail: invalid webhook secret")
        return JSONResponse(
            {"status": "rejected"}, status_code=status.HTTP_401_UNAUTHORIZED
        )

    try:
        payload = await request.json()
    except Exception:
        log.warning("inbound-mail: invalid JSON body")
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

    if text_body or subject:
        background_tasks.add_task(_run_extraction, email_id, subject, text_body)
    else:
        log.info("inbound-mail %d: no text body, skipping extraction", email_id)

    return JSONResponse({"status": "accepted", "id": email_id})
