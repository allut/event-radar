"""Admin endpoints — protected by the admin console session cookie."""


from fastapi import APIRouter


router = APIRouter(prefix="/admin")


# ---------------------------------------------------------------------------
# Claims queue (#420): grant/decline an admin-review-routed claim, revoke an
# already-granted one. Distinct from /admin/submissions (organizer-trust
# review) and /admin/reports (content moderation) — a claim's grant/decline/
# revoke is its own decision shape. See CONTEXT.md's Event Claiming glossary
# and app/claims/lifecycle.py for the organizer-facing create/cancel/recheck
# endpoints this complements.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Promotions (#600): JSON API for the cap strip, the list and the grant form.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Promotion lifecycle (#601): detail and commands. Each command runs under the
# cap lock, writes its audit row in the same transaction and returns the
# refreshed detail payload.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Promotion requests (#615): the queue, grant and decline. Under
# /promotion-requests (not /promotions/requests) so the int path of
# /promotions/{promotion_id} never shadows it.
# ---------------------------------------------------------------------------


