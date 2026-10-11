// Lives outside functions/ on purpose: Cloudflare Pages bundles every file
// under that tree into the deployed Worker (underscore-prefixed filenames
// don't exempt them — only whole directories do), and this test's vitest
// import drags in `node:sqlite` via undici, which the Workers bundler can't
// resolve.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { onRequest } from '../../../functions/api/seo-audit';
import {
  PRODUCTION_ORIGIN,
  SEO_AUDIT_TOKEN_HEADER,
  CRAWLABLE_ICON_PATHS,
} from '../../../src/constants/seo';
import { buildEventJsonLd, buildWebsiteJsonLd } from '../../../src/lib/structuredData';
import { buildSeoMeta } from '../../../src/hooks/useSeoMeta';
import { makeEvent } from '../../../src/test/utils';

interface Env {
  SEO_AUDIT_TOKEN?: string;
  GH_ISSUE_TOKEN?: string;
}

function makeContext(env: Env = { SEO_AUDIT_TOKEN: 'shared-secret', GH_ISSUE_TOKEN: 'gh-token' }) {
  return {
    request: new Request('https://eventradar.ee/api/seo-audit', {
      method: 'POST',
      headers: { [SEO_AUDIT_TOKEN_HEADER]: 'shared-secret' },
    }),
    env,
  };
}

vi.mock('../../../src/lib/seoAuditIssue', () => ({
  reportAuditFailure: vi.fn().mockResolvedValue(undefined),
  reportAuditRecovery: vi.fn().mockResolvedValue(undefined),
}));

/** Mirrors seoAudit.test.ts's local fixture helper. */
function renderSnapshotHtml(meta: ReturnType<typeof buildSeoMeta>, jsonLd: object, assetTags: string): string {
  const metaTags = meta.metaTags
    .map((tag) => `<meta ${tag.name ? `name="${tag.name}"` : `property="${tag.property}"`} content="${tag.content}">`)
    .join('\n');
  const links = meta.links
    .map((link) => `<link rel="${link.rel}" href="${link.href}"${link.hrefLang ? ` hreflang="${link.hrefLang}"` : ''}>`)
    .join('\n');
  return `<!doctype html><html lang="${meta.htmlLang}"><head><title>${meta.title}</title>${metaTags}${links}<link rel="icon" href="/favicon.svg">${assetTags}<script type="application/ld+json">${JSON.stringify(jsonLd)}</script></head><body></body></html>`;
}

function renderLandingHtml(assetTags: string): string {
  const meta = buildSeoMeta({ title: 'Mis toimub Tallinnas | Event Radar', locale: 'et', path: '/', indexable: true });
  return renderSnapshotHtml(meta, buildWebsiteJsonLd('et'), assetTags);
}

function renderEventHtml(assetTags: string): string {
  const event = makeEvent({ id: 1, title: 'Jazz Night' });
  const meta = buildSeoMeta({ title: 'Jazz Night – Kultuurikatel | Event Radar', locale: 'et', path: '/events/1', indexable: true });
  return renderSnapshotHtml(meta, buildEventJsonLd(event), assetTags);
}

const VALID_ROBOTS_TXT = [
  'User-agent: *',
  'Disallow: /',
  'Allow: /$',
  'Allow: /events/',
  'Allow: /sitemap.xml',
  'Allow: /og-fallback.png',
  'Allow: /assets/',
  ...CRAWLABLE_ICON_PATHS.map((iconPath) => `Allow: ${iconPath}`),
  '',
  `Sitemap: ${PRODUCTION_ORIGIN}/sitemap.xml`,
].join('\n');

function sitemapXml(lastmod: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>${PRODUCTION_ORIGIN}/</loc><lastmod>${lastmod}</lastmod></url><url><loc>${PRODUCTION_ORIGIN}/events/1</loc><lastmod>${lastmod}</lastmod></url></urlset>\n`;
}

/** Stubs global fetch to serve the four base production fetches plus
 * whatever event-snapshot asset URLs `assetContentTypes` maps — keyed by the
 * asset's absolute URL, so a test can control exactly which asset responds
 * with which content-type (or 404s, by omission). */
function stubFetch(params: {
  eventHtml: string;
  assetContentTypes: Record<string, string | null>;
}) {
  // Handler always evaluates freshness against the real current time (no
  // `now` override reaches it), so the sitemap's <lastmod> must be "now",
  // not a fixed past date, or the audit's own staleness check fails these
  // tests for a reason unrelated to what they're testing.
  const lastmod = new Date().toISOString();
  const landingHtml = renderLandingHtml('');
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      const u = String(url);
      if (u === `${PRODUCTION_ORIGIN}/sitemap.xml`) {
        return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(sitemapXml(lastmod)) });
      }
      if (u === `${PRODUCTION_ORIGIN}/`) {
        return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(landingHtml) });
      }
      if (u === `${PRODUCTION_ORIGIN}/robots.txt`) {
        return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(VALID_ROBOTS_TXT) });
      }
      if (u === `${PRODUCTION_ORIGIN}/favicon.ico`) {
        return Promise.resolve({ ok: true, status: 200, headers: { get: () => 'image/x-icon' } });
      }
      if (u === `${PRODUCTION_ORIGIN}/events/1`) {
        return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(params.eventHtml) });
      }
      if (u.startsWith(`${PRODUCTION_ORIGIN}/en/explore`) || u.startsWith(`${PRODUCTION_ORIGIN}/explore`) || u.startsWith(`${PRODUCTION_ORIGIN}/ru/explore`)) {
        return Promise.resolve({ ok: false, status: 404, text: () => Promise.resolve('') });
      }
      if (u in params.assetContentTypes) {
        const contentType = params.assetContentTypes[u];
        return Promise.resolve({ ok: contentType !== null, status: contentType !== null ? 200 : 200, headers: { get: () => contentType } });
      }
      return Promise.reject(new Error(`unexpected fetch: ${u}`));
    }),
  );
}

describe('seo-audit handler — event snapshot asset content-type check (issue #97)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('answers a GET with 405 itself instead of falling through to the proxy (L-8)', async () => {
    const res = await onRequest({
      request: new Request('https://eventradar.ee/api/seo-audit', {
        method: 'GET',
        headers: { [SEO_AUDIT_TOKEN_HEADER]: 'shared-secret' },
      }),
      env: { SEO_AUDIT_TOKEN: 'shared-secret', GH_ISSUE_TOKEN: 'gh-token' },
    } as never);
    expect(res.status).toBe(405);
  });

  it('passes when the event snapshot\'s assets serve their expected content-types', async () => {
    const jsUrl = `${PRODUCTION_ORIGIN}/assets/index-CURRENT111.js`;
    const cssUrl = `${PRODUCTION_ORIGIN}/assets/index-CURRENT222.css`;
    const assetTags = `<script type="module" src="/assets/index-CURRENT111.js"></script><link rel="stylesheet" href="/assets/index-CURRENT222.css">`;
    stubFetch({
      eventHtml: renderEventHtml(assetTags),
      assetContentTypes: { [jsUrl]: 'application/javascript', [cssUrl]: 'text/css' },
    });

    const res = await onRequest(makeContext());

    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean };
    expect(body.ok).toBe(true);
  });

  it('flags a stale event snapshot asset that 200s as text/html (app-shell fallthrough)', async () => {
    const jsUrl = `${PRODUCTION_ORIGIN}/assets/index-STALE111.js`;
    const assetTags = `<script type="module" src="/assets/index-STALE111.js"></script>`;
    stubFetch({
      eventHtml: renderEventHtml(assetTags),
      assetContentTypes: { [jsUrl]: 'text/html; charset=utf-8' },
    });

    const res = await onRequest(makeContext());

    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean; issues: string[] };
    expect(body.ok).toBe(false);
    expect(body.issues.some((issue) => issue.includes('index-STALE111.js') && issue.includes('previous build'))).toBe(true);
  });
});
