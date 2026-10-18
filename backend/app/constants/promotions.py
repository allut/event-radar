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
# `end_reason` for an admin-ended or admin-voided Promotion; the free-text
# reason (the P2B statement of reasons) is stored in `end_note`.
PROMOTION_END_REASON_ADMIN = "admin"
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
# Lifecycle commands (#601).
PROMOTION_ERROR_INVALID_TRANSITION = "invalid_transition"
PROMOTION_ERROR_ALREADY_STARTED = "already_started"
PROMOTION_ERROR_NOT_EDITABLE = "not_editable"
PROMOTION_ERROR_NO_CHANGES = "no_changes"
PROMOTION_ERROR_LIVE_EDIT_FIELDS = "live_edit_end_date_only"
PROMOTION_ERROR_LIVE_END_MUST_SHORTEN = "live_end_must_shorten"
PROMOTION_ERROR_LIVE_END_IN_PAST = "live_end_in_past"
PROMOTION_ERROR_ADVERTISER_NAME_REQUIRED = "advertiser_legal_name_required"
PROMOTION_ERROR_REASON_REQUIRED = "reason_required"
PROMOTION_ERROR_REPOINT_SAME_EVENT = "repoint_same_event"
PROMOTION_ERROR_REPOINT_TARGET_NOT_FOUND = "repoint_target_not_found"
PROMOTION_ERROR_REPOINT_NOT_OWNER = "repoint_not_same_owner"
PROMOTION_ERROR_REPOINT_NOT_SAME_GROUP = "repoint_not_same_dedup_group"
PROMOTION_ERROR_REFUND_NOT_PAID = "refund_not_paid"
PROMOTION_ERROR_REFUND_AMOUNT = "refund_amount_invalid"
PROMOTION_ERROR_REFUND_EXCEEDS_PAID = "refund_exceeds_paid"
PROMOTION_ERROR_REFUND_NOTE_REQUIRED = "refund_note_required"

# Codes that mean "the state of things forbids this" (HTTP 409); every other
# code is a bad input (HTTP 422).
PROMOTION_CONFLICT_ERROR_CODES = frozenset(
    {
        PROMOTION_ERROR_NO_OWNER,
        PROMOTION_ERROR_OVERLAP,
        PROMOTION_ERROR_CAP_EXCEEDED,
        PROMOTION_ERROR_INVALID_TRANSITION,
        PROMOTION_ERROR_ALREADY_STARTED,
        PROMOTION_ERROR_NOT_EDITABLE,
        PROMOTION_ERROR_REPOINT_NOT_OWNER,
        PROMOTION_ERROR_REPOINT_NOT_SAME_GROUP,
        PROMOTION_ERROR_REFUND_NOT_PAID,
        PROMOTION_ERROR_REFUND_EXCEEDS_PAID,
    }
)

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
    PROMOTION_ERROR_INVALID_TRANSITION: "This Promotion's status does not allow that action.",
    PROMOTION_ERROR_ALREADY_STARTED: "The Promotion has already started.",
    PROMOTION_ERROR_NOT_EDITABLE: "A finished, ended or void Promotion cannot be edited.",
    PROMOTION_ERROR_NO_CHANGES: "Nothing to change.",
    PROMOTION_ERROR_LIVE_EDIT_FIELDS: "While a Promotion is live, only an earlier end date can change.",
    PROMOTION_ERROR_LIVE_END_MUST_SHORTEN: "A live Promotion's end date can only move earlier.",
    PROMOTION_ERROR_LIVE_END_IN_PAST: "The new end date cannot be before today.",
    PROMOTION_ERROR_ADVERTISER_NAME_REQUIRED: "The advertiser legal name is required.",
    PROMOTION_ERROR_REASON_REQUIRED: "A reason is required.",
    PROMOTION_ERROR_REPOINT_SAME_EVENT: "The Promotion already points at that event.",
    PROMOTION_ERROR_REPOINT_TARGET_NOT_FOUND: "The target event does not exist.",
    PROMOTION_ERROR_REPOINT_NOT_OWNER: "The target event is not owned by the Promotion's Organizer.",
    PROMOTION_ERROR_REPOINT_NOT_SAME_GROUP: "The target event is not in the same dedup group.",
    PROMOTION_ERROR_REFUND_NOT_PAID: "Only a paid Promotion that was not complimentary can be refunded.",
    PROMOTION_ERROR_REFUND_AMOUNT: "The refund amount must be a positive number of cents.",
    PROMOTION_ERROR_REFUND_EXCEEDS_PAID: "The refund would exceed what was paid.",
    PROMOTION_ERROR_REFUND_NOTE_REQUIRED: "A refund note is required.",
}
ERROR_PROMOTION_INVALID_STATE = "state must be one of scheduled, live, finished"

# Explore Sponsored slot (#603).
# Tile number (1-based) the slot renders at on page 1.
PROMOTION_EXPLORE_SLOT_TILE = 4
# Page 1 needs at least this many organic results before a slot may appear.
PROMOTION_EXPLORE_MIN_ORGANIC = 6
# The client opts in with `GET /explore?sponsored_slot=true`; the prerender never does.
# "Miks?" explanation variants: Explore filters or `q` active, or neither.
PROMOTION_EXPLANATION_FILTERS = "filters"
PROMOTION_EXPLANATION_NONE = "none"

# Self-declared bots never get a slot, so delivery counts stay honest.
PROMOTION_BOT_USER_AGENT_RE = re.compile(
    r"bot|crawl|spider|slurp|facebookexternalhit|bingpreview|mediapartners",
    re.IGNORECASE,
)

# Named not-showing reasons, one per failing fill-gate clause (the console, the
# portal and the daily stats row share them).
PROMOTION_NOT_SHOWING_SLOTS_DISABLED = "slots_disabled"
PROMOTION_NOT_SHOWING_BOT = "bot_user_agent"
PROMOTION_NOT_SHOWING_NOT_PAID = "not_paid"
PROMOTION_NOT_SHOWING_OUTSIDE_WINDOW = "outside_window"
PROMOTION_NOT_SHOWING_EVENT_NOT_PUBLIC = "event_not_public"
PROMOTION_NOT_SHOWING_EVENT_NOT_CANONICAL = "event_not_canonical"
PROMOTION_NOT_SHOWING_EVENT_ENDED = "event_ended"
PROMOTION_NOT_SHOWING_NOT_OWNED = "organizer_not_owner"
PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED = "restriction_unassessed"
PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED = "restriction_flagged"
PROMOTION_NOT_SHOWING_FILTERS_MISMATCH = "filters_mismatch"

# `events.promotion_restriction`: `None` = unassessed, `none` = clear.
PROMOTION_RESTRICTION_NONE = "none"

# Content snapshots (#601): what a Promotion displayed, taken when it becomes
# paid and on every edit or re-point while scheduled or live. Never pruned.
PROMOTION_SNAPSHOT_TRIGGER_GRANT = "grant"
PROMOTION_SNAPSHOT_TRIGGER_MARK_PAID = "mark_paid"
PROMOTION_SNAPSHOT_TRIGGER_EDIT = "edit"
PROMOTION_SNAPSHOT_TRIGGER_REPOINT = "repoint"
PROMOTION_SNAPSHOT_DESCRIPTION_MAX_CHARS = 300
# The caption on a Sponsored slot card.
PROMOTION_LABEL_TEXT_TEMPLATE = "REKLAAM · {advertiser}"

# Delivery counters (#606). Columns of promotion_daily_stats the in-process
# counter owns; the rest are written by their own jobs.
PROMOTION_STAT_EXPLORE_SERVED = "explore_served"
PROMOTION_STAT_WEB_OPENS = "web_opens"
PROMOTION_STAT_SLOT_DISLIKES = "slot_dislikes"
PROMOTION_COUNTER_COLUMNS = (
    PROMOTION_STAT_EXPLORE_SERVED,
    PROMOTION_STAT_WEB_OPENS,
    PROMOTION_STAT_SLOT_DISLIKES,
)
# Every column the per-day table reports, in display order.
PROMOTION_STAT_REPORT_COLUMNS = (
    PROMOTION_STAT_EXPLORE_SERVED,
    "daily5_placed",
    "digest_sent",
    PROMOTION_STAT_WEB_OPENS,
    "digest_opens",
    PROMOTION_STAT_SLOT_DISLIKES,
)
PROMOTION_COUNTER_FLUSH_SECONDS = 60
# The ref query value Explore slot card links carry.
PROMOTION_REF_AD = "ad"
ERROR_PROMOTION_NOT_FOUND = "promotion not found"
