/**
 * Build-time static-prerender step (issue #50) — added to, not replacing,
 * `vite build`. Boots the just-built dist/ under `vite preview`, drives it
 * with Playwright, and writes a fully-rendered HTML snapshot per route to
 * dist/, so the host serves real content to crawlers/link-unfurlers instead of
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
  APP_SHELL_FILENAME,
  BROWSE_PAGE_SIZE,
  CANONICAL_LINK_SELECTOR,
  CHAIN_STATE_PREFIX,
  CRAWLABLE_ASSETS_PATH,
  CRAWLABLE_ICON_PATHS,
  EXPLORE_PARAM,
  JSONLD_SCRIPT_SELECTOR,
  JSONLD_SCRIPT_TYPE,
  LOCALE_ET,
  LOCALE_KEY,
  LOCALE_URL_PREFIX_CODES,
  LOCALES,
  OG_FALLBACK_IMAGE_PATH,
  PRERENDER_CADENCE_GIT_BRANCH,
  PRERENDER_CHAIN_GITHUB_REPO,
  PRERENDER_DIAGNOSTIC_EVENT_MAX_LENGTH,
  PRERENDER_ERROR_SELECTOR,
  PRERENDER_READY_SELECTOR,
  PRODUCTION_ORIGIN,
  ROBOTS_TXT_FILENAME,
  ROUND_STATUS,
  ROUTES,
  SEO_HREFLANG_CODES,
  SEO_XDEFAULT_CODE,
  SITEMAP_FILENAME,
  SITEMAP_PATH,
  SORT_DEFAULT,
  CHANGE_DETECTION_CONCURRENCY,
  R2_PERSIST_CONCURRENCY,
  CHANGE_MARKER_JSONLD_FIELD,
  CONTENT_READY_TIMEOUT_MS,
  DEFAULT_RENDER_BUDGET_MINUTES,
  EVENT_DETAIL_RATE_LIMIT_PER_MINUTE,
  NAV_TIMEOUT_MS,
  PRERENDER_CONCURRENCY,
  RENDER_POOL_CONCURRENCY,
  PRERENDER_DIAGNOSTIC_MAX_EVENTS,
  RATE_GATE_SLACK_MS,
} from '../src/constants';
import { serializeJsonLd } from '../src/lib/jsonLd';
import { localizedPath } from '../src/lib/urlLocale';
import { githubRequest } from '../src/lib/githubRequest';
import { compareEventStaleness, parseSnapshotHtml, validateSnapshotStructure } from '../src/lib/seoValidation';
import { createBudgetedCursor, prioritizeRenderQueue } from '../src/lib/prerenderQueue';
import { deleteR2ObjectsByPrefix, getR2Object, putR2Object } from '../src/lib/r2ChainState';
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
  // Head index instead of Array.shift() — shift() is O(window) per call
  // (re-indexes every remaining element), so this makes eviction O(1)
  // amortized. Compacted back to the front once evicted entries dominate the
  // array so it doesn't grow unbounded over a long prerender run.
  private head = 0;

  constructor(
    private readonly maxPerWindow: number,
    private readonly windowMs: number,
  ) {}

  async acquire(): Promise<void> {
    for (;;) {
      const now = Date.now();
      while (
        this.head < this.timestamps.length &&
        now - this.timestamps[this.head] >= this.windowMs
      ) {
        this.head++;
      }
      if (this.head > 0 && this.head * 2 >= this.timestamps.length) {
        this.timestamps.splice(0, this.head);
        this.head = 0;
      }
      if (this.timestamps.length - this.head < this.maxPerWindow) {
        this.timestamps.push(now);
        return;
      }
      const waitMs = this.windowMs - (now - this.timestamps[this.head]) + RATE_GATE_SLACK_MS;
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
  // candidate.id feeds ROUTES.eventDetail(id) -> path.join(DIST_DIR, ...) for the
  // prerendered file's output path; a non-integer id (e.g. a traversal string from
  // a compromised backend) could write outside DIST_DIR, so it's runtime-checked
  // here rather than trusted from the response's declared `number` type.
  return body.events
    .filter((e) => Number.isInteger(e.id))
    .map((e) => ({ id: e.id, updatedAt: e.updated_at }));
}

function buildTargets(candidates: PrerenderCandidate[]): PrerenderTarget[] {
  const localeCodes = LOCALES.map((l) => l.code);
  const targets: PrerenderTarget[] = [];
  for (const locale of localeCodes) {
    targets.push({ bare: ROUTES.home, locale });
    // Appended right after home, never at index 0 — the live audit
    // (seoAudit.ts's parseSitemapLastmod) reads sitemap freshness off the
    // *first* <lastmod> in the document, which depends on home staying
    // first (issue #236). No eventId/updatedAt, same shape as home — see
    // classifyTarget's doc comment for why that alone makes it always
    // render fresh, no copy-forward.
    targets.push({ bare: ROUTES.explore, locale });
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

/** Embeds `marker` under CHANGE_MARKER_JSONLD_FIELD in `document`'s single
 * JSON-LD script (issue #80), at render time — after the page's real
 * content (including its JSON-LD) has already been captured. Leaves
 * `document` unchanged if there's no JSON-LD script or its body doesn't
 * parse; the in-build validation gate below is what actually catches/blocks
 * on that. In-place (mutates `document`, no JSDOM of its own) so
 * snapshotTarget's fresh-render path can share one JSDOM parse/serialize
 * with stripBakedThemeAttrInPlace instead of two (Big-O audit #5, Tier 4). */
function embedChangeMarkerInPlace(document: Document, marker: string): void {
  const script = document.querySelector(JSONLD_SCRIPT_SELECTOR);
  if (script) {
    try {
      const data = JSON.parse(script.textContent ?? '{}') as Record<string, unknown>;
      data[CHANGE_MARKER_JSONLD_FIELD] = marker;
      script.textContent = serializeJsonLd(data);
    } catch {
      // Malformed JSON-LD — leave untouched, validateTarget() catches it.
    }
  }
}

/** Rewrites `html`'s built-asset `<head>` references (`<script type="module">`,
 * `<link rel="stylesheet">`, `<link rel="modulepreload">` — anything Vite
 * emits under CRAWLABLE_ASSETS_PATH) to match `shellHtml`'s, in place.
 *
 * Exists because a copied-forward snapshot (issue #80/#82) is a byte-for-byte
 * capture of a *previous* build's rendered HTML, complete with that build's
 * content-hashed asset filenames. Vite mints new hashes on every source
 * change, so those references go dead the moment the next build ships —
 * and because copy-forward has no staleness signal of its own (its whole
 * point is "nothing about this route changed"), the dead references would
 * otherwise persist silently across arbitrarily many future deploys.
 * Cloudflare doesn't 404 the request either: `functions/[[path]].ts`'s SPA
 * fallback serves `app-shell.html` (200, `text/html`) for any unmatched
 * path, which a browser then rejects as a stylesheet/module script under
 * strict MIME sniffing — no CSS, and React never mounts.
 *
 * `shellHtml` must be `dist/app-shell.html` — the pristine, never-prerendered
 * Vite output — not `dist/index.html`, which prerender itself overwrites
 * with the home-route snapshot partway through the same round.
 *
 * Throws if `shellHtml` carries zero asset nodes: that means the caller
 * passed the wrong document, and a silent no-op rewrite here would just
 * reintroduce the bug it exists to fix. */
function isAssetNode(node: Element): boolean {
  const ref = node.getAttribute('src') ?? node.getAttribute('href') ?? '';
  return ref.startsWith(CRAWLABLE_ASSETS_PATH);
}

// Caches the one shell document's parsed asset nodes across every call in a
// round (a copy-forward/stale-fallback round can call rewriteSnapshotAssetRefs
// thousands of times against the same, invariant shellHtml) — re-parsing an
// identical string with a fresh JSDOM per call would be pure waste at that
// scale. Keyed on shellHtml itself rather than assuming "one call per round",
// so a shellHtml change (e.g. between test cases) still gets a fresh parse.
let shellAssetNodeCache: { shellHtml: string; nodes: Element[] } | null = null;

function getShellAssetNodes(shellHtml: string): Element[] {
  if (shellAssetNodeCache !== null && shellAssetNodeCache.shellHtml === shellHtml) {
    return shellAssetNodeCache.nodes;
  }
  const shellDom = new JSDOM(shellHtml);
  const nodes = [...shellDom.window.document.head.querySelectorAll('script, link')].filter(isAssetNode);
  shellAssetNodeCache = { shellHtml, nodes };
  return nodes;
}

// In-place — mutates `document`, no JSDOM/serialize of its own, so
// finalizeSnapshotHtml can share one JSDOM parse/serialize with
// stripBakedThemeAttrInPlace instead of chaining two (Big-O audit #5, Tier
// 4). The exported, string-in-string-out rewriteSnapshotAssetRefs below
// wraps this for its own standalone callers/tests.
function rewriteSnapshotAssetRefsInPlace(document: Document, shellHtml: string): void {
  const shellAssetNodes = getShellAssetNodes(shellHtml);
  if (shellAssetNodes.length === 0) {
    throw new Error(
      'rewriteSnapshotAssetRefs: shell HTML has zero /assets/ references — wrong document passed as shellHtml?',
    );
  }

  const head = document.head;
  const staleAssetNodes = [...head.querySelectorAll('script, link')].filter(isAssetNode);
  // Anchor on the node right after the stale block (captured before removal,
  // so it's untouched by it) — `insertBefore(node, null)` appends at the end,
  // which is exactly the "no stale nodes" case (append to <head>) the plan
  // calls for. Fixing the anchor once, rather than re-deriving it per
  // inserted node, keeps the shell's nodes in their original relative order.
  const anchor = staleAssetNodes.length > 0 ? staleAssetNodes[staleAssetNodes.length - 1].nextSibling : null;
  for (const node of staleAssetNodes) node.remove();
  for (const shellNode of shellAssetNodes) {
    const imported = document.importNode(shellNode, true);
    head.insertBefore(imported, anchor);
  }
}

export function rewriteSnapshotAssetRefs(html: string, shellHtml: string): string {
  const dom = new JSDOM(html);
  rewriteSnapshotAssetRefsInPlace(dom.window.document, shellHtml);
  return dom.serialize();
}

/** Strips a baked-in `data-theme` attribute off `html`'s `<html>` element,
 * leaving every other attribute (`lang`, `data-rh`, …) untouched. A snapshot
 * is captured in the build browser, which has no `theme_override` in
 * localStorage — the inline pre-paint script (index.html) resolves that to
 * whatever the build machine's OS `prefers-color-scheme` happens to be and
 * bakes it into `document.documentElement.dataset.theme` before
 * `page.content()` ever reads the DOM back. Shipping that baked value means
 * every visitor sees the build machine's theme, frozen, until JS re-resolves
 * it at runtime — the theme-revert-on-refresh bug this fixes. Leaving the
 * attribute absent instead falls through to the dark origin palette
 * (`:root` in index.css) only until the pre-paint script (now unblocked by
 * the CSP hash — see src/lib/csp.ts) sets the real value before first paint.
 * Idempotent — a second call on already-stripped HTML is a no-op. */
function stripBakedThemeAttrInPlace(document: Document): void {
  document.documentElement.removeAttribute('data-theme');
}

export function stripBakedThemeAttr(html: string): string {
  const dom = new JSDOM(html);
  stripBakedThemeAttrInPlace(dom.window.document);
  return dom.serialize();
}

/** Single choke point for every snapshot write, so a future write site can't
 * skip stripBakedThemeAttr by accident. `shellHtml` is optional: the
 * fresh-render write site (snapshotTarget) has no stale asset refs to
 * rewrite (the page was just rendered against the current build), while
 * both copy-forward write sites in main() do. One JSDOM parse/serialize for
 * both steps, not two chained string round trips (Big-O audit #5, Tier 4). */
function finalizeSnapshotHtml(html: string, shellHtml?: string): string {
  const dom = new JSDOM(html);
  if (shellHtml !== undefined) rewriteSnapshotAssetRefsInPlace(dom.window.document, shellHtml);
  stripBakedThemeAttrInPlace(dom.window.document);
  return dom.serialize();
}

/** A resumed round's accumulated manifest entries (issue #367) — keyed
 * `${locale}:${eventId}` so home/explore targets (no eventId) can never
 * form a key. */
export interface ChainStateIndexEntry {
  resolvedAtRound: number;
}
export type ChainStateIndex = Record<string, ChainStateIndexEntry>;

/** R2 object keys are plain strings with no escaping of `:`/`.` the way a
 * git ref would need — but burstId is an ISO timestamp (resolveRoundStart),
 * and some S3-compatible tooling/CLIs choke on colons in a key path, so it
 * gets a display-only substitution here. RoundMarker.burstId itself (the
 * git-committed value other rounds compare against) is never touched. */
export function sanitizeBurstIdForR2(burstId: string): string {
  return burstId.replace(/[:.]/g, '-');
}

function chainStatePrefix(sanitizedBurstId: string): string {
  return `${CHAIN_STATE_PREFIX}${sanitizedBurstId}/`;
}

export function chainStateContentKey(sanitizedBurstId: string, locale: string, eventId: number): string {
  return `${chainStatePrefix(sanitizedBurstId)}targets/${locale}-${eventId}.html`;
}

export function chainStateIndexKey(sanitizedBurstId: string): string {
  return `${chainStatePrefix(sanitizedBurstId)}index.json`;
}

/** Round-start read (issue #367) — merges onto whatever an earlier round in
 * this same burst already accumulated, so the single end-of-round PUT below
 * never clobbers it. A missing/corrupt index (no manifest yet, or a
 * genuinely malformed one) degrades to "start fresh", same fail-open
 * posture as every other R2 read in this path. */
export function parseChainStateIndex(raw: string | null): ChainStateIndex {
  if (raw === null) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as ChainStateIndex;
    }
    console.error('prerender: chain-state index was not a plain object — starting fresh:', parsed);
  } catch (error) {
    console.error('prerender: chain-state index JSON parse failed — starting fresh:', error);
  }
  return {};
}

/** Shared by both manifest write points (issue #367's copy-forward branch
 * and successful-render branch) — a target only earns a manifest entry once
 * finalized HTML is in hand, and only when it carries an eventId (home/
 * explore never do). Never called for the stale-fallback write: that
 * content isn't done, so it must not look resolved to a later round's
 * read-side skip-refetch (#368). */
export async function persistChainStateTarget(
  sanitizedBurstId: string,
  round: number,
  target: PrerenderTarget,
  finalizedHtml: string,
  index: ChainStateIndex,
): Promise<void> {
  if (target.eventId === undefined) return;
  const wrote = await putR2Object(
    chainStateContentKey(sanitizedBurstId, target.locale, target.eventId),
    finalizedHtml,
    'text/html',
  );
  // Only record the index entry once the content object is actually in the
  // bucket — an index entry with no matching content object would tell a
  // later round's read-side (#368) this target is resolved when it isn't.
  if (wrote) {
    index[`${target.locale}:${target.eventId}`] = { resolvedAtRound: round };
  }
}

/** End-of-round manifest write (issue #367), placed next to
 * commitRoundMarker's call site since both fire off the same "this round
 * just finished" event. A `done` round (shouldCommit false) has nothing
 * left for a later round to resume, so its manifest is deleted outright
 * rather than given one final index write nobody will ever read back —
 * CHAIN_STATE_LIFECYCLE_DAYS is only the crash backstop for a burst whose
 * `done` round never got this far. */
export async function finalizeChainState(
  sanitizedBurstId: string,
  index: ChainStateIndex,
  shouldCommit: boolean,
): Promise<void> {
  if (shouldCommit) {
    await putR2Object(chainStateIndexKey(sanitizedBurstId), JSON.stringify(index), 'application/json');
  } else {
    await deleteR2ObjectsByPrefix(chainStatePrefix(sanitizedBurstId));
  }
}

/** Reads the change-detection marker back off a rendered snapshot's JSON-LD
 * (issue #80) — used to read the currently-live production page during
 * change detection. A targeted scan of the first JSON-LD script body rather
 * than a full DOM parse (Big-O audit M13): change detection runs once per
 * target and would otherwise parse every page twice (here, then again in
 * finalizeSnapshotHtml). Reads the same first script parseSnapshotHtml (the
 * validation gate) does, so the two readers agree. */
const JSONLD_SCRIPT_BODY_RE = new RegExp(
  `<script[^>]*type=["']${JSONLD_SCRIPT_TYPE.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}["'][^>]*>([\\s\\S]*?)</script>`,
  'i',
);

function extractChangeMarker(html: string): string | null {
  const body = JSONLD_SCRIPT_BODY_RE.exec(html)?.[1];
  if (body === undefined) return null;
  try {
    const jsonLd: unknown = JSON.parse(body);
    if (jsonLd && typeof jsonLd === 'object') {
      const marker = (jsonLd as Record<string, unknown>)[CHANGE_MARKER_JSONLD_FIELD];
      if (typeof marker === 'string') return marker;
    }
  } catch {
    // Malformed JSON-LD — no marker, exactly like parseSnapshotHtml's undefined entry.
  }
  return null;
}

export interface ChangeDetectionResult {
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
   * (null here) falls through to the CSR shell via `functions/[[path]].ts`'s
   * SPA fallback instead. */
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

/** A resolved-in-manifest target — narrows `eventId` to non-undefined so
 * fetchResolvedTarget never needs a runtime check for what
 * partitionByChainState already guarantees. */
export type ResolvedTarget = PrerenderTarget & { eventId: number };

/** Round-2+ read-side split (issue #368) — every event target whose
 * `locale:eventId` key is already in the manifest index skips
 * classifyTarget's production fetch entirely; home/explore targets (no
 * eventId, per ChangeDetectionResult's doc comment) and any event target
 * the index hasn't resolved yet fall through to today's classifyTarget path
 * unchanged. */
export function partitionByChainState(
  targets: PrerenderTarget[],
  index: ChainStateIndex,
): { resolved: ResolvedTarget[]; unresolved: PrerenderTarget[] } {
  const resolved: ResolvedTarget[] = [];
  const unresolved: PrerenderTarget[] = [];
  for (const target of targets) {
    const key = target.eventId === undefined ? null : `${target.locale}:${target.eventId}`;
    if (key !== null && Object.prototype.hasOwnProperty.call(index, key)) {
      resolved.push(target as ResolvedTarget);
    } else {
      unresolved.push(target);
    }
  }
  return { resolved, unresolved };
}

/** Read path (issue #368) — round-2+ substitute for classifyTarget on a
 * target the manifest index already resolved earlier in this burst: reads
 * its finalized snapshot HTML out of R2 instead of re-fetching production.
 * Returns the same ChangeDetectionResult shape classifyTarget produces
 * (`unchanged: true`, `liveHtml` set) so every downstream consumer — the
 * copy-forward write loop, prioritizeRenderQueue's `!unchanged` filter, the
 * sitemap builder — needs no change to tell the two apart. A content-object
 * read miss (evicted, corrupt, or a stale index entry) falls back to a
 * fresh classifyTarget fetch for this one target only, exactly like an
 * unresolved target — never blocks or fails the round. */
export async function fetchResolvedTarget(
  sanitizedBurstId: string,
  target: ResolvedTarget,
  manifestHits: Set<PrerenderTarget>,
): Promise<ChangeDetectionResult> {
  const html = await getR2Object(chainStateContentKey(sanitizedBurstId, target.locale, target.eventId));
  if (html === null) return classifyTarget(target);
  // A burst can span several rounds (resolveRoundStart/CHAIN_MAX_ROUNDS),
  // and fetchPrerenderCandidates() re-fetches Event.updated_at fresh every
  // round — so the manifest's cached snapshot, written whichever earlier
  // round first resolved this target, can have gone stale in the meantime.
  // Re-run the same marker diff classifyTarget performs against a live
  // fetch (extractChangeMarker/target.updatedAt) before trusting it as
  // `unchanged`; a mismatch falls back to a fresh production fetch exactly
  // like a manifest miss, rather than serving stale content forward.
  if (target.updatedAt === undefined || extractChangeMarker(html) !== target.updatedAt) {
    return classifyTarget(target);
  }
  // Marks this target as actually sourced from the manifest (as opposed to
  // either fallback classifyTarget call above) so main()'s copy-forward
  // write loop knows not to re-PUT it (issue #368).
  manifestHits.add(target);
  return { target, unchanged: true, liveHtml: html };
}

/** Escapes the five XML predefined entities. `id` (sitemap targets are only
 * ever numeric event ids or static bare paths) can't carry these, but
 * `lastmod` is `Event.updated_at` straight from the API (OWASP audit G-12) —
 * a DB timestamp today, but nothing here has ever asserted that shape holds
 * against a compromised backend. Applied to every interpolated value below
 * as defense-in-depth, not just the ones currently reachable by untrusted
 * input. */
function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
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
      const loc = escapeXml(`${PRODUCTION_ORIGIN}${localizedPath(target.bare, target.locale)}`);
      const alternates = SEO_HREFLANG_CODES.map((code) => {
        const href =
          code === SEO_XDEFAULT_CODE
            ? `${PRODUCTION_ORIGIN}${target.bare}`
            : `${PRODUCTION_ORIGIN}${localizedPath(target.bare, code)}`;
        return `    <xhtml:link rel="alternate" hreflang="${code}" href="${escapeXml(href)}"/>`;
      }).join('\n');
      const lastmod = escapeXml(String(target.updatedAt ?? buildTimestamp));
      return `  <url>\n    <loc>${loc}</loc>\n    <lastmod>${lastmod}</lastmod>\n${alternates}\n  </url>`;
    })
    .join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n${urlEntries}\n</urlset>\n`;
}

/** robots.txt (issue #51) — inverse-allowlist shape (`Disallow: /` first,
 * then explicit `Allow:`s) so a new authenticated route added later is
 * excluded by default, with no robots.txt edit required to keep it that way.
 * Non-route files served straight out of dist/ (the sitemap itself, the OG
 * fallback image, the SPA's built JS/CSS) fall under that same default-deny
 * and need their own explicit `Allow:` or Google can't fetch them — this bit
 * sitemap.xml itself (Google Search Console: "Couldn't fetch") until these
 * three lines were added. */
export function buildRobotsTxt(): string {
  const lines = ['User-agent: *', 'Disallow: /', 'Allow: /$', 'Allow: /events/'];
  // Not $-anchored (unlike the home-route `Allow: /$` above) — a filtered
  // Explore URL (`/explore?category=…`) must stay crawlable per the map's
  // canonical-alone crawl-control decision (issue #236): no Disallow on
  // query strings, no param-conditional noindex.
  lines.push(`Allow: ${ROUTES.explore}`);
  for (const code of LOCALE_URL_PREFIX_CODES) {
    lines.push(`Allow: /${code}$`, `Allow: /${code}/events/`, `Allow: /${code}${ROUTES.explore}`);
  }
  lines.push(`Allow: ${SITEMAP_PATH}`, `Allow: ${OG_FALLBACK_IMAGE_PATH}`, `Allow: ${CRAWLABLE_ASSETS_PATH}`);
  for (const iconPath of CRAWLABLE_ICON_PATHS) lines.push(`Allow: ${iconPath}`);
  lines.push('', `Sitemap: ${PRODUCTION_ORIGIN}${SITEMAP_PATH}`);
  return lines.join('\n') + '\n';
}

/** dist-relative output file for a locale-prefixed URL — mirrors how a static
 * file server resolves a directory path to its index.html. */
function outputFilePath(bare: string, locale: string): string {
  const localized = localizedPath(bare, locale);
  const relDir = localized === '/' ? '' : localized;
  return path.join(DIST_DIR, relDir, 'index.html');
}

async function launchBrowser(): Promise<Browser> {
  return chromium.launch();
}

/** Rolling buffer of a page's recent console/pageerror/requestfailed
 * activity (issue #86 investigation) — three consecutive `waitForSelector`
 * timeout theories (single-process contention, then a flat timeout bump)
 * each failed to explain the next production run, always on the exact same
 * routes including the static, no-fetch Landing page.
 * Rather than guess a fourth time, capture what the page itself was doing
 * when a render times out, so the next failure's log says what actually
 * happened instead of just that it didn't. Attached once per page (workers
 * reuse one page across many targets), capped so a long-lived page's buffer
 * can't grow unbounded. */
function attachPageDiagnostics(page: Page): () => string[] {
  const events: string[] = [];
  const record = (line: string) => {
    events.push(line);
    if (events.length > PRERENDER_DIAGNOSTIC_MAX_EVENTS) events.shift();
  };
  page.on('console', (msg) => record(`console.${msg.type()}: ${msg.text().slice(0, PRERENDER_DIAGNOSTIC_EVENT_MAX_LENGTH)}`));
  page.on('pageerror', (err) => record(`pageerror: ${String(err).slice(0, PRERENDER_DIAGNOSTIC_EVENT_MAX_LENGTH)}`));
  page.on('requestfailed', (req) =>
    record(`requestfailed: ${req.url()} — ${req.failure()?.errorText ?? 'unknown'}`),
  );
  return () => [...events];
}

async function snapshotTarget(
  page: Page,
  previewOrigin: string,
  target: PrerenderTarget,
): Promise<string> {
  // Re-keyed on eventId, not `bare !== ROUTES.home` (issue #236) — /explore
  // never calls GET /events/{id}, so it must not consume this budget either.
  if (target.eventId !== undefined) {
    await eventDetailRateGate.acquire();
  }
  const url = `${previewOrigin}${localizedPath(target.bare, target.locale)}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT_MS });
  const isExplore = target.bare === ROUTES.explore;
  // Landing and /events/:id are `indexable` (useSeoMeta) only once real
  // content has loaded, so waiting for the canonical link this hook emits is
  // a reliable "real content is in the DOM" signal for both. /explore is
  // different (issue #236): readiness must be decoupled from indexability —
  // a query that resolves to an error is real, settled content that must
  // still get snapshotted (so the error marker check below can fail the
  // build loudly) rather than left to time out here, but useSeoMeta's
  // `indexable` is never true on error. So /explore waits on its own
  // PRERENDER_READY_SELECTOR (Explore.tsx sets it on isSuccess/isError, never
  // isLoading) instead of the canonical-link selector.
  // `state: 'attached'`, not the default 'visible' — neither marker has a
  // CSS box, so the default visibility check would time out even once
  // rendered.
  await page.waitForSelector(isExplore ? PRERENDER_READY_SELECTOR : CANONICAL_LINK_SELECTOR, {
    state: 'attached',
    timeout: CONTENT_READY_TIMEOUT_MS,
  });
  if (isExplore && (await page.$(PRERENDER_ERROR_SELECTOR)) !== null) {
    // The query itself errored — fail loudly rather than silently shipping a
    // noindex page (issue #236): routed through the same failures[]/throw
    // path every other render failure takes, below.
    throw new Error(`prerender: /explore query errored for ${localizedPath(target.bare, target.locale)}`);
  }
  const html = await page.content();
  // One JSDOM parse/serialize for both steps below, not two chained ones
  // (Big-O audit #5, Tier 4) — mirrors finalizeSnapshotHtml's own merge.
  const dom = new JSDOM(html);
  if (target.eventId !== undefined && target.updatedAt !== undefined) {
    embedChangeMarkerInPlace(dom.window.document, target.updatedAt);
  }
  stripBakedThemeAttrInPlace(dom.window.document);
  const finalized = dom.serialize();
  const outPath = outputFilePath(target.bare, target.locale);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, finalized, 'utf-8');
  return finalized;
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

/** Bounded fire-and-forget: `run(task)` starts `task` once fewer than
 * `limit` are in flight and returns its promise (never rejects to the caller
 * — failures resolve, since every caller here fails open). `drain()` awaits
 * everything scheduled so far. */
function createLimiter(limit: number): {
  run: (task: () => Promise<void>) => void;
  drain: () => Promise<void>;
} {
  let active = 0;
  const waiting: (() => void)[] = [];
  const all: Promise<void>[] = [];
  async function execute(task: () => Promise<void>): Promise<void> {
    if (active >= limit) await new Promise<void>((resolve) => waiting.push(resolve));
    active++;
    try {
      await task();
    } catch {
      // Fail open — see doc comment.
    } finally {
      active--;
      waiting.shift()?.();
    }
  }
  return {
    run: (task) => {
      all.push(execute(task));
    },
    drain: async () => {
      await Promise.allSettled(all);
    },
  };
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
 * the published-event catalog grows enough to threaten Cloudflare Pages'
 * build cap (see PRERENDER_CONCURRENCY above). Returns
 * one message per violation, prefixed with the target's path — never
 * throws for a validation failure itself. */
/** Live count backing the /explore validator's >=3-items check (issue #236)
 * — same unfiltered, first-page query Explore.tsx's default request builds
 * (DEFAULT_EXPLORE_FILTERS + offset 0), but limit=1: only the response's
 * `total` is read, not the events themselves. Prerendering is always
 * anonymous (Playwright never signs in), and Explore.tsx's `gridItems`
 * always drops exactly one fetched event to make room for the persistent
 * upsell card (`visibleEvents = events.slice(0, events.length - 1)`) — so
 * the snapshot's `itemListElement` (built from that same `visibleEvents`,
 * per buildExploreItemListJsonLd's caller) is always one shorter than the
 * raw catalog count. Adjusting for that here (not in assertListJsonLd,
 * which stays a generic, business-rule-free structural check) is what lets
 * a catalog of exactly 3 events correctly render a 2-item list without
 * tripping the >=3 check — comparing against the unadjusted `total` would
 * make every such catalog fail the build on a UI layout decision, not an
 * actual builder regression. `min(total, BROWSE_PAGE_SIZE)` mirrors
 * `events.length` itself only ever reflecting the first fetched page.
 * `undefined` on any fetch problem (best-effort — see assertListJsonLd's
 * doc comment on what omitting this does to the check). */
export async function fetchLiveExploreCount(locale: string): Promise<number | undefined> {
  const params = new URLSearchParams();
  params.set(EXPLORE_PARAM.forYou, 'false');
  params.set(EXPLORE_PARAM.sort, SORT_DEFAULT);
  params.set(EXPLORE_PARAM.limit, '1');
  params.set(EXPLORE_PARAM.offset, '0');
  params.set(LOCALE_KEY, locale);
  try {
    const res = await fetch(`${API_ORIGIN}/explore?${params.toString()}`);
    if (!res.ok) return undefined;
    const body = (await res.json()) as { total: number };
    return Math.max(Math.min(body.total, BROWSE_PAGE_SIZE) - 1, 0);
  } catch {
    return undefined;
  }
}

async function validateTarget(
  target: PrerenderTarget,
  renderedHtml: string | undefined,
  checkStaleness: boolean,
): Promise<string[]> {
  const html = renderedHtml ?? (await readFile(outputFilePath(target.bare, target.locale), 'utf-8'));
  const parsed = parseSnapshotHtml(html);
  const kind = target.bare === ROUTES.home ? 'website' : target.bare === ROUTES.explore ? 'list' : 'event';

  const liveItemCount = kind === 'list' ? await fetchLiveExploreCount(target.locale) : undefined;

  const issues = validateSnapshotStructure(parsed, {
    kind,
    locale: target.locale,
    originPrefix: PRODUCTION_ORIGIN,
    liveItemCount,
  }).map((issue) => `structural: ${issue}`);

  // Live-API staleness comparison runs once per event (Big-O audit M15) —
  // `checkStaleness` is set by main() for the default-locale sibling, or for
  // one stand-in sibling when the default locale isn't being validated: all locale variants of an event render seconds apart
  // from the same DB row, so a per-locale re-fetch tripled the API calls
  // (and rate-gate budget) for near-zero extra signal. Structural checks
  // above still run for every locale.
  if (target.eventId !== undefined && checkStaleness) {
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

/** Shared GitHub Git Data API request for everything in this chain-marker
 * flow (commitRoundMarker's ref/tree/commit calls, fetchBuildCommitMessage's
 * commit-message lookup) — one place to keep the auth/User-Agent shape
 * consistent rather than re-deriving it at each call site. */
function chainGithubRequest(token: string, path: string, init?: RequestInit): Promise<Response> {
  return githubRequest(PRERENDER_CHAIN_GITHUB_REPO, path, token, 'event-radar-prerender-chain', init);
}

/** Commits `marker` to the branch the Deploy Hook targets (issue #83;
 * extended to Cloudflare Pages under #346), advancing the git ref so a later
 * chained round (issue #84) can re-fire the hook against a genuinely new
 * version rather than colliding with the platform's same-version-
 * cancellation behavior. Uses the GitHub Git Data API — not a local
 * `git push` — since the build environment's checkout has no guaranteed
 * push credentials; mirrors the removed api/seo-audit.ts's plain-fetch
 * GH_ISSUE_TOKEN pattern rather than adding an SDK dependency. The new
 * commit reuses the branch tip's tree unchanged (no file diff — only the
 * marker embedded in the message changes), so this is effectively an empty
 * commit. No-ops with a log line (not a build failure) when
 * GH_PRERENDER_CHAIN_TOKEN/branch aren't set, e.g. local/dev builds —
 * returns `false` in that case (as opposed to throwing, its failure path) to
 * distinguish "nothing was committed" from "the commit succeeded". main()
 * only calls this when shouldCommitRoundMarker(marker) says the round is
 * `continuing` (issue #101 — see that function's doc comment for why a
 * `done` round must never reach this call). The advanced ref is this
 * chain's sole continuation trigger (issue #89): the production branch is
 * git-connected, so this push alone fires the next round's build — no
 * separate Deploy Hook call is needed or made. */
async function commitRoundMarker(marker: RoundMarker): Promise<boolean> {
  const token = process.env.GH_PRERENDER_CHAIN_TOKEN;
  const branch = process.env.CF_PAGES_BRANCH;
  if (!token || !branch) {
    console.log(
      'prerender: GH_PRERENDER_CHAIN_TOKEN/CF_PAGES_BRANCH not set — skipping round-marker commit (not a Cloudflare Pages build)',
    );
    return false;
  }

  const refRes = await chainGithubRequest(token, `/git/ref/heads/${branch}`);
  if (!refRes.ok) {
    throw new Error(
      `prerender: failed to read ref heads/${branch} — ${refRes.status} ${refRes.statusText}`,
    );
  }
  const parentSha = ((await refRes.json()) as { object: { sha: string } }).object.sha;

  const parentCommitRes = await chainGithubRequest(token, `/git/commits/${parentSha}`);
  if (!parentCommitRes.ok) {
    throw new Error(
      `prerender: failed to read parent commit ${parentSha} — ${parentCommitRes.status} ${parentCommitRes.statusText}`,
    );
  }
  const treeSha = ((await parentCommitRes.json()) as { tree: { sha: string } }).tree.sha;

  const summary = `round ${marker.round} (${marker.status}) — ${marker.newlyRendered} rendered, ${marker.copiedForward} copied, ${marker.queueRemaining} queued`;
  const message = `prerender: ${summary}\n\n${serializeRoundMarker(marker)}`;

  const commitRes = await chainGithubRequest(token, '/git/commits', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, tree: treeSha, parents: [parentSha] }),
  });
  if (!commitRes.ok) {
    throw new Error(
      `prerender: failed to create round-marker commit — ${commitRes.status} ${commitRes.statusText}`,
    );
  }
  const newSha = ((await commitRes.json()) as { sha: string }).sha;

  const updateRefRes = await chainGithubRequest(token, `/git/refs/heads/${branch}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
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
 * Hook here — `commitRoundMarker`'s branch push already triggers Cloudflare
 * Pages' git-connected auto-deploy, and firing a second hook against the
 * same commit produced two competing deployments (issue #89). */
/** Scopes the in-build validation gate to this round's newly-rendered
 * routes only (issue #94) — `renderQueue` minus whatever the render budget
 * left in `skippedTargets`. Copied-forward routes (never in `renderQueue`)
 * are byte-identical to what already passed this same gate earlier, so
 * re-validating them every round is pure waste that grows unboundedly as
 * the copied-forward set accumulates. */
/** One target per event id that gets the live-API staleness comparison
 * (Big-O audit M15): the default-locale sibling when it's being validated,
 * else the event's first validated sibling — so an event is never left
 * unchecked just because its default-locale render wasn't in this round. */
export function selectStalenessTargets(validationTargets: PrerenderTarget[]): Set<PrerenderTarget> {
  const chosen = new Map<number, PrerenderTarget>();
  for (const target of validationTargets) {
    if (target.eventId === undefined) continue;
    const current = chosen.get(target.eventId);
    if (current === undefined || (target.locale === LOCALE_ET && current.locale !== LOCALE_ET)) {
      chosen.set(target.eventId, target);
    }
  }
  return new Set(chosen.values());
}

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

/** True on a Preview build (issue #95; extended to Cloudflare Pages under
 * #346). Cloudflare Pages exposes no dedicated preview/production flag
 * (confirmed against Cloudflare's own build-config docs), only
 * `CF_PAGES_BRANCH` (the branch this build's checkout is on), so a build
 * infers it the same way Cloudflare's own guidance does: any branch other
 * than the production branch (`PRERENDER_CADENCE_GIT_BRANCH`, 'release' —
 * the same branch functions/api/prerender-cadence.ts already treats as
 * production) is a preview build. Preview URLs aren't crawled or linked
 * externally, and Cloudflare's own fallback routing already serves
 * `app-shell.html` for any route with no snapshot, so skipping prerendering
 * doesn't affect preview functionality. Also sidesteps `commitRoundMarker`
 * committing a chain-state marker against a preview branch ref. Local/dev
 * runs (`CF_PAGES` not set) are unaffected. */
export function isPreviewBuild(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.CF_PAGES === '1' && env.CF_PAGES_BRANCH !== PRERENDER_CADENCE_GIT_BRANCH;
}

/** Reads back this build's own commit message (issue #83; extended to
 * Cloudflare Pages under #346). Cloudflare Pages exposes no commit-message
 * env var at all (confirmed against Cloudflare's build-config docs), only
 * `CF_PAGES_COMMIT_SHA`, so a build looks the message up via GitHub's Git
 * Data API for that exact sha — not a branch-tip lookup — so a commit
 * landing on the production branch between checkout and this call can never
 * be mistaken for this build's own chain-marker commit (see
 * resolveRoundStart's doc comment in prerenderChain.ts for why the marker
 * must belong to *this* build). Reuses GH_PRERENDER_CHAIN_TOKEN (already
 * provisioned with read access for commitRoundMarker) rather than a
 * separate token. Returns `null` — not a thrown error — when either env var
 * is unset (local/dev), or on any fetch/parse failure, so a GitHub hiccup
 * starts a fresh burst at round 1 instead of failing the whole build
 * (mirrors functions/api/prerender-cadence.ts's `fetchTipCommitMessage`,
 * which fails open the same way for the same reason). */
async function fetchBuildCommitMessage(env: NodeJS.ProcessEnv): Promise<string | null> {
  const token = env.GH_PRERENDER_CHAIN_TOKEN;
  const sha = env.CF_PAGES_COMMIT_SHA;
  if (!token || !sha) return null;
  try {
    const res = await chainGithubRequest(token, `/git/commits/${sha}`);
    if (!res.ok) return null;
    const body = (await res.json()) as { message?: string };
    return body.message ?? null;
  } catch {
    return null;
  }
}

export async function main(): Promise<void> {
  if (isPreviewBuild()) {
    console.log('prerender: CF_PAGES_BRANCH is a non-production branch — skipping prerender pass entirely (issue #95)');
    return;
  }

  // Read back this build's own commit message at build start, before doing
  // any rendering work, to resume mid-burst rather than always starting
  // fresh at round 1 (issue #83). Since the round marker's git push is the
  // only thing that triggers the next round's build (issue #89 removed the
  // redundant Deploy Hook that used to fire a second, competing deployment
  // of the same commit), a fresh `continuing` marker here is exactly the
  // legitimate continuation it was committed for — see resolveRoundStart's
  // doc comment (src/lib/prerenderChain.ts) for why it resumes at round + 1
  // instead of skipping (issue #90), and why a stale `continuing` marker
  // still falls through to a fresh round 1.
  const commitMessage = await fetchBuildCommitMessage(process.env);
  const { burstId, round } = resolveRoundStart(commitMessage, new Date());
  console.log(`prerender: round ${round} of burst ${burstId}${round > 1 ? ' (resumed)' : ' (new)'}`);

  // Chain-state manifest (issues #367/#368) — round 1's burstId is freshly
  // minted (resolveRoundStart), guaranteed to have no manifest yet, so no
  // read is attempted; round 2+ reads it both to merge #367's end-of-round
  // accumulation onto what an earlier round already wrote and to drive
  // #368's skip-refetch partition below.
  const sanitizedBurstId = sanitizeBurstIdForR2(burstId);
  const isResumedRound = round > 1;
  const chainStateIndex: ChainStateIndex = isResumedRound
    ? parseChainStateIndex(await getR2Object(chainStateIndexKey(sanitizedBurstId)))
    : {};

  const candidates = await fetchPrerenderCandidates();
  const targets = buildTargets(candidates);

  const buildTimestamp = new Date().toISOString();
  await writeFile(
    path.join(DIST_DIR, SITEMAP_FILENAME),
    buildSitemapXml(targets, buildTimestamp),
    'utf-8',
  );
  await writeFile(path.join(DIST_DIR, ROBOTS_TXT_FILENAME), buildRobotsTxt(), 'utf-8');
  console.log(`prerender: wrote sitemap.xml (${targets.length} url(s)) and robots.txt`);

  // The one pristine Vite build output still on disk during this round
  // (frontend/package.json's build script copies it here before invoking
  // this script, and nothing below ever touches it) — read once so every
  // copy-forward/stale-fallback write below can rewrite its stale asset
  // refs to match the current build (issue #97).
  const shellHtml = await readFile(path.join(DIST_DIR, APP_SHELL_FILENAME), 'utf-8');

  // Change detection (issue #80): for every event route, diff its embedded
  // marker against the currently-live production page. An exact match
  // copies the live page forward as-is (no Playwright render); everything
  // else (never-rendered, changed, or a fetch/parse miss) renders fresh.
  // Round 2+ (issue #368) skips this production fetch for any event target
  // the manifest index already resolved earlier in the burst, substituting
  // fetchResolvedTarget's cheaper R2 read instead — both routes run through
  // the same mapPool/CHANGE_DETECTION_CONCURRENCY pool `targets` already
  // did pre-#368, so the concurrency cap against PRODUCTION_ORIGIN never
  // stacks and the result stays ordered like `targets` with no separate
  // merge step.
  const resolvedTargets: ResolvedTarget[] = isResumedRound
    ? partitionByChainState(targets, chainStateIndex).resolved
    : [];
  const resolvedTargetSet = new Set<PrerenderTarget>(resolvedTargets);
  const resolvedFromManifest = new Set<PrerenderTarget>();
  const classification = await mapPool(targets, CHANGE_DETECTION_CONCURRENCY, (target) =>
    resolvedTargetSet.has(target)
      ? fetchResolvedTarget(sanitizedBurstId, target as ResolvedTarget, resolvedFromManifest)
      : classifyTarget(target),
  );
  let copiedForward = 0;
  // Stale-but-real fallback (issue #82) content, held in memory rather than
  // written to dist/ yet — see the write-out below (after the render pool)
  // for why. Keyed by target so a successfully-rendered or -failed target
  // can drop its entry once the render loop has an answer for it either way.
  const staleFallbackHtml = new Map<PrerenderTarget, string>();
  // R2 chain-state PUTs are fire-and-forget from the workers' point of view
  // (Big-O audit M14): render/copy-forward workers never block on them, and
  // `allSettled` after the pools drains them. persistChainStateTarget fails
  // open, so a rejected entry can only mean a lost optimization.
  const persistLimiter = createLimiter(R2_PERSIST_CONCURRENCY);
  // runPool, not a sequential for-of — each iteration's mkdir/writeFile/
  // persistChainStateTarget (an R2 network round trip) was the dominant
  // wall-clock cost of a copy-forward-heavy round, run one at a time for
  // events x 3 locales (Big-O audit #5, item Tier 4, biggest single win).
  // copiedForward++ and staleFallbackHtml.set() are plain synchronous
  // statements with no await between read and write, so concurrent workers
  // touching them (distinct target keys) never race.
  await runPool(classification, CHANGE_DETECTION_CONCURRENCY, async (entry) => {
    const { target, unchanged, liveHtml } = entry;
    // Drop the classification's own reference (Big-O audit M12): the HTML now
    // lives only in the local (copy-forward) or in staleFallbackHtml (needs
    // render), so it's collectable as soon as each branch is done with it.
    entry.liveHtml = null;
    if (unchanged && liveHtml !== null) {
      const outPath = outputFilePath(target.bare, target.locale);
      await mkdir(path.dirname(outPath), { recursive: true });
      const finalized = finalizeSnapshotHtml(liveHtml, shellHtml);
      await writeFile(outPath, finalized, 'utf-8');
      copiedForward++;
      // A target fetchResolvedTarget already sourced from the manifest is
      // already in the bucket under this exact key — re-PUTting identical
      // bytes would be a pure-waste duplicate write (issue #368).
      if (!resolvedFromManifest.has(target)) {
        persistLimiter.run(() =>
          persistChainStateTarget(sanitizedBurstId, round, target, finalized, chainStateIndex),
        );
      }
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
  });
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
  // Feeds validateTarget below — every successfully-rendered target this
  // round already has its finalized HTML sitting in memory right here, so
  // the validation pass doesn't need to re-readFile + re-parse a file this
  // same process just wrote (Big-O audit #5, Tier 4).
  const renderedHtmlByTarget = new Map<PrerenderTarget, string>();
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
              const finalizedHtml = await snapshotTarget(page, resolvedPreviewOrigin, target);
              newlyRendered++;
              renderedHtmlByTarget.set(target, finalizedHtml);
              persistLimiter.run(() =>
                persistChainStateTarget(sanitizedBurstId, round, target, finalizedHtml, chainStateIndex),
              );
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
  // nothing on disk, which falls through to the CSR shell via
  // `functions/[[path]].ts`'s SPA fallback rather than a build failure —
  // see outputFilePath above.
  let staleFallbackWritten = 0;
  // runPool, not a sequential for-of — same rationale as the copy-forward
  // loop above (Big-O audit #5, Tier 4).
  await runPool(skippedTargets, CHANGE_DETECTION_CONCURRENCY, async (target) => {
    const liveHtml = staleFallbackHtml.get(target);
    if (liveHtml === undefined) return;
    const outPath = outputFilePath(target.bare, target.locale);
    await mkdir(path.dirname(outPath), { recursive: true });
    await writeFile(outPath, finalizeSnapshotHtml(liveHtml, shellHtml), 'utf-8');
    staleFallbackWritten++;
  });

  await persistLimiter.drain();

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
  const stalenessTargets = selectStalenessTargets(validationTargets);
  await runPool(validationTargets, PRERENDER_CONCURRENCY, async (target) => {
    validationIssues.push(
      ...(await validateTarget(target, renderedHtmlByTarget.get(target), stalenessTargets.has(target))),
    );
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
  // and committed to the git-connected production branch, whose push
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
  // production branch is git-connected to Cloudflare Pages, so advancing its
  // ref alone triggers the next round's build. No separate Deploy Hook fire
  // happens here. Only push when shouldCommitRoundMarker(marker) says a
  // round is actually `continuing` — pushing a `done` marker has nothing
  // left to resume, yet the push itself still triggers a fresh build (any
  // push does), which starts a brand-new burst that (home routes never
  // classify `unchanged` — see classifyTarget) reliably finishes `done`
  // again, forever. That self-sustaining loop is what shipped overnight
  // (issue #101) before this gate existed. If the commit is skipped or
  // fails, the chain simply resumes via the next 6-hourly cron tick instead
  // of self-triggering (degraded, not broken — same fallback as any other
  // lost marker commit).
  const commitMarker = shouldCommitRoundMarker(marker);
  if (commitMarker) {
    try {
      await commitRoundMarker(marker);
    } catch (error) {
      console.error('prerender: failed to commit round marker — deploy proceeds anyway:', error);
    }
  }
  // Chain-state manifest write (issue #367) — see finalizeChainState's doc
  // comment for why a `done` round deletes instead of writing.
  await finalizeChainState(sanitizedBurstId, chainStateIndex, commitMarker);
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
