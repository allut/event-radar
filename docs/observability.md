# Observability & Monitoring (Axiom)

What's in here: the Axiom logging/monitoring spec — log shipping, dashboards, alerts, the fields every structured log line carries, and the log-triage recipe.

Version-controlled spec for the Axiom monitors that watch the production log
stream. The backend ships prod logs to Axiom (`app/logging_config.py` →
`HttpLogShipHandler`); this file defines what to alert on.

Monitors are created
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
| `job` / `status` / `duration_ms` | on `event="job_run"` | per scheduled-job telemetry; successful runs of `flush_promotion_counters` and `sweep_promotions` (per-minute, `LOG_SHIP_SUPPRESS_OK_JOBS`) are not shipped, their errors are |
| `path` | on `event="rate_limit_block"` | request path that was throttled |

`event` values (defined in `app/constants/log_events.py`, `LOG_EVENT_*`):

| `event` | Meaning | Emitted from |
|---|---|---|
| `job_run` | scheduled job completed/failed (carries `job`, `status`, `duration_ms`) | `app/main.py::_scheduled` |
| `rate_limit_block` | own per-IP 429 rejection (carries `path`) | `app/rate_limit.py` |
| `llm_degraded` | LLM provider chain exhausted, or classify/dedup backlog deferred | `app/llm/router.py`, `app/ingestion/jobs.py` |
| `auth_failed` | magic-link / admin-console login / claim-intent-link auth rejected | `app/routers/auth.py`, `organizer_auth.py`, `organizer_claims.py`, `app/auth/admin_lockout.py` |
| `webhook_rejected` | inbound-mail bad signature / bad body | `app/routers/webhooks.py` |
| `report_submitted` | `POST /reports` succeeded | `app/routers/reports.py` |
| `email_send_failed` | a Resend send failed (magic link, digest, contact, report notify/reporter, claim resolution, cancellation, Promotion notices) | `app/email/resend.py::send_resend_email` (every request-path send), `app/email/digest.py`, `app/claims/lifecycle.py`, `app/events/cancellation.py`, `app/promotions/sweep.py`, `app/routers/admin.py`, `app/routers/admin_claims.py`, `app/routers/organizer_promotions.py`, `app/routers/stripe_webhook.py` |
| `admin_action` | console-initiated or system Promotion action — audit trail; carries `action`, one of the `ADMIN_ACTION_*` values (`app/constants/admin.py`) | `app/routers/admin_auth.py`, `app/routers/utils.py`, `app/promotions/audit.py` |
| `contact_honeypot_block` | contact-form honeypot field tripped (bot signal) | `app/routers/contact.py` |
| `host_rejected` | `HostCheckMiddleware` rejected a request's Host header — signals cache-poisoning/host-spoofing probes | `app/main.py` |
| `unverified_account_budget_exceeded` | global daily new-unverified-account budget crossed (mail-bomb early warning, OWASP audit F10) | `app/routers/utils.py::record_unverified_account_creation` |
| `explore_ceiling_overflow` | `GET /explore` candidate query returned more than `BROWSE_RELEVANCE_CEILING` rows, so only the soonest were ranked (carries `ceiling`) | `app/routers/browse.py` |
| `google_signin` | Google sign-in completed on either track (carries `track` — `user`/`organizer` — and `outcome`, e.g. `existing_login`/`new_account`/`auto_linked`/`confirmation_sent`) | `app/routers/auth.py`, `app/routers/organizer_auth.py` (the two Google callbacks) |
| `google_signin_degraded` | network/5xx failure talking to Google (token exchange or JWKS fetch) — upstream degradation, distinct from a rejected caller | `app/routers/auth.py`, `app/routers/organizer_auth.py`, `app/auth/google_oauth.py` |
| `identity_linked` | a provider identity row was created (new account, auto-link, or confirmation-link absorption) | `app/routers/auth.py`, `app/routers/organizer_auth.py` |
| `identity_unlinked` | `DELETE /users/me/identities/{provider}` or `DELETE /organizer/profile/identities/{provider}` succeeded | `app/routers/settings.py`, `app/routers/organizer_profile.py::unlink_own_identity` |
| `schema_drift` | boot-time alembic revision ≠ migration head (carries `db_revision`, `head_revision`) — raises in production, warns in development | `app/db.py::assert_schema_at_head` |

## Log triage

A sweep of the production stream for bugs, such as a weekly check. Run the four queries below over the window. Search existing issues (`docs/agents/issue-tracker.md`) before filing one.

### Query gotchas

- **The dataset is `event-radar-logs`.** The monitor APL below uses the same name.
- **`_time` is the batch-flush time, not the record time.** `HttpLogShipHandler` ships in batches, so a batch's lines share one timestamp to within microseconds. Within a batch, order is still emission order.
- **`ts` is a string in Axiom.** Aggregate and bin on `_time`; `min(ts)` fails with a type error.
- **APL has no `any()` or `take_any()`.** Use `arg_max(_time, msg)` for a sample line per group.
- **Write a regex containing a quote as a normal string.** A verbatim `@"…"` string ends at its first `"`, so `@"\" ([0-9]{3})"` fails to parse.

### Queries

1. **Warning and error templates.** Digits collapse to `N`, so per-page and per-ID lines group into one row.
   ```
   ['event-radar-logs'] | where level in ("WARNING", "ERROR")
   | extend tmpl = replace_regex(@"[0-9]+", "N", substring(msg, 0, 100))
   | summarize n = count(), last = max(_time) by level, logger, tmpl | order by n desc
   ```
2. **Job cadence.** Compare runs per UTC day against `docs/backend-ops.md` "Scheduled Jobs". A doubled or missing run is the bug signal, and an all-`ok` status hides it.
   ```
   ['event-radar-logs'] | where event == "job_run"
   | summarize runs = count(), failed = countif(status != "ok"), max_ms = max(duration_ms) by job, day = bin(_time, 1d)
   ```
3. **HTTP errors.** Look at 5xx first. 404s on `/events/<id>` and scanner paths like `/.env` are noise.
   ```
   ['event-radar-logs'] | where logger == "uvicorn.access"
   | extend status = toint(extract("\" ([0-9]{3})", 1, msg)) | where status >= 400
   | summarize n = count() by status, path = extract("[A-Z]+ ([^ ?]+)", 1, msg) | order by status desc, n desc
   ```
4. **Anomaly tags.** Every `event` value except `job_run`, with its latest line.
   ```
   ['event-radar-logs'] | where isnotempty(event) and event != "job_run"
   | summarize n = count(), arg_max(_time, msg) by event | order by n desc
   ```

### LLM call stats

- **`backend/scripts/llm_calls_stats.py [--days N]` prints prod `llm_calls` stats.** It reads the read-only Neon role URL from `LLM_STATS_DATABASE_URL` (devcontainer env or the gitignored `backend/.env`), and prints `completion_tokens` and `prompt_tokens` p50/p95/max per provider and task on successful rows, the five busiest minutes per provider (calls and total tokens, for sizing against a per-minute provider limit), and `failure_reason` counts per provider.
- **`failure_reason` first shipped on 2026-10-25.** Earlier rate-limited attempts are not in it.
- **The log-side source is the `event-radar-logs` dataset.** The `llm response truncated` WARNING logs `completion_tokens`, but only for truncated calls; success-row token counts come from the script.

## Setup

1. **Notifier** — Axiom → Monitors → Notifiers → **New → Email**, name
   `event-radar-email`, recipient = your address. Every monitor below attaches
   this one notifier.
2. **Dataset** — `event-radar-logs`, the dataset named in `LOG_SHIP_URL`
   (`.../v1/datasets/<dataset>/ingest`). The APL below uses it.
3. Create each monitor from the table, pasting its APL and setting
   type/threshold/window/frequency.

## Monitors

APL is illustrative — adjust field names to what the live stream shows, and tune
thresholds after observing a few days of baseline volume.

| # | Monitor | Type | APL / condition | Alert when |
|---|---|---|---|---|
| 1 | Error spike | Threshold | `['event-radar-logs'] \| where level == "ERROR" \| summarize count()` | count > 5 in 5 min |
| 2 | Scheduled job failed | Match | `['event-radar-logs'] \| where event == "job_run" and status == "error"` | any match (msg carries `job` + `exc`) |
| 3 | Dead scheduler / stale feed ⭐ | Threshold (below) | `['event-radar-logs'] \| where event == "job_run" and job == "build_daily_feeds" and status == "ok" \| summarize count()` over 25h | count < 1 |
| 3b | Stale ingest ⭐ | Threshold (below) | as #3, `job == "hourly ingest"`, window 120 min | count < 1 |
| 3c | Digest not sent | Threshold (below) | as #3, `job == "send_daily_digests"`, window 25h | count < 1 |
| 4 | LLM degradation | Threshold | `['event-radar-logs'] \| where event == "llm_degraded" \| summarize count()` over 30 min | count > 3 |
| 5 | Auth / abuse spike | Threshold | `['event-radar-logs'] \| where event in ("auth_failed", "rate_limit_block") \| summarize count()` over 10 min | count > 20 |
| 6 | Webhook probing | Threshold | `['event-radar-logs'] \| where event == "webhook_rejected" \| summarize count()` over 15 min | count > 5 |
| 7 | Log-stream silence | Threshold (below) | `['event-radar-logs'] \| summarize count()` over 30 min | count < 1 |
| 8 | Job-duration anomaly *(optional)* | AnomalyDetection | `['event-radar-logs'] \| where event == "job_run" \| summarize avg(duration_ms) by job, bin_auto(_time)` | auto-baselined drift |
| 9 | Report abuse spike | Threshold | `['event-radar-logs'] \| where event == "report_submitted" \| summarize count()` over 10 min | placeholder — tune after baseline volume observed |
| 10 | Admin action audit ⭐ | Match | `['event-radar-logs'] \| where event == "admin_action"` | any match — the audit trail (`ADMIN_ACTION_*` values) exists but had no monitor watching it (OWASP audit F11); this makes every console-initiated admin action visible, not alert-worthy on its own |
| 11 | Host-header probing | Threshold | `['event-radar-logs'] \| where event == "host_rejected" \| summarize count()` over 15 min | count > 5 — signals cache-poisoning/host-spoofing probes (OWASP audit F11) |
| 12 | Google sign-in degraded | Threshold | `['event-radar-logs'] \| where event == "google_signin_degraded" \| summarize count()` over 15 min | count > 3 — sustained failures talking to Google (token exchange or JWKS fetch), not just an occasional blip |

**Priority if the free tier caps monitor count:** #2 (job failed), #3/#3b (dead
scheduler), #7 (silence) are the must-haves — they catch the real operational
failure modes. #1, #4, #5, #6, #9, #10, #11 are next. #8 is a nice-to-have.

### Why #3/#3b/#7 matter most

The embedded APScheduler lives inside the single web process. The backend now
runs on Render's always-on Starter plan (the old free tier's 15-min idle sleep
no longer applies — see `docs/backend-ops.md`), but a scheduler can still die
quietly: a wedged event loop, a process restarted without the scheduler
starting, or a job that hangs instead of failing.

When that happens **nothing
errors** — jobs simply never run, so an error-only monitor stays silent. #3/#3b detect the *absence* of a successful
`job_run` in the window the job should have run; #7 detects the whole stream
going quiet (app down **or** shipping broken).

## Residual risks

- **Axiom can't alert on its own silence.** #7 only fires if Axiom is still
  ingesting and evaluating. If Axiom ingest or the monitor engine is down,
  nothing fires.
- **An external uptime check would close that gap.** For example, a second
  cron-job.org job that alerts on a failed `GET /health`. It's not set up
  (declined for now), so this is the one uncovered case.
- **Free-tier limits.** Monitor count and evaluation frequency may be capped on
  the Axiom plan in use — use the priority order above if so.

## Verification

- **Field emission (local):** run the backend with `APP_ENV=production` and
  `LOG_SHIP_URL` pointed at a [webhook.site](https://webhook.site) bin (+ any
  `LOG_SHIP_TOKEN`) and `ENABLE_SCHEDULER` on, then let a scheduled job fire
  (hourly ingest is the shortest wait). Confirm the shipped JSON carries
  `event`, `job`, `status`, `duration_ms`.
- **Only `_scheduled` jobs emit `job_run`.** An admin-console trigger
  (`POST /admin/build-feeds`) emits `admin_action` instead.
- **Rate-limit events:** hammer a rate-limited route and confirm an
  `event="rate_limit_block"` line ships.
- **Axiom:** confirm the new fields appear as columns on the dataset; run each
  monitor's APL as a query and check it returns the expected rows.
- **Monitor #2:** create it + the email notifier, force one job error, confirm
  the email arrives. Create #3 with a short test window to confirm the *below*
  path fires, then set the real 25h window.
