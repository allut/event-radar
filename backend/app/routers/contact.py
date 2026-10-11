"""POST /contact — public contact-form submission, delivered by email only."""

import logging

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.constants.email import (
    CONTACT_HONEYPOT_MAX_LEN,
    CONTACT_FIELD_MIN_LEN,
    CONTACT_MESSAGE_MAX_LEN,
    CONTACT_NAME_MAX_LEN,
    CONTACT_SUCCESS_DETAIL,
)
from app.constants.log_events import LOG_EVENT_CONTACT_HONEYPOT
from app.constants.rate_limits import RATE_LIMIT_CONTACT
from app.email.contact import send_contact_message
from app.rate_limit import limiter
from app.auth.utils import mask_email

log = logging.getLogger(__name__)
router = APIRouter(prefix="/contact", tags=["contact"])


class ContactBody(BaseModel):
    name: str = Field(min_length=CONTACT_FIELD_MIN_LEN, max_length=CONTACT_NAME_MAX_LEN)
    email: EmailStr
    message: str = Field(min_length=CONTACT_FIELD_MIN_LEN, max_length=CONTACT_MESSAGE_MAX_LEN)
    website: str = Field("", max_length=CONTACT_HONEYPOT_MAX_LEN)  # honeypot — real users leave this blank


@router.post("", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_CONTACT)
async def submit_contact(body: ContactBody, request: Request) -> dict:
    """Submit the contact form. Always returns the same success shape, even
    when the honeypot is tripped, so a bot gets no signal that it was caught."""
    if body.website.strip():
        log.warning(
            "contact form honeypot tripped (from %s)",
            mask_email(body.email),
            extra={"event": LOG_EVENT_CONTACT_HONEYPOT},
        )
        return {"detail": CONTACT_SUCCESS_DETAIL}

    try:
        await send_contact_message(body.name, body.email, body.message)
    except Exception:
        log.exception("Failed to send contact message from %s", mask_email(body.email))
        # Do not surface email errors to caller.

    return {"detail": CONTACT_SUCCESS_DETAIL}
