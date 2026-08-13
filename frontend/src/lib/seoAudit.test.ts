import { describe, it, expect } from 'vitest';
import { parseSitemapLastmod, parseSitemapEventUrls, evaluateLiveAudit } from './seoAudit';
import { buildEventJsonLd, buildWebsiteJsonLd } from './structuredData';
import { buildSeoMeta } from '../hooks/useSeoMeta';
import { makeEvent } from '../test/utils';
import { PRODUCTION_ORIGIN, SEO_AUDIT_STALE_THRESHOLD_HOURS } from '../constants';

/** Mirrors seoValidation.test.ts's renderSnapshotHtml — kept local since that
 * helper isn't exported, and this file needs both the Landing/website and
 * event-page shapes. */
function renderSnapshotHtml(meta: ReturnType<typeof buildSeoMeta>, jsonLd: object): string {
  const metaTags = meta.metaTags
    .map((tag) => `<meta ${tag.name ? `name="${tag.name}"` : `property="${tag.property}"`} content="${tag.content}">`)
    .join('\n');
  const links = meta.links
    .map((link) => `<link rel="${link.rel}" href="${link.href}"${link.hrefLang ? ` hreflang="${link.hrefLang}"` : ''}>`)
    .join('\n');
  return `<!doctype html><html lang="${meta.htmlLang}"><head><title>${meta.title}</title>${metaTags}${links}<script type="application/ld+json">${JSON.stringify(jsonLd)}</script></head><body></body></html>`;
}

function renderLandingHtml(): string {
  const meta = buildSeoMeta({ title: 'Mis toimub Tallinnas | What\'s on Radar', locale: 'et', path: '/', indexable: true });
  return renderSnapshotHtml(meta, buildWebsiteJsonLd('et'));
}

function renderEventHtml(eventId = 1): string {
  const event = makeEvent({ id: eventId, title: 'Jazz Night' });
  const meta = buildSeoMeta({
    title: 'Jazz Night – Kultuurikatel | What\'s on Radar',
    locale: 'et',
    path: `/events/${eventId}`,
    indexable: true,
  });
  return renderSnapshotHtml(meta, buildEventJsonLd(event));
}

function sitemapWithLastmod(lastmod: string, extraLocs: string[] = []): string {
  const extraUrls = extraLocs.map((loc) => `<url><loc>${loc}</loc><lastmod>${lastmod}</lastmod></url>`).join('');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>${PRODUCTION_ORIGIN}/</loc><lastmod>${lastmod}</lastmod></url>${extraUrls}</urlset>\n`;
}

describe('parseSitemapLastmod', () => {
  it('extracts the first <lastmod> value', () => {
    expect(parseSitemapLastmod(sitemapWithLastmod('2026-08-13T04:00:00.000Z'))).toBe('2026-08-13T04:00:00.000Z');
  });

  it('returns null when no <lastmod> is present', () => {
    expect(parseSitemapLastmod('<urlset></urlset>')).toBeNull();
  });
});

describe('parseSitemapEventUrls', () => {
  it('extracts only bare-Estonian /events/:id URLs, excluding locale-prefixed siblings and Landing', () => {
    const sitemap = sitemapWithLastmod('2026-08-13T04:00:00.000Z', [
      `${PRODUCTION_ORIGIN}/events/1`,
      `${PRODUCTION_ORIGIN}/en/events/1`,
      `${PRODUCTION_ORIGIN}/ru/events/1`,
      `${PRODUCTION_ORIGIN}/events/2`,
    ]);
    expect(parseSitemapEventUrls(sitemap)).toEqual([`${PRODUCTION_ORIGIN}/events/1`, `${PRODUCTION_ORIGIN}/events/2`]);
  });

  it('returns an empty list when the catalog has no published events yet', () => {
    expect(parseSitemapEventUrls(sitemapWithLastmod('2026-08-13T04:00:00.000Z'))).toEqual([]);
  });
});

describe('evaluateLiveAudit', () => {
  const now = new Date('2026-08-13T12:00:00.000Z');

  it('passes when the build is fresh and the landing snapshot is structurally valid', () => {
    const buildTimestamp = new Date(now.getTime() - 1 * 60 * 60 * 1000).toISOString(); // 1h old
    const result = evaluateLiveAudit({
      sitemapXml: sitemapWithLastmod(buildTimestamp),
      landingHtml: renderLandingHtml(),
      now,
    });
    expect(result).toEqual({ ok: true, issues: [], buildTimestamp });
  });

  it(`flags a build older than ${SEO_AUDIT_STALE_THRESHOLD_HOURS}h as stale`, () => {
    const buildTimestamp = new Date(now.getTime() - 9 * 60 * 60 * 1000).toISOString(); // 9h old
    const result = evaluateLiveAudit({
      sitemapXml: sitemapWithLastmod(buildTimestamp),
      landingHtml: renderLandingHtml(),
      now,
    });
    expect(result.ok).toBe(false);
    expect(result.issues.some((i) => i.includes('prerender snapshot cycle looks dead'))).toBe(true);
  });

  it(`passes a build exactly at the ${SEO_AUDIT_STALE_THRESHOLD_HOURS}h threshold`, () => {
    const buildTimestamp = new Date(now.getTime() - SEO_AUDIT_STALE_THRESHOLD_HOURS * 60 * 60 * 1000).toISOString();
    const result = evaluateLiveAudit({
      sitemapXml: sitemapWithLastmod(buildTimestamp),
      landingHtml: renderLandingHtml(),
      now,
    });
    expect(result.ok).toBe(true);
  });

  it('flags a missing <lastmod> as an issue rather than throwing', () => {
    const result = evaluateLiveAudit({
      sitemapXml: '<urlset></urlset>',
      landingHtml: renderLandingHtml(),
      now,
    });
    expect(result.ok).toBe(false);
    expect(result.buildTimestamp).toBeNull();
    expect(result.issues.some((i) => i.includes('no <lastmod> entry'))).toBe(true);
  });

  it('surfaces structural regressions on the live landing snapshot', () => {
    const buildTimestamp = now.toISOString();
    const brokenHtml = renderLandingHtml().replace(/<link rel="alternate"[^>]*hreflang="ru"[^>]*>/, '');
    const result = evaluateLiveAudit({
      sitemapXml: sitemapWithLastmod(buildTimestamp),
      landingHtml: brokenHtml,
      now,
    });
    expect(result.ok).toBe(false);
    expect(result.issues.some((i) => i.includes('landing structural') && i.includes('hreflang alternate for "ru"'))).toBe(true);
  });

  it('passes with a structurally valid event snapshot included', () => {
    const buildTimestamp = now.toISOString();
    const result = evaluateLiveAudit({
      sitemapXml: sitemapWithLastmod(buildTimestamp),
      landingHtml: renderLandingHtml(),
      eventHtml: renderEventHtml(),
      now,
    });
    expect(result.ok).toBe(true);
  });

  it('surfaces structural regressions on the live event snapshot', () => {
    const buildTimestamp = now.toISOString();
    const brokenEventHtml = renderEventHtml().replace(/<link rel="canonical"[^>]*>/, '');
    const result = evaluateLiveAudit({
      sitemapXml: sitemapWithLastmod(buildTimestamp),
      landingHtml: renderLandingHtml(),
      eventHtml: brokenEventHtml,
      now,
    });
    expect(result.ok).toBe(false);
    expect(result.issues.some((i) => i.includes('event structural') && i.includes('canonical'))).toBe(true);
  });

  it('skips the event check entirely when no event page was fetched (empty catalog)', () => {
    const buildTimestamp = now.toISOString();
    const result = evaluateLiveAudit({
      sitemapXml: sitemapWithLastmod(buildTimestamp),
      landingHtml: renderLandingHtml(),
      now,
    });
    expect(result.ok).toBe(true);
    expect(result.issues.some((i) => i.includes('event structural'))).toBe(false);
  });
});
