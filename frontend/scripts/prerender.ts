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
 * Fails loudly (non-zero exit) if the published-events fetch fails or if
 * Playwright can't reach/render any target route — see docs/frontend.md's
 * prerender section. `npm run build` copies dist/index.html to
 * dist/app-shell.html *before* invoking this script (not inside it) so the
 * SPA-fallback rewrite target exists even if this script never runs to
 * completion.
 */
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, type Page } from 'playwright';
import { preview, type PreviewServer } from 'vite';
import {
  LOCALE_URL_PREFIX_CODES,
  LOCALES,
  PRODUCTION_ORIGIN,
  ROUTES,
  SEO_HREFLANG_CODES,
} from '../src/constants';
import { localizedPath } from '../src/lib/urlLocale';
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

interface PrerenderTarget {
  /** Bare (Estonian) ROUTES.* path, before locale-prefixing. */
  bare: string;
  locale: string;
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

async function fetchPublishedEventIds(): Promise<number[]> {
  const res = await fetch(`${API_ORIGIN}/public/prerender-events`);
  if (!res.ok) {
    throw new Error(
      `prerender: failed to fetch published events from ${API_ORIGIN}/public/prerender-events — ${res.status} ${res.statusText}`,
    );
  }
  const body = (await res.json()) as { event_ids: number[] };
  return body.event_ids;
}

function buildTargets(eventIds: number[]): PrerenderTarget[] {
  const localeCodes = LOCALES.map((l) => l.code);
  const targets: PrerenderTarget[] = [];
  for (const locale of localeCodes) {
    targets.push({ bare: ROUTES.home, locale });
    for (const id of eventIds) {
      targets.push({ bare: ROUTES.eventDetail(id), locale });
    }
  }
  return targets;
}

/** sitemap.xml for `targets` (issue #51) — one `<url>` per locale-variant
 * URL (mirrors `buildTargets`'s flat "every locale × every bare path"
 * shape), each carrying the same en/et/ru/x-default hreflang cross-references
 * `useSeoMeta`'s `buildSeoMeta` emits as `<link>` tags, so the sitemap and
 * the prerendered pages it lists never disagree about locale siblings.
 * `lastmod` is uniformly `buildTimestamp` — `Event` has no `updated_at`, so
 * there's no meaningful per-row value to put there instead. */
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
      return `  <url>\n    <loc>${loc}</loc>\n    <lastmod>${buildTimestamp}</lastmod>\n${alternates}\n  </url>`;
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
  const html = await page.content();
  const outPath = outputFilePath(target.bare, target.locale);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, html, 'utf-8');
}

async function main(): Promise<void> {
  const eventIds = await fetchPublishedEventIds();
  const targets = buildTargets(eventIds);

  const buildTimestamp = new Date().toISOString();
  await writeFile(
    path.join(DIST_DIR, 'sitemap.xml'),
    buildSitemapXml(targets, buildTimestamp),
    'utf-8',
  );
  await writeFile(path.join(DIST_DIR, 'robots.txt'), buildRobotsTxt(), 'utf-8');
  console.log(`prerender: wrote sitemap.xml (${targets.length} url(s)) and robots.txt`);

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
    let cursor = 0;
    async function worker(): Promise<void> {
      const page = await browser.newPage();
      try {
        while (cursor < targets.length) {
          const target = targets[cursor++];
          try {
            await snapshotTarget(page, resolvedPreviewOrigin, target);
          } catch (error) {
            failures.push({ target, error });
          }
        }
      } finally {
        await page.close();
      }
    }
    await Promise.all(
      Array.from({ length: Math.min(PRERENDER_CONCURRENCY, targets.length) }, worker),
    );

    if (failures.length > 0) {
      for (const { target, error } of failures) {
        console.error(
          `prerender: failed to render ${localizedPath(target.bare, target.locale)} —`,
          error,
        );
      }
      throw new Error(
        `prerender: ${failures.length}/${targets.length} route(s) failed to render — see errors above`,
      );
    }

    console.log(`prerender: wrote ${targets.length} snapshot(s) to ${DIST_DIR}`);
  } finally {
    await browser.close();
    await server?.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
