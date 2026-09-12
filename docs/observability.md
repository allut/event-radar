# Observability & Monitoring (Axiom)

What's in here: the Axiom logging/monitoring spec — log shipping, dashboards, alerts, and the fields every structured log line carries.

Version-controlled spec for the Axiom monitors that watch the production log
stream. The backend ships prod logs to Axiom (`app/logging_config.py` →
`HttpLogShipHandler`); this file defines what to alert on. Monitors are created
by hand in the Axiom UI — this doc is the source of truth for their queries,
thresholds, and windows. Keep it in sync when you change a monitor.

## Log record shape

Every shipped line is one JSON object (`JsonLogFormatter`):

| Field | Always present | Notes |
|---|---|---|
| `ts` | yes | UTC ISO-8601, ms precision |
| `level` | yes | `INFO` / `WARNING` / `ERROR` |
| `logger` | yes | dotted module path, e.g. `app.ingestion.jobs` |
| `msg` | yes | rendered message text |
| `exc` | on exceptions | full traceback string |
| `event` | on tagged sites | structured anomaly tag — **prefer filtering on this** |
| `job` / `status` / `duration_ms` | on `event="job_run"` | per scheduled-job telemetry |
| `path` | on `event="rate_limit_block"` | request path that was throttled |

`event` values (defined in `app/constants.py`, `LOG_EVENT_*`):

| `event` | Meaning | Emitted from |
|---|---|---|
| `job_run` | scheduled job completed/failed (carries `job`, `status`, `duration_ms`) | `app/main.py::_scheduled` |
| `rate_limit_block` | own per-IP 429 rejection (carries `path`) | `app/rate_limit.py` |
| `llm_degraded` | LLM provider chain exhausted, or classify/dedup backlog deferred | `app/llm/router.py`, `app/ingestion/jobs.py` |
| `auth_failed` | magic-link / admin-basic / internal-tick auth rejected | `app/routers/auth.py`, `admin.py`, `main.py` |
| `webhook_rejected` | inbound-mail bad signature / bad body | `app/routers/webhooks.py` |
| `report_submitted` | `POST /reports` succeeded | `app/routers/reports.py` |
| `email_send_failed` | Resend magic-link or digest send failed | `app/auth/email.py`, `app/email/digest.py` |
| `admin_action` | console-initiated admin action — audit trail; carries `action`, one of 17 `ADMIN_ACTION_*` values (`app/constants.py`) | `app/routers/admin_auth.py`, `app/routers/utils.py` |
| `contact_honeypot_block` | contact-form honeypot field tripped (bot signal) | `app/routers/contact.py` |
| `host_rejected` | `HostCheckMiddleware` rejected a request's Host header — signals cache-poisoning/host-spoofing probes | `app/main.py` |
| `unverified_account_budget_exceeded` | global daily new-unverified-account budget crossed (mail-bomb early warning, OWASP audit F10) | `app/routers/utils.py::record_unverified_account_creation` |
| `google_signin` | organizer Google sign-in completed (carries `track`, `outcome` — one of `existing_login`/`new_account`/`auto_linked`/`confirmation_sent`) | `app/routers/organizer_auth.py::organizer_google_callback` |
| `google_signin_degraded` | network/5xx failure talking to Google (token exchange or JWKS fetch) — upstream degradation, distinct from a rejected caller | `app/routers/organizer_auth.py::organizer_google_callback` |
| `identity_linked` | a provider identity row was created (new account, auto-link, or confirmation-link absorption) | `app/routers/organizer_auth.py` |
| `identity_unlinked` | `DELETE /organizer/profile/identities/{provider}` succeeded | `app/routers/organizer_profile.py::unlink_own_identity` |

## Setup

1. **Notifier** — Axiom → Monitors → Notifiers → **New → Email**, name
   `event-radar-email`, recipient = your address. Every monitor below attaches
   this one notifier.
2. **Dataset** — the dataset named in `LOG_SHIP_URL`
   (`.../v1/datasets/<dataset>/ingest`). Substitute it for `['event-radar']`
   in the APL below if different.
3. Create each monitor from the table, pasting its APL and setting
   type/threshold/window/frequency.

## Monitors

APL is illustrative — adjust field names to what the live stream shows, and tune
thresholds after observing a few days of baseline volume.

| # | Monitor | Type | APL / condition | Alert when |
|---|---|---|---|---|
| 1 | Error spike | Threshold | `['event-radar'] \| where level == "ERROR" \| summarize count()` | count > 5 in 5 min |
| 2 | Scheduled job failed | Match | `['event-radar'] \| where event == "job_run" and status == "error"` | any match (msg carries `job` + `exc`) |
| 3 | Dead scheduler / stale feed ⭐ | Threshold (below) | `['event-radar'] \| where event == "job_run" and job == "build_daily_feeds" and status == "ok" \| summarize count()` over 25h | count < 1 |
| 3b | Stale ingest ⭐ | Threshold (below) | as #3, `job == "hourly ingest"`, window 120 min | count < 1 |
| 3c | Digest not sent | Threshold (below) | as #3, `job == "send_daily_digests"`, window 25h | count < 1 |
| 4 | LLM degradation | Threshold | `['event-radar'] \| where event == "llm_degraded" \| summarize count()` over 30 min | count > 3 |
| 5 | Auth / abuse spike | Threshold | `['event-radar'] \| where event in ("auth_failed", "rate_limit_block") \| summarize count()` over 10 min | count > 20 |
| 6 | Webhook probing | Threshold | `['event-radar'] \| where event == "webhook_rejected" \| summarize count()` over 15 min | count > 5 |
| 7 | Log-stream silence | Threshold (below) | `['event-radar'] \| summarize count()` over 30 min | count < 1 |
| 8 | Job-duration anomaly *(optional)* | AnomalyDetection | `['event-radar'] \| where event == "job_run" \| summarize avg(duration_ms) by job, bin_auto(_time)` | auto-baselined drift |
| 9 | Report abuse spike | Threshold | `['event-radar'] \| where event == "report_submitted" \| summarize count()` over 10 min | placeholder — tune after baseline volume observed |
| 10 | Admin action audit ⭐ | Match | `['event-radar'] \| where event == "admin_action"` | any match — the audit trail (17 `ADMIN_ACTION_*` values) exists but had no monitor watching it (OWASP audit F11); this makes every console-initiated admin action visible, not alert-worthy on its own |
| 11 | Host-header probing | Threshold | `['event-radar'] \| where event == "host_rejected" \| summarize count()` over 15 min | count > 5 — signals cache-poisoning/host-spoofing probes (OWASP audit F11) |
| 12 | Google sign-in degraded | Threshold | `['event-radar'] \| where event == "google_signin_degraded" \| summarize count()` over 15 min | count > 3 — sustained failures talking to Google (token exchange or JWKS fetch), not just an occasional blip |

**Priority if the free tier caps monitor count:** #2 (job failed), #3/#3b (dead
scheduler), #7 (silence) are the must-haves — they catch the real operational
failure modes. #1, #4, #5, #6, #9, #10, #11 are next. #8 is a nice-to-have.

### Why #3/#3b/#7 matter most

Render's free tier sleeps after 15 min idle, which halts the embedded
APScheduler. When that happens **nothing errors** — jobs simply never run, so an
error-only monitor stays silent. #3/#3b detect the *absence* of a successful
`job_run` in the window the job should have run; #7 detects the whole stream
going quiet (app down **or** shipping broken).

## Residual risks

- **Axiom can't alert on its own silence.** #7 only fires if Axiom is still
  ingesting and evaluating. If Axiom ingest or the monitor engine is down,
  nothing fires. An external uptime check (e.g. a second cron-job.org job that
  alerts on a failed `GET /health`) would close this gap — not set up (declined
  for now), documented here as the one uncovered case.
- **Free-tier limits.** Monitor count and evaluation frequency may be capped on
  the Axiom plan in use — use the priority order above if so.

## Verification

- **Field emission (local):** run the backend with `APP_ENV=production` and
  `LOG_SHIP_URL` pointed at a [webhook.site](https://webhook.site) bin (+ any
  `LOG_SHIP_TOKEN`), then `POST /admin/build-feeds`. Confirm the shipped JSON
  carries `event`, `job`, `status`, `duration_ms`. Hammer a rate-limited route
  and confirm an `event="rate_limit_block"` line ships.
- **Axiom:** confirm the new fields appear as columns on the dataset; run each
  monitor's APL as a query and check it returns the expected rows.
- **Monitor #2:** create it + the email notifier, force one job error, confirm
  the email arrives. Create #3 with a short test window to confirm the *below*
  path fires, then set the real 25h window.
