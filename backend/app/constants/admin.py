"""Admin console: queue page sizes, inspector limits, audited admin action names, admin job errors."""

# Admin queue pagination caps. The default page sizes (ADMIN_REPORTS_QUEUE_PAGE_SIZE and
# siblings) are cross-stack: shared/app-config.json → app._generated.shared_constants.
ADMIN_REPORTS_QUEUE_MAX_PAGE_SIZE: int = 500

# Event inspector (routers/admin.py GET /admin/events/{id}, issue #157) caps
# how many raw_events rows it inlines — unlike the paginated queues above,
# this is a fixed ceiling (not offset/limit query params) since it's one
# sub-list within a single-event payload, not its own listing endpoint. Each
# row carries a full verbatim JSONB payload, so this bounds response size
# for an event with a long refetch/dedup-merge history.
ADMIN_EVENT_INSPECTOR_RAW_EVENTS_LIMIT: int = 20

# Admin dedup-groups pagination cap (routers/admin.py GET /admin/dedup/groups).
ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE: int = 500

# Admin review-queue pagination cap (routers/admin.py GET /admin/submissions): small
# default page, generous cap.
ADMIN_REVIEW_QUEUE_MAX_PAGE_SIZE: int = 500

# Admin claims-queue pagination cap (routers/admin.py GET /admin/claims, issue #420).
ADMIN_CLAIMS_QUEUE_MAX_PAGE_SIZE: int = 500

# `action` field values for LOG_EVENT_ADMIN_ACTION (issue #155).
ADMIN_ACTION_RESOLVE_REPORTS = "resolve_reports"
ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT = "takedown_reported_event"
ADMIN_ACTION_APPROVE_SUBMISSION = "approve_submission"
ADMIN_ACTION_RETRACT_SUBMISSION = "retract_submission"
# `action` field values for /admin/claims (issue #420).
ADMIN_ACTION_GRANT_CLAIM = "grant_claim"
ADMIN_ACTION_DECLINE_CLAIM = "decline_claim"
ADMIN_ACTION_REVOKE_CLAIM = "revoke_claim"
ADMIN_ACTION_PROMOTION_GRANT = "promotion_grant"
ADMIN_ACTION_PROMOTION_MARK_PAID = "promotion_mark_paid"
ADMIN_ACTION_PROMOTION_EDIT = "promotion_edit"
ADMIN_ACTION_PROMOTION_REPOINT = "promotion_repoint"
ADMIN_ACTION_PROMOTION_END = "promotion_end"
ADMIN_ACTION_PROMOTION_VOID = "promotion_void"
ADMIN_ACTION_PROMOTION_REFUND = "promotion_refund"
ADMIN_ACTION_PROMOTION_CLEAR_RESTRICTION = "promotion_clear_restriction"
# A logged complaint about the ads (#620); its target is not a Promotion id.
ADMIN_ACTION_PROMOTION_COMPLAINT = "promotion_complaint"
# Written by the automatic sweep (#602), not by an admin.
ADMIN_ACTION_PROMOTION_SYSTEM_VOID = "promotion_system_void"
ADMIN_ACTION_PROMOTION_SYSTEM_END = "promotion_system_end"
# Promotion requests (#615): the target is the request id, not a Promotion id,
# so these stay out of PROMOTION_ADMIN_ACTIONS (the Promotion detail's audit).
ADMIN_ACTION_PROMOTION_REQUEST_GRANT = "promotion_request_grant"
ADMIN_ACTION_PROMOTION_REQUEST_DECLINE = "promotion_request_decline"
# Written by the Stripe webhook (#618, #619), not by an admin.
ADMIN_ACTION_PROMOTION_SYSTEM_PAID = "promotion_system_paid"
ADMIN_ACTION_PROMOTION_SYSTEM_LATE_REFUND = "promotion_system_late_refund"
PROMOTION_ADMIN_ACTIONS = frozenset(
    {
        ADMIN_ACTION_PROMOTION_GRANT,
        ADMIN_ACTION_PROMOTION_MARK_PAID,
        ADMIN_ACTION_PROMOTION_EDIT,
        ADMIN_ACTION_PROMOTION_REPOINT,
        ADMIN_ACTION_PROMOTION_END,
        ADMIN_ACTION_PROMOTION_VOID,
        ADMIN_ACTION_PROMOTION_REFUND,
        ADMIN_ACTION_PROMOTION_CLEAR_RESTRICTION,
        ADMIN_ACTION_PROMOTION_SYSTEM_VOID,
        ADMIN_ACTION_PROMOTION_SYSTEM_END,
        ADMIN_ACTION_PROMOTION_SYSTEM_PAID,
        ADMIN_ACTION_PROMOTION_SYSTEM_LATE_REFUND,
    }
)
# `action` field values for the /admin/pipeline job triggers (issue #159).
ADMIN_ACTION_INGEST = "ingest"
ADMIN_ACTION_INGEST_SOURCE = "ingest_source"
ADMIN_ACTION_DEDUP = "dedup"
ADMIN_ACTION_CLASSIFY = "classify"
ADMIN_ACTION_PUBLISH = "publish"
ADMIN_ACTION_GEOCODE = "geocode"
ADMIN_ACTION_REFETCH = "refetch"
ADMIN_ACTION_SYNC_ORGANIZERS = "sync_organizers"
ADMIN_ACTION_CLEANUP = "cleanup"
ADMIN_ACTION_BUILD_FEEDS = "build_feeds"
ADMIN_ACTION_SEND_DIGESTS = "send_digests"
ADMIN_ACTION_PIPELINE_RUN = "pipeline_run"

# routers/utils.py
ERROR_ADMIN_JOB_FAILED = "{name} failed; see server logs"
ERROR_ADMIN_JOB_ALREADY_RUNNING = "{name} is already running; try again once it finishes."
