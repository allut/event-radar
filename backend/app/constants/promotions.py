"""Promotions: stored statuses, window and cap rules, pricing, grant validation, error codes."""

import re
from decimal import Decimal

# Stored statuses are commercial only. Scheduled, live and finished are
# computed from the window and today's Tallinn date, never stored.
PROMOTION_STATUS_UNPAID = "unpaid"
PROMOTION_STATUS_PAID = "paid"
PROMOTION_STATUS_ENDED_EARLY = "ended_early"
PROMOTION_STATUS_VOID = "void"
VALID_PROMOTION_STATUSES = frozenset(
    {
        PROMOTION_STATUS_UNPAID,
        PROMOTION_STATUS_PAID,
        PROMOTION_STATUS_ENDED_EARLY,
        PROMOTION_STATUS_VOID,
    }
)
# Statuses whose window holds cap days and blocks an overlapping window.
PROMOTION_HOLDING_STATUSES = frozenset({PROMOTION_STATUS_UNPAID, PROMOTION_STATUS_PAID})

# Computed, API-facing only.
PROMOTION_STATE_SCHEDULED = "scheduled"
PROMOTION_STATE_LIVE = "live"
PROMOTION_STATE_FINISHED = "finished"
VALID_PROMOTION_STATES = frozenset(
    {PROMOTION_STATE_SCHEDULED, PROMOTION_STATE_LIVE, PROMOTION_STATE_FINISHED}
)

PROMOTION_INVOICE_SOURCE_MANUAL = "manual"
PROMOTION_GRANTED_BY_ADMIN = "admin"

# Window and cap rules.
PROMOTION_LIVE_CAP = 5
PROMOTION_MIN_DAYS = 3
PROMOTION_MAX_DAYS = 14
PROMOTION_CAP_STRIP_DAYS = 14
# The earliest start is this many Tallinn days after today (tomorrow).
PROMOTION_MIN_LEAD_DAYS = 1

# Pricing: flat per day, net, plus the VAT rate stored on the row at sale.
PROMOTION_DAY_PRICE_CENTS = 500
PROMOTION_VAT_RATE_PERCENT = Decimal("24.00")

# One transaction-scoped Postgres advisory lock serializes every cap
# check-and-insert (the cap is global, so one key covers it).
PROMOTION_CAP_LOCK_KEY = 6_000_597

# Manual invoice references live in the ER-M- series.
PROMOTION_INVOICE_PREFIX = "ER-M-"
PROMOTION_INVOICE_REFERENCE_RE = re.compile(r"^ER-M-[A-Za-z0-9][A-Za-z0-9/_-]{0,39}$")
# Estonian business registry codes (Äriregister) are 8 digits.
PROMOTION_REGISTRY_CODE_RE = re.compile(r"^\d{8}$")

PROMOTION_ADVERTISER_NAME_MAX_CHARS = 255
PROMOTION_BILLING_EMAIL_MAX_CHARS = 255
PROMOTION_NOTE_MAX_CHARS = 1000

ADMIN_PROMOTIONS_PAGE_SIZE: int = 50
ADMIN_PROMOTIONS_MAX_PAGE_SIZE: int = 500

# Rule-violation codes (grant refusals and live validation).
PROMOTION_ERROR_NO_OWNER = "no_owner"
PROMOTION_ERROR_WINDOW_ORDER = "window_order"
PROMOTION_ERROR_TOO_SHORT = "window_too_short"
PROMOTION_ERROR_TOO_LONG = "window_too_long"
PROMOTION_ERROR_STARTS_TOO_EARLY = "starts_too_early"
PROMOTION_ERROR_ENDS_AFTER_EVENT = "ends_after_event"
PROMOTION_ERROR_OVERLAP = "overlap"
PROMOTION_ERROR_CAP_EXCEEDED = "cap_exceeded"
PROMOTION_ERROR_NOTE_REQUIRED = "complimentary_note_required"
PROMOTION_ERROR_INVALID_REGISTRY_CODE = "invalid_registry_code"
PROMOTION_ERROR_INVALID_INVOICE_REFERENCE = "invalid_invoice_reference"
PROMOTION_ERROR_INVOICE_ON_COMPLIMENTARY = "invoice_on_complimentary"

PROMOTION_ERROR_MESSAGES = {
    PROMOTION_ERROR_NO_OWNER: "This event has no owning Organizer, so it cannot be promoted.",
    PROMOTION_ERROR_WINDOW_ORDER: "The end date is before the start date.",
    PROMOTION_ERROR_TOO_SHORT: f"A Promotion must run at least {PROMOTION_MIN_DAYS} days.",
    PROMOTION_ERROR_TOO_LONG: f"A Promotion can run at most {PROMOTION_MAX_DAYS} days.",
    PROMOTION_ERROR_STARTS_TOO_EARLY: "A Promotion starts tomorrow at the earliest.",
    PROMOTION_ERROR_ENDS_AFTER_EVENT: "A Promotion must end on or before the event's last day.",
    PROMOTION_ERROR_OVERLAP: "The window overlaps another Promotion on this event.",
    PROMOTION_ERROR_CAP_EXCEEDED: f"More than {PROMOTION_LIVE_CAP} Promotions would be live on a day in this window.",
    PROMOTION_ERROR_NOTE_REQUIRED: "A complimentary Promotion needs a note.",
    PROMOTION_ERROR_INVALID_REGISTRY_CODE: "The registry code must be 8 digits.",
    PROMOTION_ERROR_INVALID_INVOICE_REFERENCE: f"The invoice reference must start with {PROMOTION_INVOICE_PREFIX}.",
    PROMOTION_ERROR_INVOICE_ON_COMPLIMENTARY: "A complimentary Promotion has no invoice.",
}
ERROR_PROMOTION_INVALID_STATE = "state must be one of scheduled, live, finished"
