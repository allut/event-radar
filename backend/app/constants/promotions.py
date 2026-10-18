"""Promotions: stored statuses, window and cap rules, pricing, grant validation, error codes."""

import re
from decimal import Decimal

from app._generated.shared_constants import (
    PROMOTION_REF_AD as PROMOTION_REF_AD,
    PROMOTION_REF_DIGEST_AD as PROMOTION_REF_DIGEST_AD,
)

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

# Restriction clearance (#612): granting a restricted event needs both.
PROMOTION_ERROR_CLEARANCE_REQUIRED = "restriction_clearance_required"
PROMOTION_ERROR_CLEARANCE_NOTE_REQUIRED = "restriction_clearance_note_required"
PROMOTION_ERROR_CLEARANCE_NOT_NEEDED = "restriction_not_flagged"

# Request-path rule codes beyond the grant ones.
PROMOTION_ERROR_REQUEST_PENDING = "request_pending"
PROMOTION_ERROR_TERMS_NOT_ACCEPTED = "terms_not_accepted"
PROMOTION_ERROR_REGISTRY_CHECKSUM = "registry_code_checksum"
PROMOTION_ERROR_NOT_PROMOTABLE = "not_promotable"
PROMOTION_ERROR_REQUEST_NOT_PENDING = "request_not_pending"
PROMOTION_ERROR_REQUEST_DAILY_LIMIT = "daily_request_limit"
PROMOTION_ERROR_REQUEST_OWNER_CHANGED = "request_owner_changed"

# Codes that mean "the state of things forbids this" (HTTP 409); every other
# code is a bad input (HTTP 422).
PROMOTION_CONFLICT_ERROR_CODES = frozenset(
    {
        PROMOTION_ERROR_NO_OWNER,
        PROMOTION_ERROR_OVERLAP,
        PROMOTION_ERROR_CAP_EXCEEDED,
        PROMOTION_ERROR_REQUEST_PENDING,
        PROMOTION_ERROR_NOT_PROMOTABLE,
        PROMOTION_ERROR_REQUEST_NOT_PENDING,
        PROMOTION_ERROR_REQUEST_OWNER_CHANGED,
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
    PROMOTION_ERROR_REGISTRY_CHECKSUM: "That is not a valid Estonian registry code.",
    PROMOTION_ERROR_REQUEST_PENDING: "This event already has a pending Promotion request.",
    PROMOTION_ERROR_TERMS_NOT_ACCEPTED: "The Organizer terms must be accepted.",
    PROMOTION_ERROR_NOT_PROMOTABLE: "This event cannot be promoted right now.",
    PROMOTION_ERROR_REQUEST_NOT_PENDING: "The request is no longer pending.",
    PROMOTION_ERROR_REQUEST_OWNER_CHANGED: "The requesting Organizer no longer owns this event.",
    PROMOTION_ERROR_REQUEST_DAILY_LIMIT: "Too many Promotion requests today.",
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
    PROMOTION_ERROR_CLEARANCE_REQUIRED: "This event carries a Promotion restriction; confirm the clearance.",
    PROMOTION_ERROR_CLEARANCE_NOTE_REQUIRED: "A Restriction clearance needs a note.",
    PROMOTION_ERROR_CLEARANCE_NOT_NEEDED: "This event carries no Promotion restriction to clear.",
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
PROMOTION_RESTRICTIONS = ("tobacco", "gambling", "alcohol", "political", "weapons")
VALID_PROMOTION_RESTRICTION_VALUES = frozenset((PROMOTION_RESTRICTION_NONE, *PROMOTION_RESTRICTIONS))
# Restriction clearance (#612): granting a restricted event needs both.
# Admin-facing paths (frontend) linked from the newly-flagged email.
ADMIN_PROMOTIONS_PATH = "/admin/promotions"

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
PROMOTION_STAT_DAILY5_PLACED = "daily5_placed"
PROMOTION_STAT_DIGEST_SENT = "digest_sent"
PROMOTION_STAT_DIGEST_OPENS = "digest_opens"
PROMOTION_COUNTER_COLUMNS = (
    PROMOTION_STAT_EXPLORE_SERVED,
    PROMOTION_STAT_DAILY5_PLACED,
    PROMOTION_STAT_WEB_OPENS,
    PROMOTION_STAT_SLOT_DISLIKES,
    PROMOTION_STAT_DIGEST_SENT,
    PROMOTION_STAT_DIGEST_OPENS,
)
# Every column the per-day table reports, in display order.
PROMOTION_STAT_REPORT_COLUMNS = (
    PROMOTION_STAT_EXPLORE_SERVED,
    PROMOTION_STAT_DAILY5_PLACED,
    PROMOTION_STAT_DIGEST_SENT,
    PROMOTION_STAT_WEB_OPENS,
    PROMOTION_STAT_DIGEST_OPENS,
    PROMOTION_STAT_SLOT_DISLIKES,
)
PROMOTION_COUNTER_FLUSH_SECONDS = 60

# Automatic lifecycle sweep (#602): void unpaid, end on cancellation or claim
# revocation. Runs often so a Tallinn-midnight start and a takedown take
# effect within a minute.
PROMOTION_SWEEP_SECONDS = 60
PROMOTION_END_REASON_CLAIM_REVOKED = "claim_revoked"
# `end_reason` of an `unpaid` Promotion voided by the sweep at its start date.
PROMOTION_END_REASON_UNPAID_AT_START = "unpaid_at_start"
# Cancellation causes are carried over verbatim as `end_reason`; an event
# cancelled with no recorded cause counts as an admin retract.
PROMOTION_END_REASON_CANCELLATION_FALLBACK = "admin_retract"
# `end_note` for each automatic end; it is the reason in the Organizer's email.
PROMOTION_AUTO_END_NOTES = {
    "organizer_retract": "The event was retracted, so its Promotion ended.",
    "admin_retract": "The event was taken down, so its Promotion ended.",
    "report_takedown": "The event was taken down after a report, so its Promotion ended.",
    "source_gone": "The event is no longer listed by its source, so its Promotion ended.",
    PROMOTION_END_REASON_CLAIM_REVOKED: (
        "Your claim over the event was revoked, so its Promotion ended."
    ),
    PROMOTION_END_REASON_UNPAID_AT_START: "The Promotion was not paid before its start date.",
}
# End reasons whose Organizer gets an email. The system void is silent.
PROMOTION_AUTO_END_EMAIL_REASONS = frozenset(PROMOTION_AUTO_END_NOTES) - {
    PROMOTION_END_REASON_UNPAID_AT_START
}
ERROR_PROMOTION_NOT_FOUND = "promotion not found"

# Daily 5 Sponsored slot (#607).
# A Promotion shown to a user is not stored for them again for this many days.
PROMOTION_DAILY5_COOLDOWN_DAYS = 3
PROMOTION_EXPLANATION_DAILY5 = "daily5"
# Gate outcome the daily build stores per Promotion per day.
PROMOTION_GATE_OUTCOME_SHOWN = "shown"
PROMOTION_GATE_OUTCOME_PAUSED = "paused"
# Daily 5 context: the event starts after the builder's lookahead window.
PROMOTION_NOT_SHOWING_OUTSIDE_DAILY5_WINDOW = "outside_daily5_window"

# Trust panel, complaints and Withdraw (#620).
PROMOTION_TRUST_WINDOW_DAYS = 28
PROMOTION_TRUST_RECENT_COMPLAINTS = 20
# `admin_actions.target` of every logged complaint (it is about the ads, not
# one Promotion).
PROMOTION_COMPLAINT_TARGET = "promotion_ads"
PROMOTION_COMPLAINT_SOURCE_EMAIL = "email"
PROMOTION_COMPLAINT_SOURCE_CONTACT_FORM = "contact_form"
PROMOTION_COMPLAINT_SOURCE_OTHER = "other"
PROMOTION_COMPLAINT_SOURCES = (
    PROMOTION_COMPLAINT_SOURCE_EMAIL,
    PROMOTION_COMPLAINT_SOURCE_CONTACT_FORM,
    PROMOTION_COMPLAINT_SOURCE_OTHER,
)
PROMOTION_COMPLAINANT_MAX_CHARS = 200
# `end_reason` of a Promotion ended because the Operator withdrew the feature;
# unused whole days are refunded in full.
PROMOTION_END_REASON_FEATURE_WITHDRAWN = "feature_withdrawn"
PROMOTION_WITHDRAWN_NOTE = (
    "Event Radar has withdrawn Promotions, so this one ended early. "
    "Its unused days are refunded in full."
)
PROMOTION_WITHDRAWN_REFUND_NOTE = "Feature withdrawn: unused days refunded in full."
# Withdraw is refused while the slots flag is still on.
ERROR_PROMOTION_SLOTS_STILL_ENABLED = "slots_still_enabled"
# Organizer offer and Promotion requests (#614, #615).
# Version of the Organizer terms an Organizer accepts on a request (#613 ships
# the legal page; bump this when the terms change in substance).
ORGANIZER_TERMS_VERSION = 1
# Soft per-Organizer ceiling on new requests per Tallinn day.
ORGANIZER_DAILY_PROMOTION_REQUEST_CAP = 10
PROMOTION_REQUEST_STATUS_PENDING = "pending"
PROMOTION_REQUEST_STATUS_GRANTED = "granted"
PROMOTION_REQUEST_STATUS_DECLINED = "declined"
PROMOTION_REQUEST_STATUS_WITHDRAWN = "withdrawn"
PROMOTION_REQUEST_STATUS_EXPIRED = "expired"
VALID_PROMOTION_REQUEST_STATUSES = frozenset(
    {
        PROMOTION_REQUEST_STATUS_PENDING,
        PROMOTION_REQUEST_STATUS_GRANTED,
        PROMOTION_REQUEST_STATUS_DECLINED,
        PROMOTION_REQUEST_STATUS_WITHDRAWN,
        PROMOTION_REQUEST_STATUS_EXPIRED,
    }
)
PROMOTION_DECLINE_REASON_MAX_CHARS = 1000
# Sold-out days are listed for this many days after the earliest start.
PROMOTION_UNAVAILABLE_HORIZON_DAYS = 90
ADMIN_PROMOTION_REQUESTS_PAGE_SIZE = 50

# What the Organizer's Promotions list calls each row (plain-word labels are
# frontend strings keyed by these codes).
PROMOTION_LIST_REQUESTED = "requested"
PROMOTION_LIST_DECLINED = "declined"
PROMOTION_LIST_AWAITING_PAYMENT = "awaiting_payment"
PROMOTION_LIST_SCHEDULED = "scheduled"
PROMOTION_LIST_LIVE = "live"
PROMOTION_LIST_PAUSED = "paused"
PROMOTION_LIST_FINISHED = "finished"
PROMOTION_LIST_ENDED_EARLY = "ended_early"
PROMOTION_LIST_CANCELLED = "cancelled"
ERROR_PROMOTION_REQUEST_NOT_FOUND = "promotion request not found"
ERROR_PROMOTION_OFFER_DISABLED = "Not Found"
ERROR_PROMOTION_REQUEST_INVALID_STATUS = (
    "status must be one of pending, granted, declined, withdrawn, expired"
)
