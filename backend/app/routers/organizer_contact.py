"""POST /organizer/contact — authenticated organizer contact-form submission.

Sibling of routers/contact.py's public form, but scoped to a logged-in
organizer: name/email come from the session, not free text, so there's no
honeypot and no spoofable identity.
"""

import logging

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from app.constants.email import (
    CONTACT_FIELD_MIN_LEN,
    CONTACT_MESSAGE_MAX_LEN,
    CONTACT_SUCCESS_DETAIL,
)
from app.constants.rate_limits import RATE_LIMIT_ORGANIZER_CONTACT
from app.email.contact import send_contact_message
from app.models.models import Organizer
from app.rate_limit import limiter
from app.auth.dependencies import get_current_organizer
from app.auth.utils import mask_email

log = logging.getLogger(__name__)
# Must stay under /organizer/* — ORGANIZER_SESSION_COOKIE_PATH scopes the
# session cookie to Path=/api/organizer (see organizer_auth.py).
router = APIRouter(prefix="/organizer/contact", tags=["organizer-contact"])


class OrganizerContactBody(BaseModel):
    message: str = Field(
        min_length=CONTACT_FIELD_MIN_LEN, max_length=CONTACT_MESSAGE_MAX_LEN
    )


@router.post("", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_ORGANIZER_CONTACT)
async def submit_organizer_contact(
    body: OrganizerContactBody,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
) -> dict:
    try:
        await send_contact_message(
            current_organizer.name or current_organizer.email,
            current_organizer.email,
            body.message,
        )
    except Exception:
        log.exception(
            "Failed to send organizer contact message from %s",
            mask_email(current_organizer.email),
        )
        # Do not surface email errors to caller.

    return {"detail": CONTACT_SUCCESS_DETAIL}
