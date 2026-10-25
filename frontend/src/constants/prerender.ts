// Prerender: readiness markers, the R2 render chain, cadence, concurrency and render budgets.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

// prerender.ts's per-page diagnostics ring buffer: max chars kept per
// console/pageerror line (attachPageDiagnostics) — long enough to be useful
// in a failure log, short enough to keep the buffer bounded.
export const PRERENDER_DIAGNOSTIC_EVENT_MAX_LENGTH = 300;

// Price marker EventDetail.tsx renders on the event-detail page, read back
// by seoValidation.ts's in-build staleness gate (issue #53) — price isn't
// part of the JSON-LD payload (issue #46 defers AggregateOffer), so it needs
// its own marker. One shared map so an attribute-name typo on either side
// can't silently break the gate.
export const EVENT_PRICE_TESTID = 'event-price';
export const EVENT_PRICE_SELECTOR = `[data-testid="${EVENT_PRICE_TESTID}"]`;
export const PRICE_DATA_ATTR = {
  min: 'data-price-min',
  max: 'data-price-max',
  currency: 'data-currency',
  hasFreeTier: 'data-has-free-tier',
} as const;
// Prerender readiness markers for /explore (issue #236) — same family as
// PRICE_DATA_ATTR above. `indexable` (useSeoMeta) only flips true on a
// successful query, which is what the canonical-link wait selector every
// other prerender target uses relies on — but /explore has a real error
// path (a query that fails outright), where Playwright must still stop
// waiting rather than time out. These two markers decouple "the page is
// done loading, snapshot it" (PRERENDER_READY) from "is it indexable"
// (still driven by useSeoMeta/indexable alone) and let the render script
// tell an error state apart from a genuine (possibly zero-row) success.
export const PRERENDER_READY_ATTR = 'data-prerender-ready';
export const PRERENDER_READY_SELECTOR = `[${PRERENDER_READY_ATTR}="true"]`;
export const PRERENDER_ERROR_ATTR = 'data-prerender-error';
export const PRERENDER_ERROR_SELECTOR = `[${PRERENDER_ERROR_ATTR}="true"]`;

// Window flag scripts/prerender.ts sets (addInitScript) before the app boots, so
// the app can tell the build-time render from a real visit. Explore reads it to
// never request a Sponsored slot a crawler snapshot would freeze (issue #603).
export const PRERENDER_RUNTIME_FLAG = '__EVENT_RADAR_PRERENDER__';

// dist-relative filename of the pristine (never overwritten by prerender)
// Vite build output — `npm run build` copies dist/index.html here *before*
// invoking prerender.ts (frontend/package.json's build script), so this is
// the one file on disk during the round that still carries the current
// build's real asset hashes. prerender.ts reads it to rewrite the stale
// asset refs a copied-forward snapshot would otherwise ship (issue #97).
export const APP_SHELL_FILENAME = 'app-shell.html';

// ─── Prerender chaining (issue #79/#81) ────────────────────────────────────
// Round-state marker embedded in the git commit message (the commit message
// has a 2048-byte cap) a chained round reads back on the next round/cron tick —
// see src/lib/prerenderChain.ts.
export const CHAIN_MARKER_PREFIX = 'prerender-chain:';
// RoundMarker.status values (src/lib/prerenderChain.ts's producer,
// scripts/prerender.ts's consumer) — mirrors UI_STATE's pattern so a typo on
// either side of the chaining state machine is a compile error, not a
// silently-missed compare.
export const ROUND_STATUS = {
  continuing: 'continuing',
  done: 'done',
} as const;
// Backend event/report status values compared against in the admin console —
// mirrors ROUND_STATUS/UI_STATE's pattern so a typo is a compile error.
export const EVENT_STATUS = {
  published: 'published',
} as const;
export const REPORT_STATUS = {
  open: 'open',
} as const;
// Worst-case ~100 minutes wall-clock at the 10-minute render budget per round,
// sized with margin against the throughput research's 5–7-round cold-catch-up
// estimate. Fixed, not dynamic — a pathological catalog can't chain forever.
export const CHAIN_MAX_ROUNDS = 10;
// A `continuing` marker older than this is treated as a crashed/abandoned
// chain rather than an active one, so cron resumes instead of skipping
// forever and a genuinely active chain isn't mistaken for a stale one.
export const CHAIN_STALENESS_TIMEOUT_MINUTES = 30;
// R2 key prefix (issue #366/#365) under which the prerender chain-state
// manifest lives — one burst's index + content objects sit at
// `${CHAIN_STATE_PREFIX}${sanitizedBurstId}/...`. Parallel optimization
// layer to the CHAIN_MARKER_PREFIX git-commit flow above, not a replacement
// — see docs/seo.md "Chain-State Manifest (R2)".
export const CHAIN_STATE_PREFIX = 'prerender-chain-state/';
// R2 bucket lifecycle rule expiring everything under CHAIN_STATE_PREFIX
// after this many days — a crash backstop, comfortably past
// CHAIN_STALENESS_TIMEOUT_MINUTES, for a burst whose explicit
// delete-on-`done` never ran (build crashed mid-burst). Mirrors
// isMarkerStale's existing crash-recovery posture. The lifecycle rule
// itself is bucket configuration, not application code — this constant
// documents the intended value for whoever configures it.
export const CHAIN_STATE_LIFECYCLE_DAYS = 3;
// Repo the round-state marker is committed to (issue #83) via the GitHub Git
// Data API — the branch the Cloudflare Pages Deploy Hook targets lives here.
// Same repo as SEO_AUDIT_GITHUB_REPO (both point at this codebase); kept as a
// separate constant since the two features are unrelated and may diverge.
export const PRERENDER_CHAIN_GITHUB_REPO = 'allut/event-radar';
// Production, git-connected branch the round-state marker is pushed to and
// the cadence gate (issue #92, functions/api/prerender-cadence.ts) reads its
// tip commit from.
export const PRERENDER_CADENCE_GIT_BRANCH = 'release';
// Shared-secret header cron-job.org sends on its prerender-cadence ping
// (issue #92). Distinct name from SEO_AUDIT_TOKEN_HEADER and the backend's own
// X-Internal-Token — see that constant's comment for why a shared name is a
// cross-service secret-disclosure risk.
export const PRERENDER_CADENCE_TOKEN_HEADER = 'x-prerender-cadence-token';

// GitHub API User-Agent for api/prerender-cadence.ts's githubRequest() call
// (GitHub rejects requests with no User-Agent).
export const PRERENDER_CADENCE_USER_AGENT = 'event-radar-prerender-cadence';

// Same, for scripts/prerender.ts's githubRequest() call.
export const PRERENDER_CHAIN_USER_AGENT = 'event-radar-prerender-chain';

// ─── Prerender (scripts/prerender.ts) ────────────────────────────────────────
// These are 3x wider than local (90s/45s vs 30s/15s) — confirmed via local
// repro (same Chromium binary, same real backend) that a page which renders
// in ~3.6s locally could still consistently blow past the narrower value on
// a shared/throttled build machine running single-process,
// software-rendered (SwiftShader) Chromium. Left at the wider values
// unconditionally rather than collapsed to the local-dev numbers: issue #373
// asked for this collapse to be justified against a real Cloudflare Pages
// production build log, and that log wasn't available when this landed.
// Revisit with real numbers before narrowing.
export const NAV_TIMEOUT_MS = 90_000;
export const CONTENT_READY_TIMEOUT_MS = 45_000;
// Targets run through a bounded pool of pages rather than one at a time —
// with a growing published-event catalog (three locale variants each), a
// fully sequential run risks blowing past Cloudflare Pages' build cap.
// Bounded, not unbounded, mirroring
// this repo's external-API fan-out convention (CLAUDE.md). Used by the
// filesystem/`fetch()`-only validation pass below, which has no Chromium
// involvement and so isn't subject to RENDER_POOL_CONCURRENCY's constraint.
export const PRERENDER_CONCURRENCY = 6;
// Concurrency for the actual Playwright render pool (the `browser.newPage()`
// pool in main(), below).
export const RENDER_POOL_CONCURRENCY = PRERENDER_CONCURRENCY;
// GET /events/{id} is rate-limited server-side to RATE_LIMIT_EVENTS_DETAIL =
// "120/minute" per IP (backend/app/constants/rate_limits.py) — every worker's build
// machine shares one IP, so an unthrottled pool would eventually 429 as the
// published-event catalog grows, which (via the canonical-link wait below)
// surfaces as a spurious render "failure" and aborts the whole build.
// Capped comfortably under the server limit, shared across all workers.
export const EVENT_DETAIL_RATE_LIMIT_PER_MINUTE = 100;
// Bounded pool for the change-detection fetch pass (issue #80) — real
// GET requests against PRODUCTION_ORIGIN, one per event route, so this stays
// bounded rather than unbounded, mirroring this repo's external-API fan-out
// convention (CLAUDE.md). Separate from PRERENDER_CONCURRENCY/the rate gate
// above since these are plain page fetches, not the rate-limited
// GET /events/{id} endpoint.
export const CHANGE_DETECTION_CONCURRENCY = 6;
// Max in-flight R2 chain-state PUTs — deferred off the worker loops (Big-O
// audit M14) but still bounded so a big round can't queue thousands of bodies.
export const R2_PERSIST_CONCURRENCY = 16;
// JSON-LD field the change-detection marker (derived from Event.updated_at)
// is embedded under (issue #80). Not a real schema.org property of Event,
// but an extra key here doesn't violate the structural validation gate
// (assertEventJsonLd only checks for required fields) and Google/consumers
// ignore unrecognized properties.
export const CHANGE_MARKER_JSONLD_FIELD = 'dateModified';
// Hard wall-clock cap on the Playwright render pass only (issue #82) —
// excludes tsc/vite build and the in-build validation gate below, both of
// which run outside main()'s render-pool block. A round that hits this cap
// stops handing out new routes; unreached routes keep serving whatever's
// already live (copy-forward doubles as the "stale but real" fallback) or,
// for a route that's never been rendered at all, the CSR shell that
// `functions/[[path]].ts`'s SPA fallback serves instead. Overridable so the
// stop-at-cap behavior is verifiable without a real 10-minute wait (e.g.
// `PRERENDER_RENDER_BUDGET_MINUTES=0 npm run build`).
export const DEFAULT_RENDER_BUDGET_MINUTES = 10;
// Measured render throughput (~100 routes/min, docs/seo.md "Measured Cost")
// and the share of it predictRoundContinues trusts (issue #537). The margin
// sits below 1 because a wrong "done" guess costs a continuing round — the
// one already near the build cap — a post-render flush of its held PUTs,
// while a wrong "continuing" guess only wastes R2 writes.
export const PRERENDER_ROUTES_PER_MINUTE = 100;
export const PRERENDER_CONTINUE_PREDICTION_MARGIN = 0.75;
// Diagnostic ring buffer size per Playwright page, and the extra ms the request
// rate gate waits past the window edge so the next slot is really free.
export const PRERENDER_DIAGNOSTIC_MAX_EVENTS = 20;
export const RATE_GATE_SLACK_MS = 10;

// Max keys one S3/R2 list response returns — also the DeleteObjects batch cap.
export const S3_MAX_KEYS_PER_PAGE = 1000;
