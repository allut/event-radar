"""Dial brand mark for the email header — the one assembly helper every
``*_HEADER`` builder calls, plus the inline attachment that backs it, so the
mark's ``cid:`` reference and its payload are built in a single place."""

import base64
from pathlib import Path

from app.constants import EMAIL_BRAND_MARK_CID, EMAIL_BRAND_MARK_FILENAME
from app.email.styles import EmailStyles
from app.email.templates import EMAIL_BRAND_MARK

BRAND_MARK_SRC = f"cid:{EMAIL_BRAND_MARK_CID}"

# Read once at import: ~4 KB, attached to every branded send.
_BRAND_MARK_B64 = base64.b64encode(
    (Path(__file__).parent / "assets" / EMAIL_BRAND_MARK_FILENAME).read_bytes()
).decode("ascii")


def brand_mark_html(styles: EmailStyles) -> str:
    """``<img>`` for the rounded navy-tile Dial, referencing the inline
    attachment from ``brand_mark_attachments()``."""
    return EMAIL_BRAND_MARK.format(src=BRAND_MARK_SRC, s_brand_mark=styles.s_brand_mark)


def brand_mark_attachments(html: str) -> list[dict[str, str]]:
    """Resend ``attachments`` entry for the mark when ``html`` references it,
    else ``[]`` — internal mails without the branded header stay attachment-free."""
    if BRAND_MARK_SRC not in html:
        return []
    return [
        {
            "filename": EMAIL_BRAND_MARK_FILENAME,
            "content": _BRAND_MARK_B64,
            "content_id": EMAIL_BRAND_MARK_CID,
        }
    ]
