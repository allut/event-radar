"""Organizer claiming: claim kinds/statuses, verification mechanisms, DNS checks, search, caps, and claim errors."""

from app._generated.shared_constants import (
    CLAIM_DISCOVERY_STATUS_CLAIMED,
    CLAIM_DISCOVERY_STATUS_NOT_CLAIMABLE,
    CLAIM_DISCOVERY_STATUS_PENDING,
    CLAIM_DISCOVERY_STATUS_UNCLAIMED,
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_CANCELLED,
    CLAIM_STATUS_EXPIRED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_REVOKED,
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
    CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
    CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
    ORGANIZER_MAX_CATEGORIES,
)

VALID_CLAIM_KINDS = frozenset({CLAIM_KIND_PUBLISHER, CLAIM_KIND_SERIES})

# CLAIM_STATUS_DECLINED is API-facing only (#447), never stored, so this set
# leaves it out. A DB row's CLAIM_STATUS_REVOKED
# always means admin_decline_claim/auto_decline_other_pending_claims flipped
# a *pending* claim, since a real admin revoke of a *granted* claim
# (admin_revoke_claim) deletes the row outright rather than leaving it with
# this status. organizer_claims.py's serializers translate the stored value
# to this one for any row that still exists; the one case that legitimately
# reports CLAIM_STATUS_REVOKED is the tombstone built from the deleted
# claim's AdminAction audit row.
VALID_CLAIM_STATUSES = frozenset(
    {
        CLAIM_STATUS_PENDING,
        CLAIM_STATUS_APPROVED,
        CLAIM_STATUS_REVOKED,
        CLAIM_STATUS_CANCELLED,
        CLAIM_STATUS_EXPIRED,
    }
)
# A Publisher/Series key is free to claim again only once every prior claim
# against it has left this set (#413) — backs the partial unique indexes in
# migration 0043 that reject a duplicate/racing claim at insert time.
CLAIM_ACTIVE_STATUSES = frozenset({CLAIM_STATUS_PENDING, CLAIM_STATUS_APPROVED})

# Claim-proof verification mechanisms (#412) — app/claims/. Standalone
# verification engine, not yet wired into a claim lifecycle (#413).
CLAIM_TOKEN_BYTE_LENGTH = 16  # secrets.token_hex(16) -> 32 lowercase hex chars
CLAIM_TOKEN_PREFIX = "er-verify-"

# CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX (#428) is the Piletilevi
# Publisher fallback tier — a resolved promoter with
# only a plain contact mailbox (no domain-provable channel): auto-grants on
# an exact claimant-account-email match, else admin review with both emails
# shown as evidence (Claim.verification_contact carries the resolved one).
VALID_CLAIM_VERIFICATION_MECHANISMS = frozenset(
    {
        CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
        CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
        CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
        CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
        CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    }
)
# The mechanisms an organizer can self-service re-trigger (POST
# /organizer/claims/{id}/recheck) and whose pending claim expires after
# CLAIM_EXPIRY_DAYS of inactivity (#413) — admin_review carries no proof an
# organizer controls, so it has no recheck button and instead expires on the
# longer CLAIM_ADMIN_REVIEW_EXPIRY_DAYS window (#430; see
# app/claims/lifecycle.py::expire_stale_claims). piletilevi_mailbox is
# deliberately excluded here too (#428 review finding): unlike DNS-TXT (add a
# record) or Fienta (place a code), there is nothing an organizer can act on
# to fix a mismatch — the promoter's published contact and the organizer's
# own account email are both outside their control from this screen — so a
# mismatched/no-contact mailbox claim behaves exactly like admin_review: no
# recheck button, and the same longer expiry window.
CLAIM_AUTOMATED_VERIFICATION_MECHANISMS = frozenset(
    {
        CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
        CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
        CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
    }
)

CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT = "auto_grant"
CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW = "admin_review"
VALID_CLAIM_VERIFICATION_OUTCOMES = frozenset(
    {CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT, CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW}
)
# CLAIM_EXPIRY_DAYS (inactivity window before an unverified automated-mechanism
# claim expires, #413, resets on every POST /organizer/claims/{id}/recheck)
# and CLAIM_ADMIN_REVIEW_EXPIRY_DAYS (the longer window for a pending claim
# with no self-service recheck path — admin_review, and piletilevi_mailbox,
# see the CLAIM_AUTOMATED_VERIFICATION_MECHANISMS comment above — #430, slice
# 1 of #425; never reset, measured from Claim.last_checked_at's creation-time
# value) both come from shared/app-config.json (#443) so the frontend's
# claim-pending copy can interpolate the same figures instead of duplicating
# them.

# Bounded concurrency for expire_stale_claims' expiry-notification fan-out
# (#421) — same rationale as REPORT_EMAIL_SEND_CONCURRENCY (Resend free-tier
# rate; a large sweep shouldn't serialize dozens of Resend round trips).
CLAIM_EMAIL_SEND_CONCURRENCY: int = 8

# Claim-discovery status (#414) — computed on read from an event's
# representative EventSource + any active Claim on its target key, never
# persisted. Feeds the public event page's "is this your event?" CTA and the
# search/suggestions surfaces' exclusion filter.
# CLAIM_DISCOVERY_STATUS_NOT_CLAIMABLE (#445): a direct organizer submission
# has no ingested EventSource, so it can never be claimed — distinct from "unclaimed" (claimable, nobody has yet).
VALID_CLAIM_DISCOVERY_STATUSES = frozenset(
    {
        CLAIM_DISCOVERY_STATUS_UNCLAIMED,
        CLAIM_DISCOVERY_STATUS_PENDING,
        CLAIM_DISCOVERY_STATUS_CLAIMED,
        CLAIM_DISCOVERY_STATUS_NOT_CLAIMABLE,
    }
)

# GET /organizer/claims/search and .../suggestions (#414) result caps —
# small, human-browsable lists, not paginated collections. Candidates are
# over-fetched by this multiplier before the in-Python already-claimed
# filter, since that filter can't be pushed into the query (a Series claim's
# key is a normalized title+venue tuple, not a column).
CLAIM_SEARCH_RESULT_LIMIT = 20
CLAIM_SUGGESTIONS_LIMIT = 10
CLAIM_SEARCH_CANDIDATE_MULTIPLIER = 3
CLAIM_SEARCH_QUERY_MIN_LENGTH = 2

# DNS-TXT domain-control check, resolved via DNS-over-HTTPS (no new
# fetchable-content SSRF surface — this is a fixed, hardcoded resolver, never
# a source-supplied URL). Shared by the KUMU/Estonia Concert Hall hardcoded
# domains and a resolved Piletilevi promoter's contact domain.
CLAIM_DNS_TXT_RECORD_LABEL = "_eventradar-verify"
CLAIM_DNS_DOH_URL = "https://cloudflare-dns.com/dns-query"
DNS_RECORD_TYPE_TXT = "TXT"

# Free/shared-mailbox email providers excluded when resolving a Piletilevi
# promoter's contact email to a domain-control target — a promoter can't
# prove DNS control of a provider they don't own.
FREE_EMAIL_PROVIDER_DOMAINS = frozenset(
    {
        "gmail.com",
        "mail.ee",
        "hot.ee",
        "hotmail.com",
        "outlook.com",
        "yahoo.com",
        "live.com",
        "icloud.com",
        "mail.ru",
        "yandex.ru",
        "inbox.lv",
    }
)

# Same count-then-act soft ceiling, but for POST /organizer/claims — counts
# every claim-creation attempt (not just auto-granted ones), computed from
# Tallinn calendar-day start like ORGANIZER_DAILY_SUBMISSION_CAP (#413).
ORGANIZER_DAILY_CLAIM_CAP = 5
# Per-organizer BASE ceiling on pinned-field edits to already-claimed events,
# scoped across every event the organizer holds a claim on (not per-event) —
# counts edit attempts, not successful saves. Declared here ahead of the
# pinned-edit endpoint itself (a later #409 slice), which is the one that
# will enforce it. This is the effective cap for an organizer whose claim(s)
# cover a single event — scaled up by ORGANIZER_CLAIM_EDIT_CAP_PER_EVENT for
# every additional covered event, bounded by ORGANIZER_CLAIM_EDIT_CAP_CEILING
# (#438 — see claims/pinning.py::scaled_claim_edit_cap).
ORGANIZER_DAILY_CLAIM_EDIT_CAP = 20
# How many extra edits/day a covered event beyond the first adds to the
# organizer's daily claim-edit cap (#438) — e.g. a 61-event Estonia Concert
# Hall Publisher claim gets meaningfully more headroom than a single-event
# claim without the cap tracking claim size 1:1 (which would make a large
# institutional claim effectively unbounded).
ORGANIZER_CLAIM_EDIT_CAP_PER_EVENT = 2
# Upper ceiling on the scaled daily claim-edit cap (#438) — however many
# events an organizer's claim(s) cover, the cap never exceeds this, so it
# remains a genuine bounded limit rather than effectively unbounded for a
# very large institutional Publisher claim.
ORGANIZER_CLAIM_EDIT_CAP_CEILING = 100

# Publisher-claim event-list pagination cap (routers/organizer_claims.py GET
# /organizer/claims/{claim_id}/events, issue #436) — smaller than the admin queues
# (constants/admin.py) since this is one organizer's own claimed events, not an
# operator-wide queue. The default, CLAIM_EVENTS_PAGE_SIZE, is cross-stack
# (shared/app-config.json).
CLAIM_EVENTS_MAX_PAGE_SIZE: int = 100

# Claim-link magic links (#415) land on a distinct frontend route from a plain
# organizer sign-in link, so the frontend knows to POST
# /organizer/claims/verify-link (which also creates the claim) instead of
# /organizer/auth/verify — the two token types share a signing salt
# (generate_organizer_claim_link_token) but carry different claims.
ORGANIZER_CLAIM_VERIFY_PATH = "/organizer/claims/verify"

# The organizer's own-claims list (routers/organizer_claims.py GET
# /organizer/claims, the Your claims page, spec #551) caps at this size. Its default,
# ORGANIZER_OWN_CLAIMS_PAGE_SIZE, is cross-stack (shared/app-config.json): changing it
# moves every page boundary and breaks shared ?page=N links.
ORGANIZER_OWN_CLAIMS_MAX_PAGE_SIZE: int = 100

# Claim-edit `unpin` list bounds (pin_key() shapes are short; OWASP audit L-6).
CLAIM_UNPIN_MAX_ITEMS = 32
CLAIM_UNPIN_KEY_MAX_LEN = 64

ERROR_CLAIM_NOT_FOUND = "Claim not found."
ERROR_CLAIM_NOT_CLAIMABLE = "This event has no publisher or series that can be claimed."
ERROR_CLAIM_EVENTS_NOT_PUBLISHER = (
    "Only an approved Publisher claim has an event list."
)
# (#429) Explicit guard — a direct organizer submission has no ingested
# EventSource to claim against; keeps the claim mechanism (ingested events)
# and the submission-trust track (Organizer.verified) separate.
ERROR_CLAIM_OWN_SUBMISSION = "You cannot claim your own directly submitted event."
# (#431, slice 1 of #425) — a target already holding an *approved* claim
# still rejects a new one outright (no contest/override flow); a target
# holding only pending claims no longer does — see create_claim.
ERROR_CLAIM_TARGET_ALREADY_APPROVED = (
    "This publisher or series has already been claimed and verified."
    " Contact support if you believe this is a mistake."
)
ERROR_CLAIM_NOT_PENDING = "Only a pending claim can be cancelled or rechecked."
ERROR_CLAIM_ALREADY_RESOLVED = (
    "This claim has already been decided — only a pending claim can be"
    " granted or declined."
)
ERROR_CLAIM_NOT_APPROVED = "Only a granted claim can be revoked."
ERROR_CLAIM_QUEUE_INVALID_STATUS = "status must be 'pending' or 'approved'."
# (#428) Series claims never auto-grant — a non-blank justification is the
# only thing an organizer supplies at creation time, surfaced to the admin
# reviewing the claim.
ERROR_CLAIM_JUSTIFICATION_REQUIRED = (
    "A justification is required for a series claim (no specific promoter"
    " could be identified for this listing)."
)
CLAIM_JUSTIFICATION_MAX_CHARS = 2000
ERROR_DAILY_CLAIM_LIMIT = "Daily claim limit reached. Try again tomorrow."
ERROR_CLAIM_SEARCH_QUERY_TOO_SHORT = "Search query is too short."
ERROR_CLAIM_NOT_GRANTED = "This claim is not yet granted — editing stays locked until then."
ERROR_CLAIM_DORMANT = (
    "This claim is dormant — a duplicate claimed event now takes precedence, "
    "so editing stays locked until that's resolved."
)
# Their machine-readable companions, CLAIM_ERROR_CODE_NOT_GRANTED and
# CLAIM_ERROR_CODE_DORMANT (#444, from shared/), let the frontend tell them
# apart off `code` rather than the (English-only) `message`.
ERROR_DAILY_CLAIM_EDIT_LIMIT = "Daily claim-edit limit reached. Try again tomorrow."
ERROR_CLAIM_EVENT_NOT_FOUND = "No event could be resolved for this claim."
ERROR_CLAIM_EDIT_URL_DOMAIN = "URL must stay on the domain this claim was verified against."
ERROR_CLAIM_EDIT_CATEGORIES_CAP = (
    f"An event can have at most {ORGANIZER_MAX_CATEGORIES} categories in total."
)

CLAIM_DNS_VERIFICATION_MECHANISMS = frozenset(
    {CLAIM_VERIFICATION_MECHANISM_DNS_TXT, CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER}
)
CLAIM_DNS_DOH_ACCEPT_HEADER = {"Accept": "application/dns-json"}

# Piletilevi promoter JSON-LD resolution (claims/piletilevi_promoter.py).
PILETILEVI_PROMOTER_URL_MARKER = "/promoters/"
