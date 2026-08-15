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
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';
import { chromium, type Page } from 'playwright';
import { preview, type PreviewServer } from 'vite';
import type { EventData } from '../src/components/EventCard';
import {
  GITHUB_API_BASE_URL,
  LOCALE_URL_PREFIX_CODES,
  LOCALES,
  PRERENDER_CHAIN_GITHUB_REPO,
  PRODUCTION_ORIGIN,
  ROUTES,
  SEO_HREFLANG_CODES,
} from '../src/constants';
import { localizedPath } from '../src/lib/urlLocale';
import { compareEventStaleness, parseSnapshotHtml, validateSnapshotStructure } from '../src/lib/seoValidation';
import { createBudgetedCursor, prioritizeRenderQueue } from '../src/lib/prerenderQueue';
import {
  buildRoundMarker,
  parseRoundMarker,
  resolveRoundContext,
  serializeRoundMarker,
  type RoundMarker,
} from '../src/lib/prerenderChain';
import { PRERENDER_BACKEND_TARGET } from '../vite.config';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIST_DIR = path.resolve(__dirname, '../dist');
const API_ORIGIN = PRERENDER_BACKEND_TARGET;
const NAV_TIMEOUT_MS = 30_000;
const CONTENT_READY_TIMEOUT_MS = 15_000;
// Targets run through a bounded pool of pages rather than one at a time —
// with a growing published-event catalog (three locale variants each), a
// fully sequential run risks Vercel's Hobby-plan 45-minute build cap (see
// docs/research/prerendering-approach.md). Bounded, not unbounded, mirroring
// this repo's external-API fan-out convention (CLAUDE.md).
const PRERENDER_CONCURRENCY = 6;
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

interface PrerenderTarget {
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
  const script = dom.window.document.querySelector('script[type="application/ld+json"]');
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
          code === 'x-default'
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
  lines.push('', `Sitemap: ${PRODUCTION_ORIGIN}/sitemap.xml`);
  return lines.join('\n') + '\n';
}

/** dist-relative output file for a locale-prefixed URL — mirrors how Vercel's
 * static file server resolves a directory path to its index.html. */
function outputFilePath(bare: string, locale: string): string {
  const localized = localizedPath(bare, locale);
  const relDir = localized === '/' ? '' : localized;
  return path.join(DIST_DIR, relDir, 'index.html');
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
  await page.waitForSelector('link[rel="canonical"]', {
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
 * builds off Vercel. */
async function commitRoundMarker(marker: RoundMarker): Promise<void> {
  const token = process.env.GH_PRERENDER_CHAIN_TOKEN;
  const branch = process.env.VERCEL_GIT_COMMIT_REF;
  if (!token || !branch) {
    console.log(
      'prerender: GH_PRERENDER_CHAIN_TOKEN/VERCEL_GIT_COMMIT_REF not set — skipping round-marker commit (not a Vercel build)',
    );
    return;
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
}

async function main(): Promise<void> {
  // Round-state marker (issue #83): read back whatever VERCEL_GIT_COMMIT_MESSAGE
  // carries from the tip commit at build start, to determine which burst/round
  // this build continues (or starts fresh) — see src/lib/prerenderChain.ts.
  const existingMarker = parseRoundMarker(process.env.VERCEL_GIT_COMMIT_MESSAGE);
  const { burstId, round } = resolveRoundContext(existingMarker, new Date());
  console.log(
    `prerender: round ${round} of burst ${burstId}${existingMarker?.status === 'continuing' ? ' (resumed)' : ' (new)'}`,
  );

  const candidates = await fetchPrerenderCandidates();
  const targets = buildTargets(candidates);

  const buildTimestamp = new Date().toISOString();
  await writeFile(
    path.join(DIST_DIR, 'sitemap.xml'),
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
  const staleFallbackTargets = new Set<PrerenderTarget>();
  for (const { target, unchanged, liveHtml } of classification) {
    if (unchanged && liveHtml !== null) {
      const outPath = outputFilePath(target.bare, target.locale);
      await mkdir(path.dirname(outPath), { recursive: true });
      await writeFile(outPath, liveHtml, 'utf-8');
      copiedForward++;
    } else if (liveHtml !== null) {
      // Needs a fresh render, but a live page exists — write it now as a
      // provisional stale-but-real fallback (issue #82); snapshotTarget's
      // writeFile below overwrites it in place if/when this route is
      // actually reached within the render budget. Writing eagerly rather
      // than holding every needs-render route's full live HTML in memory
      // for the whole pass — with a growing catalog that's potentially
      // hundreds of routes' worth of HTML kept around just in case the
      // budget runs out before reaching them.
      const outPath = outputFilePath(target.bare, target.locale);
      await mkdir(path.dirname(outPath), { recursive: true });
      await writeFile(outPath, liveHtml, 'utf-8');
      staleFallbackTargets.add(target);
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
    const browser = await chromium.launch();
    try {
      server = await preview({ preview: { port: 0, strictPort: false }, logLevel: 'warn' });
      const previewOrigin = server.resolvedUrls?.local[0]?.replace(/\/$/, '');
      if (!previewOrigin) {
        throw new Error('prerender: vite preview server did not resolve a local URL');
      }

      const resolvedPreviewOrigin = previewOrigin;
      const failures: { target: PrerenderTarget; error: unknown }[] = [];
      // Hard 10-minute (overridable) cap on this pool only (issue #82) — see
      // RENDER_BUDGET_MS. Started once the preview server/browser are up, so
      // the budget covers actual render time, not startup.
      const deadline = Date.now() + RENDER_BUDGET_MS;
      const cursor = createBudgetedCursor(renderQueue.length, deadline);
      async function worker(): Promise<void> {
        const page = await browser.newPage();
        try {
          for (;;) {
            const i = cursor.next();
            if (i === null) break;
            const target = renderQueue[i];
            try {
              await snapshotTarget(page, resolvedPreviewOrigin, target);
              newlyRendered++;
            } catch (error) {
              failures.push({ target, error });
            }
          }
        } finally {
          await page.close();
        }
      }
      await Promise.all(
        Array.from({ length: Math.min(PRERENDER_CONCURRENCY, renderQueue.length) }, worker),
      );
      skippedTargets = cursor.remaining().map((i) => renderQueue[i]);

      if (failures.length > 0) {
        for (const { target, error } of failures) {
          console.error(
            `prerender: failed to render ${localizedPath(target.bare, target.locale)} —`,
            error,
          );
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
  // the budget ran out already has its last-known-good live page written
  // (eagerly, in the classification loop above), if one existed. A route
  // with no live page at all (never rendered before) has nothing on disk,
  // which falls through to the CSR shell via vercel.json's catch-all
  // rewrite rather than a build failure — see outputFilePath/vercel.json.
  const staleFallbackWritten = skippedTargets.filter((target) => staleFallbackTargets.has(target)).length;

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
  // round never attempted.
  const skippedTargetSet = new Set(skippedTargets);
  const validationTargets = targets.filter((target) => !skippedTargetSet.has(target));
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
  // and committed to the branch the Deploy Hook targets, advancing the git
  // ref before any later round re-fires the hook (issue #84, out of scope
  // here). `status` already accounts for the chain-depth cap and
  // zero-progress abort so the committed marker is truthful even before
  // hook-firing exists. A failure here (bad token, protected branch,
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
  try {
    await commitRoundMarker(marker);
  } catch (error) {
    console.error('prerender: failed to commit round marker — deploy proceeds anyway:', error);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
