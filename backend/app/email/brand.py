"""Dial brand mark for the email header — the one assembly helper every
``*_HEADER`` builder calls, so the mark URL is built in a single place."""

from app.config import settings
from app.constants import EMAIL_BRAND_MARK_PATH
from app.email.styles import EmailStyles
from app.email.templates import EMAIL_BRAND_MARK


def brand_mark_html(styles: EmailStyles, base: str | None = None) -> str:
    """``<img>`` for the navy-tile Dial, hosted by the frontend's static
    assets. ``base`` defaults to ``settings.FRONTEND_URL`` (digest passes its
    own ``frontend_base``)."""
    return EMAIL_BRAND_MARK.format(
        src=f"{base or settings.FRONTEND_URL}{EMAIL_BRAND_MARK_PATH}",
        s_brand_mark=styles.s_brand_mark,
    )
