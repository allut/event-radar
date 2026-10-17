# Backend Operations

What's in here: Render and Cloudflare Pages deployment, secrets, the edge Functions and SPA headers, cron-job.org jobs, admin endpoints, scheduled jobs, CI, retention, logging and maintenance scripts.

## Deployment

Production runs on Render Frankfurt (backend) and Cloudflare Pages (frontend). Both build from the `release` branch.

### Render Backend

- **`render.yaml` defines a Starter-plan web service in Frankfurt**, with `rootDir: backend` and a `/health` health check.
- **`PYTHON_VERSION=3.12` is pinned to match CI and the devcontainer.** Render's unpinned default drifted to a newer Python that CI never runs.
- **Migrations run as `preDeployCommand: alembic upgrade head`**, before `startCommand` on every deploy.
- **There's no Render cron service and no keepalive ping.** Render cron jobs are paid, and Starter compute is always on, so nothing has to stop it idling. Timed backend work runs in the embedded scheduler; see Scheduled Jobs.

### Env Vars and Secrets

- **`render.yaml` lists every backend env var; each `sync: false` key is a dashboard secret.** `SECRET_KEY` is auto-generated.
- **`DATABASE_URL` takes the asyncpg form**, `postgresql+asyncpg://...?ssl=require`.
- **`BACKEND_URL` is a `value:` literal, not `sync: false`.** It's the service's own public URL (`https://event-radar-api-r7l6.onrender.com`), not a secret, so a blueprint sync sets it with no dashboard step. Leaving it unset once took production down.
- **`BACKEND_URL` feeds the digest's `List-Unsubscribe` header and `HostCheckMiddleware`'s allowlist.** Render injects `RENDER_EXTERNAL_HOSTNAME` as the allowlist's second, self-correcting source; it never appears in `render.yaml`. See [security.md](security.md)'s Host Check section.
- **Google sign-in needs `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET`, not `GOOGLE_CLIENT_*`.** `GOOGLE_SIGNIN_CONSUMER_ENABLED` and `GOOGLE_SIGNIN_ORGANIZER_ENABLED` default to `false`.
- **The `CLOUDINARY_*` trio backs organizer image upload.** See [organizer-portal.md](organizer-portal.md)'s Image Upload section.
- **`ADMIN_TOTP_SECRET` comes from `backend/scripts/admin_totp_enroll.py`.** See Maintenance Scripts.
- **`EDGE_SHARED_SECRET` must match the Cloudflare Pages Secret of the same name.** See API Proxy.

### Cloudflare Pages Frontend

- **`frontend/wrangler.toml` is the build config's source of truth**, as `render.yaml` is for the backend. Pages serves the static Vite build from `dist`.
- **Non-secret build vars live in `wrangler.toml`'s `[vars]`**: `NODE_VERSION`, the `VITE_GOOGLE_SIGNIN_*` flags and `PRERENDER_RENDER_BUDGET_MINUTES`.
- **Anything credential-shaped is a Pages Secret**, set in the dashboard or with `wrangler pages secret put`. `wrangler.toml` is checked in, so a secret never goes in `[vars]`.
- **`frontend/public/_routes.json` keeps static assets off the Functions path**, so serving them never invokes a Function.
- **Exact-path Functions win over the catch-all automatically.** `functions/api/seo-audit.ts` and `functions/api/prerender-cadence.ts` match ahead of `functions/api/[[path]].ts`, so there's no exclusion pattern to keep in sync.
- **Don't install `@cloudflare/workers-types`; extend the shim instead.** `frontend/functions/_shared/cloudflare.ts` hand-rolls `PagesFunction`, `EventContext` and a `jsonResponse` helper. The package would buy only two type names. The trade-off: `tsc` doesn't check a handler against the platform contract, so add a missing member to the shim by hand.

### API Proxy

`frontend/functions/api/[[path]].ts` forwards every `/api/*` request to Render. The browser sees one origin, so CORS never applies and the session cookie stays first-party (`docs/adr/0001`).

- **It strips the `/api` prefix and targets `BACKEND_ORIGIN` (`frontend/src/constants/api.ts`).** It drops the wire-encoding response headers (`content-encoding`, `content-length`, `transfer-encoding`, `connection`), which would describe bytes that no longer match the re-emitted body.
- **It asserts `backendUrl.origin === BACKEND_ORIGIN` before fetching.** `new URL(relative, base)` discards the base host for a protocol-relative path. Without the check, `/api//host/...` would send the visitor's cookie to an arbitrary host.
- **It rewrites the client-IP headers for the two-hop topology.** It strips inbound `X-Forwarded-For` and `X-Client-IP`, then sends `CF-Connecting-IP` with `X-Edge-Auth` when `EDGE_SHARED_SECRET` is set. See [security.md](security.md)'s Client Key section.
- **Without `EDGE_SHARED_SECRET`, every visitor shares a rate-limit bucket.** The backend falls back to the rightmost `X-Forwarded-For`, which is Cloudflare's egress address.

### SPA Fallback

- **`frontend/functions/[[path]].ts` tries `env.ASSETS.fetch()` on the real request first.** A prerendered route, a built `/assets/*` file or any other real `dist/` file wins. Only a genuine 404 falls through to `app-shell.html`.
- **That fetch-first order is load-bearing.** Pages' documented precedence, static asset before any Function, didn't hold in production. The catch-all served the app shell for every request, built JS and CSS included.
- **It requests the shell at its extensionless path.** `env.ASSETS.fetch()` applies Pages' `.html`-stripping redirect, which would otherwise hand the browser a visible 308.
- **`/explore?page=N` with N of 2 or more skips the fetch-first step.** It gets the shell straight away, because the prerendered page-1 snapshot would carry the wrong canonical. See [seo.md](seo.md)'s SPA Fallback Shell section.

### SPA Security Headers

`frontend/public/_headers` sets the app document's headers in Cloudflare's static-headers format. The build copies it into `dist/`. The backend's `default-src 'none'` CSP covers only JSON API responses.

- **The document gets `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Referrer-Policy`, HSTS, `Permissions-Policy` and a tailored CSP.**
- **The CSP is `default-src 'self'`, widened only where something needs it:**

| Directive | Sources | For |
|---|---|---|
| `img-src` | `'self' https: data:` | event images from arbitrary source hosts |
| `style-src` | `'self' 'unsafe-inline'` | React inline styles |
| `script-src` | `'self'`, one `sha256-…` hash | `index.html`'s pre-paint theme script |
| `connect-src` | `'self'` | the same-origin `/api/*` proxy |
| `font-src` | `'self'` | the `@fontsource` faces bundled in `src/main.tsx` |

- **Moving a resource off-origin breaks it silently unless the CSP widens to match.** A CDN font host is the likely case.
- **The hash and its drift guard are in [security.md](security.md)'s Frontend CSP section.**
- **The document block applies to `/*`, then un-sets each header on `/api/*` with the `!` prefix.** `_headers` has no negative lookahead. API responses carry only the backend's own `app/main.py::add_security_headers` headers.
- **`/api/seo-audit` and `/api/prerender-cadence` get their own locked-down block** (`default-src 'none'`, `Cache-Control: no-store`). Their own Functions answer them, so they never reach the backend proxy.

## External Cron Jobs

Two cron-job.org jobs POST to Pages Functions every 6 hours, offset so they don't fire together. This section holds the operator setup. The Functions' mechanics are in [seo.md](seo.md).

| Job | Endpoint | Header | Pages Secrets |
|---|---|---|---|
| Prerender cadence | `POST https://eventradar.ee/api/prerender-cadence` | `X-Prerender-Cadence-Token` | `PRERENDER_CADENCE_TOKEN`, `PRERENDER_CADENCE_DEPLOY_HOOK_URL`, `GH_PRERENDER_CHAIN_TOKEN` |
| Live audit | `POST https://eventradar.ee/api/seo-audit` | `X-Seo-Audit-Token` | `SEO_AUDIT_TOKEN`, `GH_ISSUE_TOKEN` |

- **Either endpoint returns 500 when its secrets are unset**, rather than silently doing nothing.
- **Each job has its own header name on purpose** (`PRERENDER_CADENCE_TOKEN_HEADER`, `SEO_AUDIT_TOKEN_HEADER`). If the Functions shared one, a refactor merging their handlers could forward a token to the backend under the wrong header.
- **Changing either header constant means updating that cron-job.org job's header too.**
- **Six hours mirrors the backend's LLM pass cadence (`LLM_PASS_INTERVAL_HOURS`).** That cadence is an interval from process boot, not a clock time, so the prerender job needs no particular offset from it.

### Prerender Cadence

The prerender cadence rebuilds production every 6 hours, so snapshots, `sitemap.xml` and `robots.txt` stay fresh. The chain mechanics are in [seo.md](seo.md)'s Round Chaining section.

1. **cron-job.org POSTs to `prerender-cadence.ts`, the gate.**
2. **The gate fires the Deploy Hook unless a chain round is in flight.** cron-job.org never sees the hook's URL.
3. **The Deploy Hook starts a production build.** It lives under the Pages project's Settings → Builds & deployments → Deploy Hooks, named `prerender-cadence`, on the production branch.
4. **A build that runs out of budget commits a round marker.** That push to the git-connected production branch starts the next round.

- **`GH_PRERENDER_CHAIN_TOKEN` is a GitHub PAT with `contents: write` on `allut/event-radar`.** The gate reads the tip commit with it, and the build reads and commits the marker. The repo is private, so an unauthenticated read 404s.
- **Without `GH_PRERENDER_CHAIN_TOKEN` or `CF_PAGES_BRANCH`, chaining is skipped, not failed.** The catalog then catches up only on the 6-hour cadence.
- **Delete any leftover `prerender-chain` Deploy Hook in the dashboard.** The marker push is the only continuation trigger. An older chain hook fired a second, redundant build of the same commit.

### R2 Chain-State Bucket

- **The bucket is `event-radar-prerender-chain-state`.** `CLOUDFLARE_ACCOUNT_ID` and `R2_BUCKET_NAME` sit in `wrangler.toml`'s `[vars]`. `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` are Pages Secrets.
- **Its lifecycle rule is dashboard config**: `chain-state-crash-backstop`, prefix `prerender-chain-state/`, expire after 3 days. Set it under R2 → bucket → Settings → Object lifecycle rules.
- **`CHAIN_STATE_LIFECYCLE_DAYS` only documents the rule's value.** Editing it doesn't move the rule, so change both together.
- **An R2 outage shows up as a slower burst, never a broken deploy.** Every R2 failure falls back to a full re-fetch; see [seo.md](seo.md)'s Chain-State Manifest (R2) section.

### Live Audit

- **The live-audit job catches a dead prerender cadence** by checking production directly, independent of any build. See [seo.md](seo.md)'s Live Audit section.
- **`GH_ISSUE_TOKEN` is a GitHub PAT with Issues: write on `allut/event-radar`.** The audit uses it to file, update and close the `seo-audit-failure` issue.

## Admin Endpoints

Operate the pipeline through the admin console at `/admin`, not curl. Its login, session, epoch claim and lockout are in [security.md](security.md)'s Admin Console Auth section.

- **Every `/admin/*` route takes only the console's session cookie** (`app/auth/dependencies.py::get_current_admin`). A script that needs a job or a PII view signs in through `POST /admin/auth/login` and reuses the cookie.
- **`/admin/pipeline` triggers every job with a live result stream.** It asks for confirmation before an expensive or destructive run, such as a digest send or a cleanup delete.
- **Every `/admin/*` route is rate-limited.** See [security.md](security.md)'s Rate Limiting section.

### Job Triggers

- **Most scheduled jobs have a `POST /admin/<job>` trigger that runs them outside the schedule.** Dedup and classify use the drain-now variant; see [pipeline.md](pipeline.md)'s Backlog Drain section.
- **`POST /admin/pipeline/run` runs the seven pipeline stages in dependency order.** Its digest stage defaults to `dry_run=true`.
- **`/admin/geocode`, `/admin/refetch` and `/admin/cleanup` run standalone**, outside `/admin/pipeline/run`. Run refetch before a manual geocode to re-resolve coordinates an address change nulled.
- **`POST /admin/cleanup` defaults to `dry_run=true`**, like every destructive admin or maintenance tool here. Pass `?dry_run=false` to delete.
- **Claim grant and decline send the claim-resolution email; revoke deletes the row and sends none.** See [organizer-portal.md](organizer-portal.md)'s Event Claiming section.

### Streaming

- **Job triggers stream NDJSON**, one envelope line per stage with `Cache-Control: no-store`. The `/admin/pipeline` console reads them live.
- **Add a single-stage trigger through `app/routers/utils.py::stream_admin_job()`.** A failure becomes a `status: "error"` line, not a 500, because the headers are already sent when a streamed job fails.
- **`app/routers/admin.py::admin_pipeline_run` hand-rolls its stage loop.** It needs stop-on-first-failure with a per-stage result dict, which the single-line envelope can't express.
- **Both paths run the job as its own `asyncio` task fed through a queue.** A client disconnect cancels the streaming generator, because Starlette races `listen_for_disconnect` against the body. A direct `await` would let that cancellation cut the job off mid-run.
- **`run_admin_job()` backs the non-streaming mutating actions**, such as report and submission resolution and takedown. It returns JSON, and a 500 on failure.

### Audit Logging

- **`app/routers/utils.py::log_admin_action()` adds an `AdminAction` row to the caller's own `db` session.** The row rides the mutation's transaction, so it's atomic, never a best-effort write.
- **It returns a closure that emits the Axiom `admin_action` log line.** Call it only after `await db.commit()` succeeds, so a rolled-back mutation never logs an action that didn't happen.
- **`stream_admin_job`'s `db=None` sites call the closure at once.** They have no transaction to wait for.
- **`app/db.py::assert_schema_at_head` runs first in the lifespan.** It stops a production boot when the DB isn't at the migration head, and only warns in development. The CI `migrations` job catches the same drift before merge; see CI.

### Pagination

- **Unbounded admin lists page with `limit`/`offset`**, capped by `ADMIN_*_PAGE_SIZE` and `ADMIN_*_MAX_PAGE_SIZE` in `app/constants/admin.py`. Give a new admin list endpoint the same pattern.
- **Pages count logical units, such as dedup groups, not rows**, so one noisy cluster can't fill a page.
- **A paged list returns `total`, `limit` and `offset` on every request**, beside its own item key such as `groups`. The numbered pager derives its last page and past-end clamp from `total`, so it can't be skipped past offset 0. `has_more` stays on the wire, but the client never reads it.
- **Every paged sort ends on a unique tie-breaker**, such as `GET /admin/submissions`' `created_at desc, id desc`. Without one, rows that share a sort value can repeat or vanish between offset pages.
- **`GET /admin/reports?report=<event_id>` locates a row** (the admin email deep link). It ignores `offset`, finds the row's position with one `ROW_NUMBER()` over the same four-key sort (`has_illegal desc, report_count desc, oldest asc, event_id`), and returns that page with its real `offset`. A row no longer in the queue gets page 1 and `report_not_found: true`.
- **Explore's relevance path caps its ranked pool at a ceiling and flags it with `total_is_lower_bound`.** The envelope rule, keyset removal and that ceiling are described in [pipeline.md](pipeline.md)'s Pagination section.
- **`PAGINATION_MAX_OFFSET` (5,000) is cross-stack**, in `shared/app-config.json`. A deeper offset gets a 422, or a clamp on `GET /organizer/events`. The frontend pager caps its last page at the same value, so it never links past it.

## Scheduled Jobs

APScheduler runs embedded in the FastAPI process (`app/main.py::_register_scheduled_jobs()`), on Europe/Tallinn time. The cadence constants live in `app/constants/jobs.py`.

| Cadence | Job |
|---|---|
| Hourly | `ingest_all_sources` (job id; the callable is `ingest_all_enabled`) |
| Every 6h | `dedup_pass`, `classify_pending`, `publish_pending`, `geocode_pending`, `backfill_publisher_ids` |
| Daily 04:30 | `refetch_event_details` |
| Daily 05:00 | `expire_stale_claims` |
| Daily 06:00 | `build_daily_feeds` |
| Daily 07:00 | `send_daily_digests` |
| Sun 03:00 | `sync_fienta_organizers` |
| Sun 03:30 | `cleanup_stale_data` |

- **The daily jobs run in a fixed order.** Refetch reconciles source detail pages, stale claims expire, then the feed build reads the result an hour before the digest sends it.
- **`backfill_publisher_ids` and `expire_stale_claims` are scheduler-only.** Neither has an admin trigger. The publisher backfill has a CLI instead (see Maintenance Scripts).
- **`ENABLE_SCHEDULER` turns the scheduler off in the devcontainer.** A `--reload` server left running overnight then can't arm live scrapes, LLM spend or digest email on a timer.
- **`app/main.py::_start_scheduler()` honours `ENABLE_SCHEDULER=false` only when `APP_ENV=development`.** The var is absent from `render.yaml`, so production always runs the scheduler.

## CI

- **`.github/workflows/tests.yml` runs on every push and PR to `master`.** It runs `pytest --cov` on Python 3.12, `npm run test:coverage` on Node 24, and a `migrations` job. The two test jobs run no Postgres, because backend tests mock the DB.
- **The `migrations` job round-trips the alembic chain against a `postgres:16` service.** It runs `upgrade head`, `downgrade base`, `upgrade head`, then `alembic check`, which fails when a model changed without a matching migration.
- **That job exists because of a prod incident.** Code shipped the `admin_actions` model and its migration, but the deployed DB never ran it, so every audited admin action returned 500.
- **Ruff, mypy, eslint and the TypeScript type-check don't run in CI.** Run them locally before committing. The dependency CVE audit is described in [security.md](security.md)'s Dependency Audit section.

## Data Retention & Cleanup

`app/cleanup.py::cleanup_stale_data()` runs weekly, Sunday 03:30, right after the organizer sync. It prunes aged rows with one bulk `DELETE` per table.

- **`events` rows are never deleted.** Only satellite data goes, which preserves event history and the `user_event_feedback` signal indefinitely.

| Table | Retention window (`app/constants/ops.py`) |
|---|---|
| `auth_magic_links` | `MAGIC_LINK_RETENTION_DAYS` (7), expired-unused and long-used rows |
| `organizer_magic_links` | `MAGIC_LINK_RETENTION_DAYS` (7), same rule |
| `llm_calls` | `LLM_CALLS_RETENTION_DAYS` (90) |
| `raw_events` | `RAW_EVENTS_RETENTION_DAYS` (90) |
| `ingestion_runs` | `INGESTION_RUNS_RETENTION_DAYS` (90) |
| `raw_inbound_emails` | `RAW_INBOUND_EMAILS_RETENTION_DAYS` (90) |
| `daily_feeds` | `DAILY_FEEDS_RETENTION_DAYS` (30) |
| `users`, unverified only | `UNVERIFIED_ACCOUNT_RETENTION_DAYS` (30) |
| `organizers`, unverified only | `UNVERIFIED_ACCOUNT_RETENTION_DAYS` (30) |

- **The `llm_calls` window is also the dedup and classification cache window.** A content hash re-seen after 90 days costs one fresh LLM call.
- **A forensic or backfill script can't recover a `raw_events` payload pruned past its window.**
- **An unverified user is pruned only with `email_verified = false` and no unused, unexpired magic link.** `POST /auth/request-link` creates the row before the address is proven. See [security.md](security.md)'s Email Verification Gate section.
- **An unverified organizer is pruned only with `email_verified_at IS NULL` and `verified = false`.** It must also have no unused, unexpired magic link, and no submitted event, linked identity, claim or venue.
- **Every organizer sign-in path stamps `email_verified_at`**: magic link, claim link and Google.
- **Magic-link rows never count as evidence for keeping an organizer.** The same job prunes them earlier in its run.

## Logging

`app/logging_config.py::configure_logging()` is the single logging entry point. `app/main.py` calls it at import time, after uvicorn configures its own logging, so it runs last and wins.

- **It re-points the framework loggers at the root logger.** `uvicorn`, `uvicorn.error`, `uvicorn.access` and `sqlalchemy.engine` lose their own handlers, so app, uvicorn and SQL lines share one timestamped format.
- **It's idempotent**, so it's safe under `--reload` and in tests.
- **Development logs readable text to the console and a rotating file under `backend/logs/`.** SQL echo logs at INFO.
- **Production (`APP_ENV != development`) logs JSON lines (`JsonLogFormatter`) to the console.** SQL echo drops to WARNING.
- **The logging literals live in `app/constants/ops.py` (`LOG_*`).** `LOG_LEVEL`, `LOG_SHIP_URL` and `LOG_SHIP_TOKEN` are settings in `app/config.py`.

### Log Shipping

- **With `LOG_SHIP_URL` set, logs also ship to an HTTP drain such as Axiom.** A `QueueHandler` feeds a background `QueueListener` thread, so the request path never blocks. Auth is `Bearer LOG_SHIP_TOKEN`.
- **`HttpLogShipHandler` batches.** It POSTs one JSON array per `LOG_SHIP_BATCH_SIZE` (100) records. A daemon timer flushes a partial buffer every `LOG_SHIP_FLUSH_INTERVAL_SECONDS` (2s), and `close()` flushes the rest.
- **The body is always a JSON array**, because Axiom's ingest endpoint expects an array of events. Other JSON drains accept it too.
- **Shipping never crashes the app.** `handleError` swallows network failures, and a failed batch is dropped, never retried. The lifespan calls `shutdown_log_shipping()` to stop the listener thread.
- **`_AccessPathStripFilter` strips the query string from every access-log path.** It sits on the `uvicorn.access` logger, so it runs before every handler, console included. That keeps OAuth codes, unsubscribe tokens and search terms out of logs.
- **`_AccessPathSuppressFilter` drops successful access lines for `LOG_SHIP_SUPPRESS_ACCESS_PATHS` (`/health`) before shipping.** The platform health probe would otherwise dominate the drain. Errors on those paths still ship.
- **[observability.md](observability.md) is the source of truth for the Axiom side**: the shipped record shape, the `LOG_EVENT_*` taxonomy and each monitor's APL query. Axiom's free tier has no monitors-as-code. Update it when a `LOG_EVENT_*` constant or shipped field changes.

## Maintenance Scripts

`backend/scripts/` holds one-off operational scripts, run by hand from `backend/` with the venv active. Each adds `backend/` to `sys.path`, so `from app.*` resolves from any working directory.

- **An `_`-prefixed filename is a machine-local throwaway.** `.gitignore` excludes `backend/scripts/_*`. Give a script a plain name only when it belongs in version control.

### reset_events.py

- **`reset_events.py` wipes all event and pipeline data and resets IDs to 1.** It runs `TRUNCATE ... RESTART IDENTITY CASCADE` over `events`, `raw_events`, `event_sources`, `event_classifications`, `user_event_feedback`, `daily_feeds`, `ingestion_runs`, `llm_calls` and `raw_inbound_emails`.
- **It then resets `sources.last_run_at` and `last_status` to `NULL`**, so ingestion re-fetches from scratch.
- **Users, organizers, personas, sources, publishers and claims are preserved.** Only the sources' run state is cleared.
- **`CASCADE` also empties `event_reports`**, and claim edits pinned onto the wiped events go with them.
- **It's a dry run by default**, printing the masked `DATABASE_URL` and per-table counts. `--yes` truncates, then warns on any table that isn't empty afterwards.
- **The truncate can't be undone.** It's for resetting a dev or staging DB or clearing bad ingested data, not routine use.

```bash
cd backend                              # venv active
python scripts/reset_events.py          # dry run: target DB + row counts
python scripts/reset_events.py --yes    # actually truncate (irreversible)
```

### Other Scripts

- **`admin_totp_enroll.py` enrolls the admin console's TOTP step locally.** It prints a fresh secret and a scannable QR code (`--account` sets the label). Set the secret as `ADMIN_TOTP_SECRET` in the Render dashboard.
- **There are no backup codes.** A lost authenticator means re-running the script and rotating `ADMIN_TOTP_SECRET`, which also ends every admin session.
- **`backfill_publisher_ids.py` runs `app/ingestion/publisher_backfill.py::backfill_publisher_ids()` once, now.** It stamps `event_sources.publisher_id` for claimable Fienta, KUMU and Estonia Concert Hall events; see [pipeline.md](pipeline.md)'s Organizer Lifecycle (Fienta) section.
- **The scheduler already runs the backfill every 6 hours**, so the script only forces it early. It's a dry run by default; `--yes` writes.
