"""Organizer portal: daily caps, field length limits, image upload/Cloudinary, and submission errors."""

# Cross-stack field limits (shared/app-config.json). ORGANIZER_NAME_MAX_LEN is the Organizer.name
# column width (routers/organizer_profile.py, #175; models/models.py).
from app._generated.shared_constants import (
    ORGANIZER_NAME_MAX_LEN as ORGANIZER_NAME_MAX_LEN,
    ORGANIZER_VENUE_ADDRESS_MAX_LEN as ORGANIZER_VENUE_ADDRESS_MAX_LEN,
    ORGANIZER_VENUE_NAME_MAX_LEN as ORGANIZER_VENUE_NAME_MAX_LEN,
)

# Per-organizer daily submission ceiling (routers/organizer_events.py), computed
# from Tallinn calendar-day start — an IP rate limit alone can't cap a single
# organizer account across multiple IPs.
ORGANIZER_DAILY_SUBMISSION_CAP = 20
# Same count-then-act soft ceiling as ORGANIZER_DAILY_SUBMISSION_CAP, but for
# POST /organizer/events/image — submissions alone don't bound Cloudinary
# free-tier upload quota, since an upload can happen without ever completing
# a submission (organizer_image_uploads, app/models/models.py).
ORGANIZER_DAILY_IMAGE_UPLOAD_CAP = 20
# Same count-then-act soft ceiling, but for POST /organizer/venues — venues
# are created independently of a submission, so neither existing cap bounds
# them (routers/organizer_venues.py).
ORGANIZER_DAILY_VENUE_CREATION_CAP = 20

# Claim-editing surface (#416). Field-name pinning vocabulary lives directly
# in organizer_claim_edits.py (pin_key() calls) rather than as constants
# here — see CONTEXT.md's Event Claiming glossary for the pinned/synced
# rules (price fields and categories never participate).

# Field length caps for SubmitEventBody/PatchEventBody (routers/organizer_events.py).
# venue_name and currency mirror the Event column widths (models/models.py) so an
# over-length value 422s instead of raising asyncpg.StringDataRightTruncation; the
# Text-column fields (title/description/important_info) have no DB-enforced width,
# so these are abuse-prevention ceilings, not truncation-avoidance.
ORGANIZER_TITLE_MAX_LEN = 300
ORGANIZER_DESCRIPTION_MAX_LEN = 30000
ORGANIZER_IMPORTANT_INFO_MAX_LEN = 15000
ORGANIZER_CURRENCY_MAX_LEN = 3

# Organizer image upload (routers/organizer_events.py -> Cloudinary signed upload).
# IMAGE_UPLOAD_ALLOWED_MIME itself comes from shared/app-config.json (via
# app._generated.shared_constants) — mirrors the frontend's ORGANIZER_IMAGE_ALLOWED_MIME so both stacks
# stay in sync via the generator instead of two hand-maintained literals.
IMAGE_UPLOAD_MAX_BYTES = 8 * 1024 * 1024  # 8 MiB
CLOUDINARY_UPLOAD_URL_TEMPLATE = (
    "https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
)
# Path prefix every delivery URL of OUR Cloudinary account carries on
# res.cloudinary.com — the host alone is shared by every Cloudinary account, so
# organizer_events.py::_check_image_host also pins this account's cloud name
# (OWASP audit #6).
CLOUDINARY_DELIVERY_PATH_TEMPLATE = "/{cloud_name}/image/upload/"
# Leading-byte signatures for the three formats IMAGE_UPLOAD_ALLOWED_MIME
# allows. WebP needs its own check (organizer_events.py::_sniff_image_mime)
# since RIFF is a generic container format — the fourCC at offset 8 is what
# actually says "WEBP".
IMAGE_MAGIC_BYTES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}
MIME_IMAGE_WEBP = "image/webp"
# RIFF is a generic container format — the fourCC at WEBP_FOURCC_OFFSET is
# what actually says "WEBP" (organizer_events.py::_sniff_image_mime).
WEBP_RIFF_MAGIC = b"RIFF"
WEBP_FOURCC = b"WEBP"
WEBP_FOURCC_OFFSET = 8
IMAGE_EXTENSION_BY_MIME: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    MIME_IMAGE_WEBP: "webp",
}

# Namespace prefix for organizer-submitted events' synthetic external_id
# (routers/organizer_events.py) — distinguishes user-submission rows from any
# other source's external ids in event_sources.
ORGANIZER_SUBMISSION_EXTERNAL_ID_PREFIX = "org:"

# Ceiling applied to the LLM's quality_score for organizer-submitted events
# only (Event.submitted_by_organizer_id is not None), before it's persisted.
# Unlike is_explicit/is_non_event, quality_score has no deterministic keyword
# floor. PUBLISH_MIN_QUALITY_SCORE (0.4) is a low bar most real events already
# clear, so this ceiling isn't primarily a publish-gate defense — the actual
# steerable prize is ranking prominence: quality_score feeds the persona
# ranking formula (10% weight) and orders the public showcase/Explore
# `quality_score DESC`, so an organizer who controls the event text could
# otherwise push the model toward quality:1.0 to get outsized visibility
# regardless of the event's real quality. Capping below 1.0 bounds that
# upside while leaving normal submissions unaffected (OWASP audit F13).
ORGANIZER_SUBMISSION_QUALITY_SCORE_CEILING: float = 0.7

ERROR_ORGANIZER_NOT_FOUND = "Organizer not found."

ERROR_SUBMISSION_NOT_FOUND = "Submission not found."

# routers/organizer_events.py
ERROR_SUBMISSION_SOURCE_NOT_CONFIGURED = (
    "Submission source not configured; contact support."
)

ERROR_IMAGE_HOST_NOT_ALLOWED = (
    "Image URL must be uploaded via POST /organizer/events/image "
    "(res.cloudinary.com)."
)
ERROR_DAILY_SUBMISSION_LIMIT = "Daily submission limit reached. Try again tomorrow."
ERROR_DAILY_VENUE_CREATION_LIMIT = (
    "Daily venue creation limit reached. Try again tomorrow."
)
ERROR_VENUE_NOT_FOUND = "Venue not found."

ERROR_EVENT_CREATE_FAILED = "Could not create event; please try again."

ERROR_IMAGE_URL_SCHEME = "Image URL is not allowed (unsupported scheme)."
ERROR_UNSUPPORTED_IMAGE_TYPE = "Unsupported image type: {content_type!r}"
ERROR_DAILY_IMAGE_UPLOAD_LIMIT = "Daily image upload limit reached. Try again tomorrow."
ERROR_IMAGE_TOO_LARGE = "Image exceeds {max_bytes} bytes."
ERROR_IMAGE_UPLOAD_NOT_CONFIGURED = "Image upload is not configured."
ERROR_IMAGE_UPLOAD_FAILED = "Image upload failed; please try again."
