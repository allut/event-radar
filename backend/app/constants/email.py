"""Email: Resend, daily digest, unsubscribe, contact form, and the inbound-mail webhook."""

# Inbound-mail sender allowlist (domain part of the "from" header, lowercased).
# The Svix signature on POST /webhooks/inbound-mail only proves the request came
# from Resend, not who sent the underlying email — anyone able to email the
# configured inbound address could otherwise inject arbitrary content into the
# newsletter-extraction LLM prompt. Empty by default: no newsletter adapter is
# registered yet (app/ingestion/registry.py), so extraction is a no-op regardless;
# populate with trusted sender domains before wiring up the newsletter adapter —
# and only together with an SPF/DKIM/DMARC pass requirement in webhooks.py, since
# the "from" header alone is forgeable (OWASP audit #8).
NEWSLETTER_SENDER_ALLOWED_DOMAINS: frozenset[str] = frozenset()

# Resend email delivery
RESEND_SEND_URL = "https://api.resend.com/emails"
RESEND_TIMEOUT_SECONDS: float = 10.0
RESEND_ERROR_SNIPPET_LEN = 200
# Header Dial mark, embedded as an inline (CID) attachment rather than linked:
# Apple Mail's privacy proxy fails to fetch it from the Pages host. The file is
# backend/app/email/assets/<filename>, written by frontend/scripts/generate-icons.ts.
EMAIL_BRAND_MARK_FILENAME = "email-mark.png"
EMAIL_BRAND_MARK_CID = "event-radar-mark"

# Email i18n strings (subjects, labels, templates) live in shared/i18n/*.json.
DIGEST_MAX_WHY_GO_BULLETS = 3
# Concurrency cap when fanning out digest sends — bounded by Resend free-tier
# rate (10 req/s). Eight in-flight sends leaves headroom for occasional retries.
DIGEST_SEND_CONCURRENCY: int = 8
# send_daily_digests per-user outcome sentinels.
DIGEST_RESULT_SENT = "sent"
DIGEST_RESULT_SKIPPED = "skipped"

# Resend inbound-mail webhook signature verification (Svix scheme; see
# https://resend.com/docs/dashboard/webhooks/verify-webhooks-requests and
# https://docs.svix.com/receiving/verifying-payloads/how-manual). Verifying
# over the raw body via these headers replaces the old ?secret= query-string
# check, which leaked the shared secret into proxy/access logs.
SVIX_ID_HEADER = "svix-id"
SVIX_TIMESTAMP_HEADER = "svix-timestamp"
SVIX_SIGNATURE_HEADER = "svix-signature"
SVIX_SECRET_PREFIX = "whsec_"

HEADER_LIST_UNSUBSCRIBE = "List-Unsubscribe"

# Reject a signature whose svix-timestamp is further than this from "now" (either
# direction), blocking replay of an old, legitimately-signed request. Matches
# Svix's own recommended default tolerance.
WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = 300
# Bounds the in-memory seen-svix-id LRU (routers/webhooks.py::_seen_webhook_ids)
# the same way ADMIN_AUTH_FAILURES_MAX_ENTRIES bounds admin.py's lockout dict —
# a validly-signed request replayed inside WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS
# would otherwise re-verify and re-trigger extraction (OWASP audit G-6).
WEBHOOK_SEEN_IDS_MAX_ENTRIES = 4096

# One-click digest unsubscribe (routers/unsubscribe.py). A long TTL so a link in an
# old, unread inbox email still works; the endpoint is reversible (Undo/resubscribe)
# so a stale click carries low risk.
UNSUBSCRIBE_TOKEN_TTL_DAYS = 365

# Email ad consent (app/email/consent.py). Bump the version only for a material
# change to what the toggle's wording covers: the bump resets everyone to off.
EMAIL_AD_CONSENT_WORDING_VERSION = 1
CONSENT_SOURCE_SETTINGS = "settings"
CONSENT_SOURCE_EMAIL_LINK = "email_link"
CONSENT_SOURCE_EMAIL_LINK_UNDO = "email_link_undo"
CONSENT_SOURCE_DIGEST_UNSUBSCRIBE = "digest_unsubscribe"
CONSENT_SOURCE_WORDING_CHANGE = "wording_change"
CONSENT_SOURCE_ACCOUNT_DELETION = "account_deletion"
VALID_CONSENT_SOURCES = frozenset(
    {
        CONSENT_SOURCE_SETTINGS,
        CONSENT_SOURCE_EMAIL_LINK,
        CONSENT_SOURCE_EMAIL_LINK_UNDO,
        CONSENT_SOURCE_DIGEST_UNSUBSCRIBE,
        CONSENT_SOURCE_WORDING_CHANGE,
        CONSENT_SOURCE_ACCOUNT_DELETION,
    }
)
ERROR_AD_CONSENT_UNAVAILABLE = (
    "Email ads can only be turned on while the digest and Sponsored slots are on."
)

# Contact form (routers/contact.py)
CONTACT_NAME_MAX_LEN = 100
CONTACT_MESSAGE_MAX_LEN = 2000
CONTACT_FIELD_MIN_LEN = 1
# Always returned on success, even when the honeypot is tripped — a bot must
# get no signal that it was caught.
CONTACT_SUCCESS_DETAIL = "Message sent."

# routers/unsubscribe.py
ERROR_UNSUBSCRIBE_LINK_EXPIRED = (
    "Unsubscribe link has expired. Please use Settings instead."
)
ERROR_UNSUBSCRIBE_LINK_INVALID = "Invalid unsubscribe link."

CONTACT_HONEYPOT_MAX_LEN = 2048

# Inbound-mail webhook response bodies (routers/webhooks.py).
WEBHOOK_STATUS_ACCEPTED = "accepted"
WEBHOOK_STATUS_REJECTED = "rejected"
WEBHOOK_STATUS_SKIPPED = "skipped"
WEBHOOK_REASON_REPLAY = "replay"
WEBHOOK_REASON_INVALID_JSON = "invalid json"
WEBHOOK_REASON_SENDER_NOT_ALLOWLISTED = "sender not allowlisted"

HEADER_LIST_UNSUBSCRIBE_POST = "List-Unsubscribe-Post"
LIST_UNSUBSCRIBE_ONE_CLICK = "List-Unsubscribe=One-Click"
DIGEST_CATEGORY_FALLBACK = "event"
