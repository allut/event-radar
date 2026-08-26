# How long may one HTTP response take, per hop, browser → FastAPI?

**Date:** 2026-08-23
**Ticket:** https://github.com/allut/event-radar/issues/137 (research task)
**Downstream decision:** issue #141 (admin console request shape) — this file supplies facts, not the decision.

> **Superseded note:** this file is a dated snapshot. Issue #159 (landed 2026-08-25/26, after this research) implemented NDJSON streaming for every `/admin/*` job-trigger endpoint — see `docs/backend-ops.md`'s Admin Endpoints section. Where this doc says streaming is unimplemented, that was true only as of 2026-08-23.

All claims below are cited to first-party sources: Vercel's own docs/changelog/error reference (vercel.com/docs, vercel.com/changelog), Render's own docs and changelog (render.com/docs, render.com/changelog), the WHATWG Fetch Standard and MDN, Mozilla's Bugzilla for the one browser-level timeout that exists, and — for the last hop — the uvicorn 0.46.0 source actually installed in this repo. Where a claim comes from a first-party *comparison* page rather than a reference page, that is stated explicitly. Where the docs are silent, this file says so and marks the gap **NEEDS DEVELOPER INPUT** with the exact test that would settle it, rather than guessing a number.

**The concrete subject.** `POST /admin/pipeline/run` (`backend/app/routers/admin.py`) runs seven stages in sequence — `sync_organizers`, `ingest` (four sources), `dedup`, `classify` (LLM drain), `publish`, `build_feeds`, `send_digests` — inside a single `await` before returning one JSON body. `run_admin_job()` (`backend/app/routers/utils.py`) likewise awaits its coroutine inline. Nothing is emitted to the client until the whole thing finishes, so **time-to-first-byte equals total job duration** for every `/admin/*` endpoint. That fact is what makes the idle-vs-total distinction below load-bearing.

**The hops.** browser → Vercel Edge (`whatsonradar.com`) → Vercel's external-rewrite proxy (`frontend/vercel.json`, `/api/:path*` → `https://event-radar-api.onrender.com/:path*`) → Render's load balancer → uvicorn 0.46.0 → FastAPI handler.

---

## 1. Vercel — the external-rewrite proxy hop

### 1.1 The governing limit is "Proxied Request Timeout" = 120 seconds, and it is the same on every plan

Source: https://vercel.com/docs/limits — section **"Proxied request timeout"**, verbatim:

> The amount of time (in seconds) that a proxied request (`rewrites` or `routes` with an external destination) is allowed to process an HTTP request. The maximum timeout is **120 seconds** (2 minutes).
> If the external server does not reply until the maximum timeout is reached, an error with the message `ROUTER_EXTERNAL_TARGET_ERROR` will be returned.

The same page's plan-comparison table lists `Proxied Request Timeout (Seconds)` as **120 / 120 / 120** for Hobby / Pro / Enterprise. **There is no plan difference.** Being on the free/Hobby tier costs nothing here — upgrading to Pro would not buy a single extra second on this hop.

### 1.2 Vercel Function `maxDuration` does NOT apply — stated explicitly, as the ticket asks

`frontend/vercel.json`'s `/api/:path*` rule is a **rewrite to an external origin**. Vercel's own rewrites doc classifies it that way and describes the mechanism as pure proxying, with no function in the path:

> An external origin is any API or website outside your Vercel project. Rewrites to external origins forward requests to these destinations, effectively allowing Vercel to function as a reverse proxy or standalone CDN.
> — https://vercel.com/docs/routing/rewrites

No Vercel Function is invoked, so the function-duration table on https://vercel.com/docs/limits (Hobby default 10s / max 60s; Pro 15s / 300s; Enterprise 15s / 900s) is **not the governing number for `/api/*` traffic in this project**. The two limits live in different sections of the same page and are not interchangeable.

Two of this repo's paths *are* real Vercel Functions and *do* fall under `maxDuration`: `frontend/api/seo-audit.ts` and `frontend/api/prerender-cadence.ts`, which `vercel.json`'s negative lookahead deliberately excludes from the rewrite (see `docs/backend-ops.md`). Nothing in the planned admin console touches those, but the distinction is worth keeping straight when reading Vercel docs about "timeouts".

### 1.3 It is an IDLE (read) timeout, not a total-duration cap — this is the single most important finding

Source: Vercel changelog, **"CDN origin timeout increased to two minutes"**, published 8 May 2025, authors Casey Gowrie and Joe Haddad — https://vercel.com/changelog/cdn-origin-timeout-increased-to-two-minutes

The entry raises the proxied-request timeout from 30s to 120s, "on all plans at no additional cost", and states the semantics verbatim:

> [The CDN now allows] up to 120 seconds for your backend to start sending data.
>
> After the initial byte is received, your backend can take longer than two minutes to complete the request, as long as it continues sending data at least once every 120 seconds.

So the 120 seconds decomposes into two separate budgets:

| Budget | Ceiling | Applies to |
|---|---|---|
| Time to first byte | 120 s | From Vercel opening the origin connection until the first response byte arrives |
| Inter-byte gap thereafter | 120 s per gap | Every subsequent quiet interval on the response stream |
| Total response duration | **no documented cap** | — |

This directly answers the escape-hatch question (§4) for the Vercel hop: **chunked/SSE keep-alive bytes reset the clock, and Vercel documents that they do.** Note that the wording on the reference page ("allowed to process an HTTP request") reads like a total-duration cap in isolation; the changelog is the more specific and more recent statement of the same limit, and it is the one that describes the actual mechanism. Where the two could be read as conflicting, this file treats the changelog as authoritative and flags the residual doubt in §6.

### 1.4 Which error code an external-rewrite timeout actually produces

- **`ROUTER_EXTERNAL_TARGET_ERROR` — HTTP 502 Bad Gateway.** https://vercel.com/docs/errors/ROUTER_EXTERNAL_TARGET_ERROR: *"The `ROUTER_EXTERNAL_TARGET_ERROR` error occurs when there is an error while routing to an external target"*, with causes including *"an erroneous response from the external target"*, and explicitly: *"If the external server does not respond within the maximum timeout of 120 seconds, you will see this error."* This is the one the setup in `frontend/vercel.json` will produce.
- **`FUNCTION_INVOCATION_TIMEOUT` — HTTP 504 Gateway Timeout.** https://vercel.com/docs/errors/FUNCTION_INVOCATION_TIMEOUT: *"occurs when a function invocation takes longer than the allowed execution time"*. This is the gateway-timeout-family code most Vercel timeout writing is about, and it is **not** the one an external-rewrite timeout produces, because no function is invoked.

There is a genuine inconsistency between Vercel's own pages here: the 2025 changelog says the change *"reduces the chance of 504 gateway timeouts"*, while the error reference assigns the external-target failure a **502**. Both are first-party. Resolving it matters only for how the console's error handling branches on status code — see the empirical test in §6.

**Shape of what the client receives.** Vercel serves its error codes as a platform error page (HTML), not as JSON from the backend. A console built on `frontend/src/api/client.ts` will therefore get a non-JSON body on a proxy timeout — a `response.json()` parse failure, not a clean typed API error. Design for that explicitly.

### 1.5 One adjacent change worth knowing (not a timeout, but it now applies by default)

Since 6 April 2026, external rewrites honor upstream `cache-control` / `CDN-Cache-Control` / `Vercel-CDN-Cache-Control` headers **by default** for newly created projects, or where the dashboard setting is enabled (https://vercel.com/docs/routing/rewrites, "Caching rewrites to external origins"). `POST` requests are not affected, but a **`GET /admin/jobs/{id}` poll endpoint could be CDN-cached** if the backend ever emits a permissive `cache-control`. Whether this project's Vercel project has the new default or the legacy uncached behaviour depends on its creation date and dashboard setting — flagged in §6. Setting `Cache-Control: no-store` on any admin/status endpoint makes the question moot, and is the cheap defensive move.

---

## 2. Render — the backend hop

### 2.1 Documented ceiling: 100 minutes per HTTP response

Render does **not** state a request timeout on its Web Services reference page (https://render.com/docs/web-services) or on any limits page I could find. The only first-party statements of a number are on Render's own comparison docs:

- https://render.com/docs/render-vs-vercel-comparison — *"Render web services allow HTTP responses to take up to 100 minutes."*
- https://render.com/docs/render-vs-heroku-comparison — *"Render allows responses to take up to 100 minutes for HTTP requests"*, contrasted with *"Heroku has a hard response timeout of 30 seconds that can't be configured or changed."*

Two independent Render-authored pages agree on 100 minutes. **Nothing in Render's docs makes this figure plan-dependent** — no separate free-tier number is published, and the free-tier doc (https://render.com/docs/free) does not mention request timeouts at all. Inference, clearly labelled: the 100-minute figure applies to free instances too, because Render publishes it as a platform property rather than a paid-plan feature. Not proven.

At 100 minutes vs Vercel's 120 seconds, **Render is not the binding constraint on this path by roughly a factor of 50.** Anything the console can do about timeouts, it does about the Vercel hop.

### 2.2 Idle vs total on the Render hop — undocumented

Render's wording is *"allow HTTP responses to take up to 100 minutes"*, which reads as a total-duration cap rather than an idle timeout. Render publishes no read-timeout, idle-timeout or inter-byte figure for HTTP, and no statement about whether its load balancer buffers streaming responses. The nearest adjacent first-party statement is for WebSockets (https://render.com/docs/websocket): *"Render does not enforce a maximum duration for WebSocket connections"*, plus a recommendation that *"your web service and its connected clients should periodically send each other keepalive messages"*. That is a different protocol and cannot be transferred to HTTP responses without testing. Flagged in §6.

### 2.3 Free-tier spin-down and whether an in-flight request holds it open

https://render.com/docs/free, verbatim:

> Render **spins down** a Free web service that goes 15 minutes without receiving any inbound traffic.
>
> A Free web service spins back *up* whenever it next receives an HTTP request or new WebSocket connection. This process takes about one minute. Render displays a loading page to connecting browsers while a service is spinning up.

Render's changelog of 24 February 2026 (https://render.com/changelog/free-web-services-now-remain-active-while-receiving-websocket-messages) sharpens what "inbound traffic" means:

> Free web services now spin down after going 15 minutes without receiving *either* of the following: An incoming HTTP request or an incoming WebSocket message from an existing connection.

Read literally, the clock is reset by **incoming** traffic — a request arriving, or a WebSocket frame arriving. A single long-running request delivers exactly one incoming event, at t=0; the outbound response bytes that follow are not "incoming". Whether Render's spin-down logic actually treats an open in-flight request as keeping the instance active is **not documented either way**. Flagged in §6.

**In practice this project is already insulated from it.** A cron-job.org job pings `https://event-radar-api.onrender.com/internal/tick` every 10 minutes to keep APScheduler alive (`docs/backend-ops.md`), which resets the 15-minute idle clock independently of any admin request. The theoretical risk only materialises if that keepalive is ever removed.

**The spin-up case is the sharper hazard for a console.** If the instance *is* asleep when the console fires, spin-up takes *"about one minute"* — a minute consumed straight out of Vercel's 120-second time-to-first-byte budget before the pipeline has executed a single stage. And the doc's *"Render displays a loading page to connecting browsers while a service is spinning up"* raises an unanswered question for a proxied API `POST`: whether that path receives the JSON it expects or an HTML interstitial. Flagged in §6.

### 2.4 No gunicorn/uvicorn worker timeout is in play

`render.yaml`'s `startCommand` is `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT` — plain uvicorn, no gunicorn. This matters because gunicorn's default 30-second worker timeout would otherwise be the tightest ceiling on the whole chain, and it would kill the worker rather than merely the request. It is not present.

uvicorn 0.46.0 (`backend/requirements.txt`, `uvicorn[standard]==0.46.0`) exposes **no response-duration timeout at all**. `uvicorn --help` lists only `--timeout-keep-alive` (*"Close Keep-Alive connections if no new data is received within this timeout"* — the idle gap **between** requests on a pooled connection, not a cap on one response), `--timeout-graceful-shutdown`, `--timeout-worker-healthcheck`, and `--ws-ping-timeout`. **The application server imposes no ceiling on how long a handler may run.**

---

## 3. Browser / `fetch()`

### 3.1 The Fetch Standard defines no timeout — confirmed

The WHATWG Fetch Standard (https://fetch.spec.whatwg.org/) contains no timeout concept: there is no timeout member on `RequestInit` and no default time limit on a fetch. MDN's `fetch()` reference (https://developer.mozilla.org/en-US/docs/Web/API/Window/fetch) likewise documents no default timeout; the only abort mechanism it lists is `AbortController`/`AbortSignal`, with `AbortError` as the resulting exception.

The sanctioned way to impose one is `AbortSignal.timeout()` (https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static):

```js
const res = await fetch(url, { signal: AbortSignal.timeout(5000) });
```

which rejects with a `TimeoutError` `DOMException`. **Practical consequence: if the console does nothing, a hung admin request hangs forever from the JS side — the browser will not rescue the UI.** Any client-side ceiling has to be written deliberately, and should be set *above* whatever the proxy allows so the proxy's error surfaces first and is diagnosable.

### 3.2 Per-browser network timeouts that do apply

- **Firefox** has a pref `network.http.response.timeout`, introduced in Firefox 29 via https://bugzilla.mozilla.org/show_bug.cgi?id=947391 with a default of **300 seconds**. Two qualifications from Mozilla's own bug record: the bug's title is *"HTTP connections (exc. XHR, SPDY) should have a response timeout"* — i.e. **XHR is excluded by design**; and https://bugzilla.mozilla.org/show_bug.cgi?id=1024015 (resolved FIXED in Firefox 33, uplifted to 31/32) made the response timeout and TCP keep-alive **mutually exclusive, with keep-alive preferred**, precisely because the timeout *"breaks applications with long lived http connections"*. Whether the exclusion that covers XHR also covers `fetch()` in current Firefox is an inference from the shared networking path, not something Mozilla states; treat 300 s as a plausible Firefox-only ceiling worth testing rather than a certainty.
- **Chrome/Chromium**: no per-request HTTP response timeout is documented in any Chromium first-party source I could locate. Absence of documentation is not proof of absence. Since the Vercel hop caps things at 120 s of silence anyway, this is academic unless the streaming option in §4 is chosen — at which point it becomes worth a real-browser test (§6).

---

## 4. The escape hatch: does streaming reset the clock?

| Hop | Idle or total? | Does periodic output help? | Basis |
|---|---|---|---|
| **Vercel external rewrite** | **Idle** — 120 s to first byte, then 120 s max per inter-byte gap; no documented total cap | **Yes, documented.** Emitting any bytes at least every 120 s keeps the response alive indefinitely | Vercel changelog, 8 May 2025 (§1.3) |
| **Render web service** | Documented as a **total** cap of 100 minutes; no idle timeout published | **Unknown / probably irrelevant** — 100 min is ~50× the binding limit, so streaming is not needed to survive this hop | Render comparison docs (§2.1–2.2); gap flagged §6 |
| **uvicorn** | Neither — no response-duration timeout exists | N/A | uvicorn 0.46.0 CLI (§2.4) |
| **Browser `fetch()`** | Neither, per spec | N/A (Firefox's 300 s pref, if it applies, is a *response* timeout that streaming would also reset) | §3 |

**Conclusion for §4: yes, on the hop that actually binds.** Because Vercel's ceiling is an idle timeout and not a total-duration cap, a response that emits a byte at least every 120 seconds can run arbitrarily long through this exact topology. Nothing in this repo currently returns a `StreamingResponse` or `text/event-stream` — `grep` over `backend/app` and `frontend/src` finds no streaming responses at all, so this would be new machinery, not a config change.

Two caveats that keep this from being free:

1. **The 120-second TTFB budget still applies before the first chunk.** A streaming implementation must emit its first byte promptly — before any stage runs — not merely stream at the end. Flushing a stage-start line before each stage, and the first one immediately on entry, satisfies this.
2. **Whether Render's load balancer buffers a streaming HTTP response is undocumented** (§2.2). If it buffers to completion, every keep-alive byte is swallowed and the Vercel hop times out anyway. This is the single fact that decides whether option (c) works, and it is **not answerable from documentation** — see §6.

---

## 5. Failure semantics

### 5.1 What the client sees

Vercel returns **HTTP 502** with `ROUTER_EXTERNAL_TARGET_ERROR`, rendered as a Vercel platform error page (§1.4). Not a dropped connection, and not a 504 — though Vercel's own changelog language about "504 gateway timeouts" leaves room for doubt about which is emitted in practice (§6). Either way, the body is HTML from Vercel, not JSON from FastAPI, so the SPA's API client gets a parse failure rather than a structured error. Any `AbortSignal.timeout()` the console sets would instead surface a `TimeoutError` `DOMException` — a different code path, and one that fires only if the client ceiling is tighter than the proxy's.

### 5.2 The backend keeps running — verified against the installed uvicorn

**This is the finding that determines whether a timed-out click is harmless.** It is not harmless in the "nothing happened" sense; it is harmless in the "the job still completes, you just can't see it" sense.

The ASGI spec (https://asgi.readthedocs.io/en/latest/specs/www.html) makes disconnect *advisory*: `http.disconnect` is *"Sent to the application if receive is called after a response has been sent or after the HTTP connection has been closed"*, and *"Once you have received this event, you should expect future calls to `send()` to raise an exception."* The spec places the burden on the application to notice; it does **not** require the server to cancel the application coroutine.

uvicorn 0.46.0 — the version pinned in `backend/requirements.txt`, running the `httptools` implementation that `uvicorn[standard]` selects — implements exactly that advisory behaviour. In `uvicorn/protocols/http/httptools_impl.py`:

```python
def connection_lost(self, exc: Exception | None) -> None:
    self.connections.discard(self)
    ...
    if self.cycle and not self.cycle.response_complete:
        self.cycle.disconnected = True
    if self.cycle is not None:
        self.cycle.message_event.set()
```

and, in the ASGI `send` path:

```python
async def send(self, message: ASGISendEvent) -> None:
    if self.flow.write_paused and not self.disconnected:
        await self.flow.drain()
    if self.disconnected:
        return
```

A lost connection sets a flag and makes subsequent `send()` calls silent no-ops. **No task is cancelled.** Applied to `/admin/pipeline/run`:

- The seven stages run to completion (or to their first failure) exactly as if the client were still attached.
- Every commit those stages perform lands in Postgres. `dry_run` defaults to `True` for the digest stage; a run launched with `?dry_run=false` **will still send real email** after the proxy has given up.
- The `{ok, stages}` JSON is assembled and then discarded into a closed socket. The per-stage results — the only place the pipeline reports what it did — are lost to the caller. The `log.exception("pipeline: %s failed", stage_name)` lines still reach the Render logs and the Axiom drain (`docs/observability.md`), so the run is observable *there* but nowhere in the UI.
- Nothing in the codebase guards against re-entry. A user who sees a 502 and clicks again starts a **second concurrent full pipeline run** overlapping the first, on a single-process free instance. The `RATE_LIMIT_ADMIN` bucket (`10/minute`, shared across all `/admin/*` via `limiter.shared_limit(..., scope="admin")`) throttles clicking but does not prevent overlap.

So a timed-out click leaves a job that is **running, not half-done** — but with no way for the console to observe it, no idempotency guard, and a live risk of double-execution. That is a design constraint on issue #141 independent of which request shape is chosen.

---

## 6. NEEDS DEVELOPER INPUT — open questions and the exact test for each

1. **NEEDS DEVELOPER INPUT — does Render's LB buffer streaming HTTP responses?** This single fact decides whether option (c) below is viable. *Test:* add a temporary `StreamingResponse` endpoint that yields a line, sleeps 20 s, yields another, ×5, then `curl -N --no-buffer https://event-radar-api.onrender.com/<path>` (direct to Render) and `curl -N --no-buffer https://whatsonradar.com/api/<path>` (through the rewrite). Compare arrival timestamps. If lines arrive one-per-20-s on both, streaming works end to end; if either buffers to the end, it does not.
2. **NEEDS DEVELOPER INPUT — 502 or 504 on an external-rewrite timeout?** Vercel's error reference says 502 `ROUTER_EXTERNAL_TARGET_ERROR`; its changelog talks about reducing "504 gateway timeouts". *Test:* a temporary backend endpoint that sleeps 130 s, called through `https://whatsonradar.com/api/...`; record the status code, `x-vercel-error` header, and body. Also confirms the 120 s figure empirically for this project's actual configuration.
3. **NEEDS DEVELOPER INPUT — does an in-flight request keep a free Render instance from spinning down?** Not documented either way (§2.3). Low practical risk while the cron-job.org `/internal/tick` keepalive exists. *Test:* only meaningful if that keepalive is ever removed — pause it, let the service idle, then issue one request longer than 15 minutes and see whether it completes.
4. **NEEDS DEVELOPER INPUT — what a proxied `POST` receives while a free instance spins up.** Render's docs mention a loading page shown to *browsers*; behaviour for an API `POST` arriving through Vercel's proxy is unstated (§2.3). *Test:* let the service sleep (requires pausing the keepalive), then `POST` through the rewrite and capture the status/content-type/body.
5. **NEEDS DEVELOPER INPUT — does this Vercel project honor upstream `cache-control` on external rewrites?** Depends on project creation date (before/after 6 April 2026) and a dashboard setting neither of which is visible from the repo (§1.5). Only the repo owner can check it in the Vercel dashboard. Mitigation is unconditional: set `Cache-Control: no-store` on any admin status/poll endpoint regardless of the answer.
6. **NEEDS DEVELOPER INPUT (low priority) — Firefox's 300 s response timeout and any undocumented Chrome ceiling.** Relevant only if streaming (option c) is chosen and a keep-alive interval longer than a couple of minutes is contemplated. *Test:* run the §1 streaming endpoint in real Firefox and Chrome for >6 minutes and watch for a client-side abort.

Two limits that are **not** open questions and should not be re-litigated: Vercel's 120 s proxied-request timeout is plan-independent (§1.1), and Vercel Function `maxDuration` is irrelevant to `/api/*` here (§1.2).

---

## What this means for the console

The binding number is **120 seconds of silence on the Vercel hop**, and because every `/admin/*` handler emits its entire response only at the end, that 120 s is a **cap on total job duration** as the code stands today. Render (100 min) and uvicorn (no cap) have enormous headroom that the current response shape cannot reach.

**(a) Fire-and-wait with a spinner.** Viable *only* for admin jobs that reliably finish inside 120 s — comfortably true for `/admin/stats`, plausibly true for a single narrow stage, and not true for `/admin/pipeline/run`, which fans out across four ingestion sources plus an LLM classification drain plus a feed build plus a digest send. It also fails badly rather than gracefully: the user gets a 502 HTML error page (unparseable by `frontend/src/api/client.ts`), the pipeline keeps running invisibly, and a retry click launches a second concurrent run. Keep it for the demonstrably-short endpoints; it cannot carry the full pipeline.

**(b) Async job id + polling.** Every request is short, so no hop's ceiling is anywhere near engaged, and it is the only option that makes an in-flight run *observable* — which §5.2 shows is needed regardless of which option wins, because the job survives the client either way. Costs: somewhere to hold job state (a table, or an in-process dict — the backend is single-process so a dict works, but Render deploys, restarts and free-tier spin-downs erase it, and the ticket's own spin-down behaviour makes that a real event); a poll endpoint that must send `Cache-Control: no-store` (§1.5); and a poll interval respecting the shared `RATE_LIMIT_ADMIN` bucket of `10/minute` across **all** `/admin/*` routes, so ~10 s intervals, not 1 s. It does not depend on any undocumented behaviour.

**(c) Streaming / chunked keep-alive.** Vercel documents that this works on the hop that binds: first byte within 120 s, then a byte at least every 120 s, with no total cap (§1.3). Emitting a line per pipeline stage would both keep the connection alive and give the console live progress — a genuinely attractive fit for a seven-stage job. It is the cheapest fix *if* it works. But it rests on one undocumented fact — whether Render's load balancer buffers streaming responses (§6, item 1) — and if it buffers, the whole approach collapses to option (a)'s failure mode. It also inherits option (a)'s weaknesses at the edges: a dropped connection still loses the result, there is still no re-entry guard, and it adds the first streaming code path in the codebase (`grep` finds no `StreamingResponse` or `text/event-stream` anywhere today).

The decision hinges on the answer to §6 item 1, which costs one temporary endpoint and two `curl` invocations to obtain. (b) works today with no unknowns; (c) is cheaper and better UX if the buffering test comes back clean; (b) and (c) compose — stream progress while also recording job state — and only that combination survives both a proxy timeout and a closed browser tab.
