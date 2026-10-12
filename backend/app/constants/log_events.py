"""Structured log event names and statuses (the Axiom record shape — see docs/observability.md)."""

# "color_message" is uvicorn's own `extra=` on its startup/shutdown lines — kept
# reserved so it doesn't leak into the curated shipped schema (docs/observability.md).

# Structured log `event` field values (shipped as a first-class JSON key via
# `extra={"event": ...}`) — each keys an Axiom monitor. See docs/observability.md.
LOG_EVENT_JOB_RUN = "job_run"  # scheduled-job completion/failure telemetry
LOG_EVENT_RATE_LIMIT_BLOCK = "rate_limit_block"  # own per-IP 429 rejection
LOG_EVENT_LLM_DEGRADED = "llm_degraded"  # provider chain exhausted / backlog deferred
LOG_EVENT_AUTH_FAILED = "auth_failed"  # magic-link / admin auth reject
LOG_EVENT_WEBHOOK_REJECTED = "webhook_rejected"  # inbound-mail signature / body reject
LOG_EVENT_EMAIL_SEND_FAILED = "email_send_failed"  # Resend magic-link / digest failure
LOG_EVENT_CONTACT_HONEYPOT = "contact_honeypot_block"  # contact-form honeypot field tripped
LOG_EVENT_HOST_REJECTED = "host_rejected"  # HostCheckMiddleware Host-header reject
LOG_EVENT_REPORT_SUBMITTED = "report_submitted"  # POST /reports success
LOG_EVENT_ADMIN_ACTION = "admin_action"  # /admin/auth/* login/logout (issue #154)
# Global (not per-IP) daily unverified-account-creation budget crossed — see
# routers/utils.py::record_unverified_account_creation (OWASP audit F10).
LOG_EVENT_UNVERIFIED_ACCOUNT_BUDGET_EXCEEDED = "unverified_account_budget_exceeded"
# ADR 0002 (Google sign-in) — carries `track`/`outcome` (see GOOGLE_SIGNIN_OUTCOME_*).
LOG_EVENT_GOOGLE_SIGNIN = "google_signin"
# Network/5xx failure talking to Google (token exchange or JWKS fetch) — distinct
# from auth_failed, which is a caller-side/verification rejection, not an
# upstream-degradation signal.
LOG_EVENT_GOOGLE_SIGNIN_DEGRADED = "google_signin_degraded"
LOG_EVENT_IDENTITY_LINKED = "identity_linked"  # provider identity row created
# DELETE .../profile/identities/{provider} or .../users/me/identities/{provider}
LOG_EVENT_IDENTITY_UNLINKED = "identity_unlinked"
LOG_EVENT_SCHEMA_DRIFT = "schema_drift"  # boot-time alembic-head mismatch (see ERROR_SCHEMA_DRIFT)

# `status` field values for LOG_EVENT_JOB_RUN.
LOG_STATUS_OK = "ok"
LOG_STATUS_ERROR = "error"
