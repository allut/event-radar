/**
 * Build-time static-prerender step (issue #50) — added to, not replacing,
 * `vite build`. Boots the just-built dist/ under `vite preview`, drives it
 * with Playwright, and writes a fully-rendered HTML snapshot per route to
 * dist/, so Vercel serves real content to crawlers/link-unfurlers instead of
 * the empty CSR shell for Landing and every published /events/:id, across
 * all three locale-prefixed URL variants.
 *
 * This script owns the "list published events" query (via GET
 * /public/prerender-events) as the single source of truth for what gets
 * prerendered, reused as-is (via the same `targets` list `buildTargets`
 * produces) to also emit sitemap.xml + robots.txt in the same build run
 * (issue #51), so the sitemap and the snapshot pages it lists can never
 * disagree.
 *
 * Once every snapshot is written, an in-build validation gate (issue #53,
 * src/lib/seoValidation.ts) reads each one back off disk and checks
 * structural correctness (valid JSON-LD, a non-default title, a canonical,
 * the hreflang alternates) and non-staleness (title/venue/price still match
 * what GET /events/{id} returns right now) — blocking the deploy on failure.
 *
 * Fails loudly (non-zero exit) if the published-events fetch fails, if
 * Playwright can't reach/render any target route, or if the validation gate
 * finds a structural/staleness issue — see docs/frontend.md's prerender
 * section. `npm run build` copies dist/index.html to dist/app-shell.html
 * *before* invoking this script (not inside it) so the SPA-fallback rewrite
 * target exists even if this script never runs to completion.
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { JSDOM } from 'jsdom';
import { chromium, type Browser, type Page } from 'playwright';
import { preview, type PreviewServer } from 'vite';
import type { EventData } from '../src/components/EventCard';
import {
  CANONICAL_LINK_SELECTOR,
  GITHUB_API_BASE_URL,
  JSONLD_SCRIPT_SELECTOR,
  LOCALE_URL_PREFIX_CODES,
  LOCALES,
  PRERENDER_CHAIN_GITHUB_REPO,
  PRODUCTION_ORIGIN,
  ROUND_STATUS,
  ROUTES,
  SEO_HREFLANG_CODES,
  SEO_XDEFAULT_CODE,
  SITEMAP_FILENAME,
  SITEMAP_PATH,
} from '../src/constants';
import { localizedPath } from '../src/lib/urlLocale';
import { compareEventStaleness, parseSnapshotHtml, validateSnapshotStructure } from '../src/lib/seoValidation';
import { createBudgetedCursor, prioritizeRenderQueue } from '../src/lib/prerenderQueue';
import {
  buildRoundMarker,
  isChainDepthExceeded,
  isZeroProgress,
  resolveRoundStart,
  serializeRoundMarker,
  shouldCommitRoundMarker,
  type RoundMarker,
} from '../src/lib/prerenderChain';
import { PRERENDER_BACKEND_TARGET } from '../vite.config';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIST_DIR = path.resolve(__dirname, '../dist');
const API_ORIGIN = PRERENDER_BACKEND_TARGET;
// Both timeouts are 3x wider on Vercel. Confirmed via local repro (same
// @sparticuz/chromium binary, same real backend) that a page which renders
// in ~3.6s off Vercel can still consistently blow past 15s on Vercel's
// build machine — every attempted route timed out identically at both
// concurrency 6 and concurrency 1 (RENDER_POOL_CONCURRENCY above), even the
// static, no-data-dependency Landing route, which rules out contention or
// backend latency as the sole cause and points at the shared/throttled
// 2-core build machine simply running this single-process, software-
// rendered (SwiftShader) Chromium slower across the board. Widening the
// timeout costs throughput (fewer routes fit in the render budget per
// round), which the render-budget/chaining mechanism (issues #82/#84)
// already exists to absorb across rounds — a hard build failure from a
// route that would have succeeded given a few more seconds is worse than a
// slower round.
const NAV_TIMEOUT_MS = process.env.VERCEL ? 90_000 : 30_000;
const CONTENT_READY_TIMEOUT_MS = process.env.VERCEL ? 45_000 : 15_000;
// Targets run through a bounded pool of pages rather than one at a time —
// with a growing published-event catalog (three locale variants each), a
// fully sequential run risks Vercel's Hobby-plan 45-minute build cap (see
// docs/research/prerendering-approach.md). Bounded, not unbounded, mirroring
// this repo's external-API fan-out convention (CLAUDE.md). Used by the
// filesystem/`fetch()`-only validation pass below, which has no Chromium
// involvement and so isn't subject to RENDER_POOL_CONCURRENCY's constraint.
const PRERENDER_CONCURRENCY = 6;
// Concurrency for the actual Playwright render pool (the `browser.newPage()`
// pool in main(), below) — narrower than PRERENDER_CONCURRENCY on Vercel.
// `@sparticuz/chromium`'s launch args always include `--single-process`
// (required — Lambda's sandbox rejects the `prctl` calls a multi-process
// Chromium needs), which forces every concurrently-open page through one OS
// process/thread — multiple pages there compete for that one thread rather
// than getting Chromium's normal per-page process isolation. (An earlier
// version of this comment blamed that contention for routes failing in an
// apparent simultaneous burst; that read the failure *logging* — which is
// batched into one loop after the whole pool settles, not emitted live — as
// the failures themselves happening at once. The real cause, confirmed by a
// follow-up run at concurrency 1 that failed the exact same routes, is
// CONTENT_READY_TIMEOUT_MS being too tight for Vercel's build machine
// regardless of concurrency — see the timeout comment above.) Keeping this
// at 1 on Vercel still avoids adding avoidable single-thread contention on
// top of that base slowness; the render-budget/chaining mechanism (issues
// #82/#84) covers the resulting lower single-round throughput across later
// rounds. Off Vercel, Playwright's own bundled Chromium has no such
// constraint, so this stays at PRERENDER_CONCURRENCY's original width.
const RENDER_POOL_CONCURRENCY = process.env.VERCEL ? 1 : PRERENDER_CONCURRENCY;
// GET /events/{id} is rate-limited server-side to RATE_LIMIT_EVENTS_DETAIL =
// "120/minute" per IP (backend/app/constants.py) — every worker's build
// machine shares one IP, so an unthrottled pool would eventually 429 as the
// published-event catalog grows, which (via the canonical-link wait below)
// surfaces as a spurious render "failure" and aborts the whole build.
// Capped comfortably under the server limit, shared across all workers.
const EVENT_DETAIL_RATE_LIMIT_PER_MINUTE = 100;
// Bounded pool for the change-detection fetch pass (issue #80) — real
// GET requests against PRODUCTION_ORIGIN, one per event route, so this stays
// bounded rather than unbounded, mirroring this repo's external-API fan-out
// convention (CLAUDE.md). Separate from PRERENDER_CONCURRENCY/the rate gate
// above since these are plain page fetches, not the rate-limited
// GET /events/{id} endpoint.
const CHANGE_DETECTION_CONCURRENCY = 6;
// JSON-LD field the change-detection marker (derived from Event.updated_at)
// is embedded under (issue #80). Not a real schema.org property of Event,
// but an extra key here doesn't violate the structural validation gate
// (assertEventJsonLd only checks for required fields) and Google/consumers
// ignore unrecognized properties.
const CHANGE_MARKER_JSONLD_FIELD = 'dateModified';
// Hard wall-clock cap on the Playwright render pass only (issue #82) —
// excludes tsc/vite build and the in-build validation gate below, both of
// which run outside main()'s render-pool block. A round that hits this cap
// stops handing out new routes; unreached routes keep serving whatever's
// already live (copy-forward doubles as the "stale but real" fallback) or,
// for a route that's never been rendered at all, the CSR shell that
// vercel.json's catch-all rewrite falls back to. Overridable so the
// stop-at-cap behavior is verifiable without a real 10-minute wait (e.g.
// `PRERENDER_RENDER_BUDGET_MINUTES=0 npm run build`).
const DEFAULT_RENDER_BUDGET_MINUTES = 10;
const RENDER_BUDGET_MS = (() => {
  const raw = process.env.PRERENDER_RENDER_BUDGET_MINUTES;
  if (raw === undefined) return DEFAULT_RENDER_BUDGET_MINUTES * 60_000;
  const minutes = Number(raw);
  if (!Number.isFinite(minutes) || minutes < 0) {
    throw new Error(
      `prerender: PRERENDER_RENDER_BUDGET_MINUTES must be a non-negative number, got ${JSON.stringify(raw)}`,
    );
  }
  return minutes * 60_000;
})();

export interface PrerenderTarget {
  /** Bare (Estonian) ROUTES.* path, before locale-prefixing. */
  bare: string;
  locale: string;
  /** Set for /events/:id targets only — the in-build validation gate's
   * non-staleness check (validateTarget) uses it to re-fetch the live event. */
  eventId?: number;
  /** ISO Event.updated_at (issue #80) — set alongside eventId only. The
   * change-detection marker embedded in this route's JSON-LD and diffed
   * against the currently-live production page's marker. Home routes carry
   * no Event to diff against, so they're always rendered fresh. */
  updatedAt?: string;
}

/** Simple sliding-window rate gate — `acquire()` resolves immediately while
 * under budget, else waits until the oldest slot in the window expires. */
class RateGate {
  private readonly timestamps: number[] = [];
  constructor(
    private readonly maxPerWindow: number,
    private readonly windowMs: number,
  ) {}

  async acquire(): Promise<void> {
    for (;;) {
      const now = Date.now();
      while (this.timestamps.length > 0 && now - this.timestamps[0] >= this.windowMs) {
        this.timestamps.shift();
      }
      if (this.timestamps.length < this.maxPerWindow) {
        this.timestamps.push(now);
        return;
      }
      const waitMs = this.windowMs - (now - this.timestamps[0]) + 10;
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }
  }
}

const eventDetailRateGate = new RateGate(EVENT_DETAIL_RATE_LIMIT_PER_MINUTE, 60_000);

interface PrerenderCandidate {
  id: number;
  /** ISO Event.updated_at — see PrerenderTarget.updatedAt (issue #80). */
  updatedAt: string;
}

async function fetchPrerenderCandidates(): Promise<PrerenderCandidate[]> {
  const res = await fetch(`${API_ORIGIN}/public/prerender-events`);
  if (!res.ok) {
    throw new Error(
      `prerender: failed to fetch published events from ${API_ORIGIN}/public/prerender-events — ${res.status} ${res.statusText}`,
    );
  }
  const body = (await res.json()) as { events: { id: number; updated_at: string }[] };
  return body.events.map((e) => ({ id: e.id, updatedAt: e.updated_at }));
}

function buildTargets(candidates: PrerenderCandidate[]): PrerenderTarget[] {
  const localeCodes = LOCALES.map((l) => l.code);
  const targets: PrerenderTarget[] = [];
  for (const locale of localeCodes) {
    targets.push({ bare: ROUTES.home, locale });
    for (const candidate of candidates) {
      targets.push({
        bare: ROUTES.eventDetail(candidate.id),
        locale,
        eventId: candidate.id,
        updatedAt: candidate.updatedAt,
      });
    }
  }
  return targets;
}

/** Embeds `marker` under CHANGE_MARKER_JSONLD_FIELD in `html`'s single
 * JSON-LD script (issue #80), at render time — after the page's real
 * content (including its JSON-LD) has already been captured. Leaves `html`
 * unchanged if there's no JSON-LD script or its body doesn't parse; the
 * in-build validation gate below is what actually catches/blocks on that. */
function embedChangeMarker(html: string, marker: string): string {
  const dom = new JSDOM(html);
  const script = dom.window.document.querySelector(JSONLD_SCRIPT_SELECTOR);
  if (script) {
    try {
      const data = JSON.parse(script.textContent ?? '{}') as Record<string, unknown>;
      data[CHANGE_MARKER_JSONLD_FIELD] = marker;
      script.textContent = JSON.stringify(data);
    } catch {
      // Malformed JSON-LD — leave untouched, validateTarget() catches it.
    }
  }
  return dom.serialize();
}

/** Reads the change-detection marker back off a rendered snapshot's JSON-LD
 * (issue #80) — used both to read the currently-live production page during
 * change detection, and (via the same parseSnapshotHtml helper the in-build
 * validation gate uses) to keep the two readers in agreement. */
function extractChangeMarker(html: string): string | null {
  const jsonLd = parseSnapshotHtml(html).jsonLd[0];
  if (jsonLd && typeof jsonLd === 'object') {
    const marker = (jsonLd as Record<string, unknown>)[CHANGE_MARKER_JSONLD_FIELD];
    if (typeof marker === 'string') return marker;
  }
  return null;
}

interface ChangeDetectionResult {
  target: PrerenderTarget;
  /** True when the live page's embedded marker matches — the Playwright
   * render is skipped entirely and `liveHtml` copied forward as-is. */
  unchanged: boolean;
  /** The target's currently-live production HTML, if a page exists there at
   * all (null on fetch failure or a non-2xx, typically 404 for a route
   * that's never been rendered). Used as-is when `unchanged`; also kept
   * around as the stale-but-real fallback (issue #82) for a route that
   * *does* need a fresh render but the render budget runs out before
   * reaching it — copying the last-known-good page forward beats leaving
   * the route with nothing this round. A route with no live page at all
   * (null here) falls through to the CSR shell via vercel.json's catch-all
   * rewrite instead. */
  liveHtml: string | null;
}

/** Change detection (issue #80): fetches `target`'s currently-live
 * production page and diffs its embedded marker against `target.updatedAt`.
 * `unchanged` is true only on an exact marker match — home routes have no
 * Event.updated_at to diff against, so they're never `unchanged` and always
 * render fresh. They still go through this fetch (issue #82): a home route
 * always renders first (highest queue priority), but if the render budget
 * is small enough to strand even it, `liveHtml` is what lets it copy
 * forward its own last-known-good page instead of falling through to the
 * CSR shell — the same stale-but-real fallback every event route gets. */
async function classifyTarget(target: PrerenderTarget): Promise<ChangeDetectionResult> {
  const url = `${PRODUCTION_ORIGIN}${localizedPath(target.bare, target.locale)}`;
  let res: Response;
  try {
    res = await fetch(url);
  } catch {
    return { target, unchanged: false, liveHtml: null };
  }
  if (!res.ok) return { target, unchanged: false, liveHtml: null };
  const html = await res.text();
  if (target.eventId === undefined || target.updatedAt === undefined) {
    return { target, unchanged: false, liveHtml: html };
  }
  const liveMarker = extractChangeMarker(html);
  const unchanged = liveMarker !== null && liveMarker === target.updatedAt;
  return { target, unchanged, liveHtml: html };
}

/** sitemap.xml for `targets` (issue #51) — one `<url>` per locale-variant
 * URL (mirrors `buildTargets`'s flat "every locale × every bare path"
 * shape), each carrying the same en/et/ru/x-default hreflang cross-references
 * `useSeoMeta`'s `buildSeoMeta` emits as `<link>` tags, so the sitemap and
 * the prerendered pages it lists never disagree about locale siblings.
 * `lastmod` is each event target's real `Event.updated_at` (issue #80) where
 * available, falling back to `buildTimestamp` for home (no backing Event). */
function buildSitemapXml(targets: PrerenderTarget[], buildTimestamp: string): string {
  const urlEntries = targets
    .map((target) => {
      const loc = `${PRODUCTION_ORIGIN}${localizedPath(target.bare, target.locale)}`;
      const alternates = SEO_HREFLANG_CODES.map((code) => {
        const href =
          code === SEO_XDEFAULT_CODE
            ? `${PRODUCTION_ORIGIN}${target.bare}`
            : `${PRODUCTION_ORIGIN}${localizedPath(target.bare, code)}`;
        return `    <xhtml:link rel="alternate" hreflang="${code}" href="${href}"/>`;
      }).join('\n');
      const lastmod = target.updatedAt ?? buildTimestamp;
      return `  <url>\n    <loc>${loc}</loc>\n    <lastmod>${lastmod}</lastmod>\n${alternates}\n  </url>`;
    })
    .join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n${urlEntries}\n</urlset>\n`;
}

/** robots.txt (issue #51) — inverse-allowlist shape (`Disallow: /` first,
 * then explicit `Allow:`s) so a new authenticated route added later is
 * excluded by default, with no robots.txt edit required to keep it that way. */
function buildRobotsTxt(): string {
  const lines = ['User-agent: *', 'Disallow: /', 'Allow: /$', 'Allow: /events/'];
  for (const code of LOCALE_URL_PREFIX_CODES) {
    lines.push(`Allow: /${code}$`, `Allow: /${code}/events/`);
  }
  lines.push('', `Sitemap: ${PRODUCTION_ORIGIN}${SITEMAP_PATH}`);
  return lines.join('\n') + '\n';
}

/** dist-relative output file for a locale-prefixed URL — mirrors how Vercel's
 * static file server resolves a directory path to its index.html. */
function outputFilePath(bare: string, locale: string): string {
  const localized = localizedPath(bare, locale);
  const relDir = localized === '/' ? '' : localized;
  return path.join(DIST_DIR, relDir, 'index.html');
}

/**
 * On Vercel, launches `@sparticuz/chromium` explicitly rather than falling
 * through to Playwright-bundled Chromium (issue #87, reusing Wave 1's fix
 * from issue #72) — the build script's `[ -n "$VERCEL" ] || playwright
 * install chromium` step skips installing Playwright's own browser on
 * Vercel, so `chromium.launch()` alone would have nothing to launch there.
 * `@sparticuz/chromium`'s bundled binary is linked against a handful of
 * AL2023 shared libs (`libnspr4.so`/`libnss3.so`/`libnssutil3.so`) that
 * aren't present on the build image by default; `executablePath()` only
 * extracts them and points `LD_LIBRARY_PATH` at the extraction dir when its
 * own `isRunningInAmazonLinux2023` check sees `VERCEL` set — so `VERCEL`
 * must stay visible through this call, not hidden, or the launch fails with
 * `error while loading shared libraries: libnspr4.so: cannot open shared
 * object file`. Off Vercel (local/dev, any OS), Playwright's own bundled
 * Chromium is used unchanged — `@sparticuz/chromium`'s binary is Linux-only.
 */
async function launchBrowser(): Promise<Browser> {
  if (!process.env.VERCEL) {
    return chromium.launch();
  }
  const { default: sparticuzChromium } = await import('@sparticuz/chromium');
  return await chromium.launch({
    args: sparticuzChromium.args,
    executablePath: await sparticuzChromium.executablePath(),
    headless: true,
  });
}

/** Rolling buffer of a page's recent console/pageerror/requestfailed
 * activity (issue #86 investigation) — three consecutive Vercel-only
 * `waitForSelector` timeout theories (single-process contention, then a
 * flat timeout bump) each failed to explain the next production run, always
 * on the exact same routes including the static, no-fetch Landing page.
 * Rather than guess a fourth time, capture what the page itself was doing
 * when a render times out, so the next failure's log says what actually
 * happened instead of just that it didn't. Attached once per page (workers
 * reuse one page across many targets), capped so a long-lived page's buffer
 * can't grow unbounded. */
function attachPageDiagnostics(page: Page): () => string[] {
  const MAX_EVENTS = 20;
  const events: string[] = [];
  const record = (line: string) => {
    events.push(line);
    if (events.length > MAX_EVENTS) events.shift();
  };
  page.on('console', (msg) => record(`console.${msg.type()}: ${msg.text().slice(0, 300)}`));
  page.on('pageerror', (err) => record(`pageerror: ${String(err).slice(0, 300)}`));
  page.on('requestfailed', (req) =>
    record(`requestfailed: ${req.url()} — ${req.failure()?.errorText ?? 'unknown'}`),
  );
  return () => [...events];
}

async function snapshotTarget(
  page: Page,
  previewOrigin: string,
  target: PrerenderTarget,
): Promise<void> {
  if (target.bare !== ROUTES.home) {
    await eventDetailRateGate.acquire();
  }
  const url = `${previewOrigin}${localizedPath(target.bare, target.locale)}`;
  await page.goto(url, { waitUntil: 'networkidle', timeout: NAV_TIMEOUT_MS });
  // Landing and /events/:id are the only routes useSeoMeta marks `indexable`
  // (see useSeoMeta.ts) — for /events/:id that only flips true once the
  // event has actually loaded (EventDetail.tsx), so waiting for the
  // canonical link this hook emits is a reliable "real content is in the
  // DOM, not the loading/CSR-shell state" signal for both target types.
  // `state: 'attached'`, not the default 'visible' — a <link> element never
  // has a CSS box, so the default visibility check would time out even once
  // Helmet has inserted it.
  await page.waitForSelector(CANONICAL_LINK_SELECTOR, {
    state: 'attached',
    timeout: CONTENT_READY_TIMEOUT_MS,
  });
  let html = await page.content();
  if (target.eventId !== undefined && target.updatedAt !== undefined) {
    html = embedChangeMarker(html, target.updatedAt);
  }
  const outPath = outputFilePath(target.bare, target.locale);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, html, 'utf-8');
}

/** Bounded-concurrency runner shared by the change-detection pass, the
 * snapshot pass, and the validation-gate pass below (issues #53, #80) —
 * bounded, not unbounded, mirroring this repo's external-API fan-out
 * convention (CLAUDE.md). Shares its index-claiming with the render pass's
 * time-boxed pool via createBudgetedCursor (issue #82) — an unreachable
 * deadline (`Infinity`) makes it behave as a plain, non-budgeted cursor
 * rather than a second hand-rolled "claim next index" loop. */
async function mapPool<T, R>(
  items: T[],
  concurrency: number,
  worker: (item: T) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  const cursor = createBudgetedCursor(items.length, Infinity);
  async function run(): Promise<void> {
    for (;;) {
      const i = cursor.next();
      if (i === null) break;
      results[i] = await worker(items[i]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, run));
  return results;
}

async function runPool<T>(items: T[], concurrency: number, worker: (item: T) => Promise<void>): Promise<void> {
  await mapPool(items, concurrency, worker);
}

/** In-build validation gate (issue #53) — reads a just-written snapshot back
 * off disk and checks it against src/lib/seoValidation.ts's structural
 * (title/canonical/hreflang/JSON-LD) assertions and, for /events/:id
 * targets, its non-staleness (title/venue/price vs. the live API right now)
 * assertions. That module is deliberately filesystem/network-free so the
 * live-audit ticket (issue #54) can reuse it unchanged against a
 * fetch()-ed production page instead of a dist/ file. Shares
 * eventDetailRateGate's budget with the snapshot pass above, since this is
 * another round of real GET /events/{id} calls against the same
 * rate-limited backend — deliberately a *second*, independent fetch rather
 * than reusing the response the browser already got during snapshotTarget:
 * reusing it would make the staleness comparison vacuous (it'd always match
 * the very data it was built from), whereas the acceptance criteria call for
 * comparing against what the live API returns right now. This roughly
 * doubles the build's GET /events/{id} volume; accepted for now since the
 * gate still runs sequentially after the snapshot pass under the same
 * rate-limited budget, bounded rather than unbounded — worth revisiting if
 * the published-event catalog grows enough to threaten the Vercel
 * Hobby-plan 45-minute build cap (see PRERENDER_CONCURRENCY above). Returns
 * one message per violation, prefixed with the target's path — never
 * throws for a validation failure itself. */
async function validateTarget(target: PrerenderTarget): Promise<string[]> {
  const html = await readFile(outputFilePath(target.bare, target.locale), 'utf-8');
  const parsed = parseSnapshotHtml(html);
  const isHome = target.bare === ROUTES.home;

  const issues = validateSnapshotStructure(parsed, {
    kind: isHome ? 'website' : 'event',
    locale: target.locale,
    originPrefix: PRODUCTION_ORIGIN,
  }).map((issue) => `structural: ${issue}`);

  if (target.eventId !== undefined) {
    await eventDetailRateGate.acquire();
    const url = `${API_ORIGIN}/events/${target.eventId}?locale=${encodeURIComponent(target.locale)}`;
    const res = await fetch(url);
    if (!res.ok) {
      issues.push(`staleness: failed to fetch live event ${target.eventId} for comparison — ${res.status} ${res.statusText}`);
    } else {
      const live = (await res.json()) as EventData;
      issues.push(...compareEventStaleness(parsed, live).map((issue) => `staleness: ${issue}`));
    }
  }

  return issues.map((issue) => `${localizedPath(target.bare, target.locale)} — ${issue}`);
}

/** Commits `marker` to the branch the Vercel Deploy Hook targets (issue #83),
 * advancing the git ref so a later chained round (issue #84) can re-fire the
 * hook against a genuinely new version rather than colliding with Vercel's
 * same-version-cancellation behavior. Uses the GitHub Git Data API — not a
 * local `git push` — since the Vercel build environment's checkout has no
 * guaranteed push credentials; mirrors api/seo-audit.ts's plain-fetch
 * GH_ISSUE_TOKEN pattern rather than adding an SDK dependency. The new
 * commit reuses the branch tip's tree unchanged (no file diff — only the
 * marker embedded in the message changes), so this is effectively an empty
 * commit. No-ops with a log line (not a build failure) when
 * GH_PRERENDER_CHAIN_TOKEN/VERCEL_GIT_COMMIT_REF aren't set, e.g. local/dev
 * builds off Vercel — returns `false` in that case (as opposed to throwing,
 * its failure path) to distinguish "nothing was committed" from "the commit
 * succeeded". main() only calls this when shouldCommitRoundMarker(marker)
 * says the round is `continuing` (issue #101 — see that function's doc
 * comment for why a `done` round must never reach this call). The advanced
 * ref is this chain's sole continuation trigger (issue #89): the production
 * branch is Vercel-git-connected, so this push alone fires the next round's
 * build — no separate Deploy Hook call is needed or made. */
async function commitRoundMarker(marker: RoundMarker): Promise<boolean> {
  const token = process.env.GH_PRERENDER_CHAIN_TOKEN;
  const branch = process.env.VERCEL_GIT_COMMIT_REF;
  if (!token || !branch) {
    console.log(
      'prerender: GH_PRERENDER_CHAIN_TOKEN/VERCEL_GIT_COMMIT_REF not set — skipping round-marker commit (not a Vercel build)',
    );
    return false;
  }

  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
  };
  const repoBase = `${GITHUB_API_BASE_URL}/repos/${PRERENDER_CHAIN_GITHUB_REPO}`;

  const refRes = await fetch(`${repoBase}/git/ref/heads/${branch}`, { headers });
  if (!refRes.ok) {
    throw new Error(
      `prerender: failed to read ref heads/${branch} — ${refRes.status} ${refRes.statusText}`,
    );
  }
  const parentSha = ((await refRes.json()) as { object: { sha: string } }).object.sha;

  const parentCommitRes = await fetch(`${repoBase}/git/commits/${parentSha}`, { headers });
  if (!parentCommitRes.ok) {
    throw new Error(
      `prerender: failed to read parent commit ${parentSha} — ${parentCommitRes.status} ${parentCommitRes.statusText}`,
    );
  }
  const treeSha = ((await parentCommitRes.json()) as { tree: { sha: string } }).tree.sha;

  const summary = `round ${marker.round} (${marker.status}) — ${marker.newlyRendered} rendered, ${marker.copiedForward} copied, ${marker.queueRemaining} queued`;
  const message = `prerender: ${summary}\n\n${serializeRoundMarker(marker)}`;

  const commitRes = await fetch(`${repoBase}/git/commits`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, tree: treeSha, parents: [parentSha] }),
  });
  if (!commitRes.ok) {
    throw new Error(
      `prerender: failed to create round-marker commit — ${commitRes.status} ${commitRes.statusText}`,
    );
  }
  const newSha = ((await commitRes.json()) as { sha: string }).sha;

  const updateRefRes = await fetch(`${repoBase}/git/refs/heads/${branch}`, {
    method: 'PATCH',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ sha: newSha }),
  });
  if (!updateRefRes.ok) {
    throw new Error(
      `prerender: failed to advance heads/${branch} to ${newSha} — ${updateRefRes.status} ${updateRefRes.statusText}`,
    );
  }
  console.log(`prerender: committed round marker ${newSha} to ${branch} — ${summary}`);
  return true;
}

/** Diagnostic-only: logs at WARNING (round/burst context, no separate admin
 * alert per the spec) when a round was forced to `done` by the zero-progress
 * abort — `queueRemaining > 0` and not already `isChainDepthExceeded` is what
 * distinguishes that genuinely-stuck case from a `done` round that naturally
 * emptied its queue (nothing needed rendering to begin with, also
 * `newlyRendered === 0` but nothing to warn about) or hit the chain-depth cap
 * (an expected, routine outcome, not a stuck catalog, even on the rare round
 * that also rendered nothing new). No-op for a `continuing` marker.
 *
 * Chaining to the next round (issue #84) no longer fires an explicit Deploy
 * Hook here — `commitRoundMarker`'s branch push already triggers Vercel's
 * git-connected auto-deploy, and firing a second hook against the same
 * commit produced two competing deployments (issue #89). */
/** Scopes the in-build validation gate to this round's newly-rendered
 * routes only (issue #94) — `renderQueue` minus whatever the render budget
 * left in `skippedTargets`. Copied-forward routes (never in `renderQueue`)
 * are byte-identical to what already passed this same gate earlier, so
 * re-validating them every round is pure waste that grows unboundedly as
 * the copied-forward set accumulates. */
export function selectValidationTargets(
  renderQueue: PrerenderTarget[],
  skippedTargets: PrerenderTarget[],
): PrerenderTarget[] {
  const skippedTargetSet = new Set(skippedTargets);
  return renderQueue.filter((target) => !skippedTargetSet.has(target));
}

export function logZeroProgressAbort(marker: RoundMarker): void {
  if (marker.status === ROUND_STATUS.continuing) {
    return;
  }
  if (isZeroProgress(marker) && marker.queueRemaining > 0 && !isChainDepthExceeded(marker.round)) {
    console.warn(
      `prerender: zero-progress abort — round ${marker.round} of burst ${marker.burstId} rendered 0 new routes with ${marker.queueRemaining} route(s) still queued; chain forced to done`,
    );
  }
}

/** True on a Vercel Preview build (issue #95) — `VERCEL_ENV` is Vercel's own
 * build-time discriminator (`"production" | "preview" | "development"`),
 * auto-injected regardless of build type. Preview URLs aren't crawled or
 * linked externally, and `vercel.json`'s catch-all rewrite already serves
 * `app-shell.html` for any route with no snapshot, so skipping prerendering
 * doesn't affect preview functionality. Also sidesteps `commitRoundMarker`
 * reading `VERCEL_GIT_COMMIT_REF` and committing a chain-state marker
 * against a preview branch ref. Local/dev runs (`VERCEL` unset) are
 * unaffected — `VERCEL_ENV` is never set there either. */
export function isPreviewBuild(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.VERCEL_ENV === 'preview';
}

export async function main(): Promise<void> {
  if (isPreviewBuild()) {
    console.log('prerender: VERCEL_ENV=preview — skipping prerender pass entirely (issue #95)');
    return;
  }

  // Read back whatever VERCEL_GIT_COMMIT_MESSAGE carries from the tip commit
  // at build start, before doing any rendering work, to resume mid-burst
  // rather than always starting fresh at round 1 (issue #83). Since the
  // round marker's git push is the only thing that triggers the next round's
  // build (issue #89 removed the redundant Deploy Hook that used to fire a
  // second, competing deployment of the same commit), a fresh `continuing`
  // marker here is exactly the legitimate continuation it was committed for
  // — see resolveRoundStart's doc comment (src/lib/prerenderChain.ts) for why
  // it resumes at round + 1 instead of skipping (issue #90), and why a stale
  // `continuing` marker still falls through to a fresh round 1.
  const { burstId, round } = resolveRoundStart(process.env.VERCEL_GIT_COMMIT_MESSAGE, new Date());
  console.log(`prerender: round ${round} of burst ${burstId}${round > 1 ? ' (resumed)' : ' (new)'}`);

  const candidates = await fetchPrerenderCandidates();
  const targets = buildTargets(candidates);

  const buildTimestamp = new Date().toISOString();
  await writeFile(
    path.join(DIST_DIR, SITEMAP_FILENAME),
    buildSitemapXml(targets, buildTimestamp),
    'utf-8',
  );
  await writeFile(path.join(DIST_DIR, 'robots.txt'), buildRobotsTxt(), 'utf-8');
  console.log(`prerender: wrote sitemap.xml (${targets.length} url(s)) and robots.txt`);

  // Change detection (issue #80): for every event route, diff its embedded
  // marker against the currently-live production page. An exact match
  // copies the live page forward as-is (no Playwright render); everything
  // else (never-rendered, changed, or a fetch/parse miss) renders fresh.
  const classification = await mapPool(targets, CHANGE_DETECTION_CONCURRENCY, classifyTarget);
  let copiedForward = 0;
  // Stale-but-real fallback (issue #82) content, held in memory rather than
  // written to dist/ yet — see the write-out below (after the render pool)
  // for why. Keyed by target so a successfully-rendered or -failed target
  // can drop its entry once the render loop has an answer for it either way.
  const staleFallbackHtml = new Map<PrerenderTarget, string>();
  for (const { target, unchanged, liveHtml } of classification) {
    if (unchanged && liveHtml !== null) {
      const outPath = outputFilePath(target.bare, target.locale);
      await mkdir(path.dirname(outPath), { recursive: true });
      await writeFile(outPath, liveHtml, 'utf-8');
      copiedForward++;
    } else if (liveHtml !== null) {
      // Needs a fresh render, but a live page exists — held for now rather
      // than written to its final path immediately (issue #86 investigation:
      // an earlier version of this wrote it straight to outputFilePath()
      // here, "eagerly" ahead of the render pool, on the theory that
      // snapshotTarget's writeFile below would just overwrite it in place
      // once the route was actually reached. In practice `vite preview`
      // serves a literal file over its SPA fallback, so the moment this
      // route's *own* Playwright render attempt navigated to it later in
      // this same round, it loaded this stale page instead of the CSR shell
      // — referencing a previous build's JS asset hash, which 404s against
      // the current build's dist/assets/, so the app never mounts and the
      // canonical-link wait times out. Every route with existing live
      // content failed this way, permanently, regardless of concurrency or
      // timeout width, until this was caught by attachPageDiagnostics
      // surfacing the 404'd asset in a build log). Deferring the write until
      // after the render pool — only for targets it never got to — keeps
      // the memory benefit this was written for (not holding hundreds of
      // routes' full HTML for the whole pass; entries are freed as the
      // render loop resolves each one) without the self-sabotage.
      staleFallbackHtml.set(target, liveHtml);
    }
  }
  // Priority queue (issue #82): home routes (all locales) first, then event
  // routes oldest-unrendered-first — so a large event backlog can never
  // starve the highest-traffic pages, and among event routes the
  // longest-stale one always gets budget before a newer one.
  const renderQueue = prioritizeRenderQueue(classification
    .filter(({ unchanged }) => !unchanged)
    .map(({ target }) => target));
  console.log(
    `prerender: copied forward ${copiedForward}/${targets.length} unchanged route(s), rendering ${renderQueue.length}`,
  );

  let newlyRendered = 0;
  let skippedTargets: PrerenderTarget[] = [];
  if (renderQueue.length > 0) {
    let server: PreviewServer | undefined;
    const browser = await launchBrowser();
    try {
      server = await preview({ preview: { port: 0, strictPort: false }, logLevel: 'warn' });
      const previewOrigin = server.resolvedUrls?.local[0]?.replace(/\/$/, '');
      if (!previewOrigin) {
        throw new Error('prerender: vite preview server did not resolve a local URL');
      }

      const resolvedPreviewOrigin = previewOrigin;
      const failures: { target: PrerenderTarget; error: unknown; diagnostics: string[] }[] = [];
      // Hard 10-minute (overridable) cap on this pool only (issue #82) — see
      // RENDER_BUDGET_MS. Started once the preview server/browser are up, so
      // the budget covers actual render time, not startup.
      const deadline = Date.now() + RENDER_BUDGET_MS;
      const cursor = createBudgetedCursor(renderQueue.length, deadline);
      async function worker(): Promise<void> {
        const page = await browser.newPage();
        const recentEvents = attachPageDiagnostics(page);
        try {
          for (;;) {
            const i = cursor.next();
            if (i === null) break;
            const target = renderQueue[i];
            try {
              await snapshotTarget(page, resolvedPreviewOrigin, target);
              newlyRendered++;
            } catch (error) {
              failures.push({ target, error, diagnostics: recentEvents() });
            } finally {
              // No longer needed as a fallback either way: a success wrote a
              // fresh snapshot over any stale content; a failure aborts the
              // whole build below, so nothing further will ever read this.
              staleFallbackHtml.delete(target);
            }
          }
        } finally {
          await page.close();
        }
      }
      await Promise.all(
        Array.from({ length: Math.min(RENDER_POOL_CONCURRENCY, renderQueue.length) }, worker),
      );
      skippedTargets = cursor.remaining().map((i) => renderQueue[i]);

      if (failures.length > 0) {
        for (const { target, error, diagnostics } of failures) {
          console.error(
            `prerender: failed to render ${localizedPath(target.bare, target.locale)} —`,
            error,
          );
          if (diagnostics.length > 0) {
            console.error(
              `prerender: recent page activity for ${localizedPath(target.bare, target.locale)}:\n  ${diagnostics.join('\n  ')}`,
            );
          } else {
            console.error(
              `prerender: no page console/network activity recorded for ${localizedPath(target.bare, target.locale)} before it timed out.`,
            );
          }
        }
        throw new Error(
          `prerender: ${failures.length}/${renderQueue.length} route(s) failed to render — see errors above`,
        );
      }

      console.log(`prerender: wrote ${newlyRendered} snapshot(s) to ${DIST_DIR}`);
    } finally {
      await browser.close();
      await server?.close();
    }
  } else {
    console.log('prerender: no routes require rendering — every route was copied forward');
  }

  // Stale-but-real fallback (issue #82): a route skipped this round because
  // the budget ran out gets its last-known-good live page written now, if
  // one existed (held in staleFallbackHtml above — see that block for why
  // this write is deferred to here instead of happening ahead of the render
  // pool). A route with no live page at all (never rendered before) has
  // nothing on disk, which falls through to the CSR shell via vercel.json's
  // catch-all rewrite rather than a build failure — see outputFilePath/vercel.json.
  let staleFallbackWritten = 0;
  for (const target of skippedTargets) {
    const liveHtml = staleFallbackHtml.get(target);
    if (liveHtml === undefined) continue;
    const outPath = outputFilePath(target.bare, target.locale);
    await mkdir(path.dirname(outPath), { recursive: true });
    await writeFile(outPath, liveHtml, 'utf-8');
    staleFallbackWritten++;
  }

  console.log(
    `prerender: round summary — newly-rendered ${newlyRendered}, copied-forward ${copiedForward}, queue-remaining ${skippedTargets.length} (${staleFallbackWritten} of those still serving stale-but-real content)`,
  );
  if (skippedTargets.length > 0) {
    console.log(
      `prerender: hit the render budget with ${skippedTargets.length} route(s) still queued — they keep serving their previously-live content (or the CSR shell, if never rendered) until a later round/cadence tick.`,
    );
  }

  // In-build validation gate (issue #53) — runs immediately after every
  // snapshot has been written, blocking the deploy (non-zero exit) on a
  // structural or non-staleness violation. Routes skipped this round because
  // the render budget ran out (issue #82) never got a snapshot written, so
  // they're excluded here rather than failing validation for something this
  // round never attempted. Scoped to this round's renderQueue only (issue
  // #94) — copied-forward routes are byte-identical to what already passed
  // this same gate in an earlier round (or the pre-incremental pipeline), so
  // re-validating them every round is pure waste that grows unboundedly as
  // the copied-forward set accumulates.
  const validationTargets = selectValidationTargets(renderQueue, skippedTargets);
  const validationIssues: string[] = [];
  await runPool(validationTargets, PRERENDER_CONCURRENCY, async (target) => {
    validationIssues.push(...(await validateTarget(target)));
  });
  if (validationIssues.length > 0) {
    for (const issue of validationIssues) {
      console.error(`prerender: validation failed — ${issue}`);
    }
    throw new Error(
      `prerender: ${validationIssues.length} snapshot validation issue(s) — see errors above`,
    );
  }
  console.log(`prerender: validated ${validationTargets.length} snapshot(s), no issues found`);

  // Round-state marker (issue #83): built from this round's actual outcome
  // and committed to the Vercel-git-connected production branch, whose push
  // is what triggers any later round's build (issue #84/#89 — see the
  // comment below). `status` already accounts for the chain-depth cap and
  // zero-progress abort so the committed marker is truthful. A failure here
  // (bad token, protected branch,
  // transient GitHub 5xx) must not fail the whole build — every snapshot
  // was already rendered and passed the validation gate above, so the
  // deploy is good; the only cost of a lost marker commit is this round's
  // progress being invisible to the next build's resume logic, which then
  // just starts a fresh burst (see resolveRoundContext's missing-marker
  // fallback) rather than resuming — degraded, not broken.
  const marker = buildRoundMarker(
    burstId,
    round,
    { newlyRendered, copiedForward, queueRemaining: skippedTargets.length },
    new Date(),
  );
  // Chaining (issue #84, fixed in #89, gated in #101): the branch push
  // inside commitRoundMarker is the chain's sole continuation trigger — the
  // production branch is Vercel-git-connected, so advancing its ref alone
  // triggers the next round's build. No separate Deploy Hook fire happens
  // here. Only push when shouldCommitRoundMarker(marker) says a round is
  // actually `continuing` — pushing a `done` marker has nothing left to
  // resume, yet the push itself still triggers a fresh Vercel build (any
  // push does), which starts a brand-new burst that (home routes never
  // classify `unchanged` — see classifyTarget) reliably finishes `done`
  // again, forever. That self-sustaining loop is what shipped overnight
  // (issue #101) before this gate existed. If the commit is skipped or
  // fails, the chain simply resumes via the next 6-hourly cron tick instead
  // of self-triggering (degraded, not broken — same fallback as any other
  // lost marker commit).
  if (shouldCommitRoundMarker(marker)) {
    try {
      await commitRoundMarker(marker);
    } catch (error) {
      console.error('prerender: failed to commit round marker — deploy proceeds anyway:', error);
    }
  }
  logZeroProgressAbort(marker);
}

const isMainModule =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMainModule) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
