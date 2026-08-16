// .js extensions required: this module is also imported (transitively) by
// api/seo-audit.ts, which Vercel runs as unbundled Node ESM.
import { LOCALE_ET, MS_PER_HOUR, PRODUCTION_ORIGIN, SEO_AUDIT_STALE_THRESHOLD_HOURS } from '../constants.js';
import { parseSnapshotHtml, validateSnapshotStructure } from './seoValidation.js';

export interface LiveAuditResult {
  ok: boolean;
  issues: string[];
  /** Raw `<lastmod>` value read off sitemap.xml, or null if none was found. */
  buildTimestamp: string | null;
}

/** sitemap.xml carries one `<lastmod>` per `<url>`, uniformly the prerender
 * build timestamp (see prerender.ts's buildSitemapXml) — any one entry is
 * representative of the whole build, so the first is enough. Regex, not an
 * XML parser: this is our own generated, well-formed output, not third-party
 * XML that needs defensive parsing. */
export function parseSitemapLastmod(sitemapXml: string): string | null {
  const match = sitemapXml.match(/<lastmod>([^<]+)<\/lastmod>/);
  return match ? match[1] : null;
}

/** Every bare-Estonian `/events/:id` URL listed in sitemap.xml (excludes the
 * `/en`/`/ru`-prefixed siblings and the Landing entry) — used to pick one
 * live event page to structurally spot-check. Without this, the live audit
 * would only ever exercise validateSnapshotStructure's `kind: 'website'`
 * path, never `kind: 'event'` (assertEventJsonLd), even though event pages
 * are the higher-value SEO surface. */
export function parseSitemapEventUrls(sitemapXml: string): string[] {
  const locs = [...sitemapXml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
  const eventUrlRe = new RegExp(`^${PRODUCTION_ORIGIN.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/events/\\d+$`);
  return locs.filter((loc) => eventUrlRe.test(loc));
}

/** The live audit (issue #54): checks production (not a local build) for (1)
 * a dead prerender cadence — sitemap.xml's build timestamp older than
 * SEO_AUDIT_STALE_THRESHOLD_HOURS — and (2) structural regressions on the
 * live Landing snapshot and (if the catalog has any published events yet) one
 * live event snapshot, reusing seoValidation.ts's in-build-gate checks
 * (issue #53) unchanged rather than reimplementing them. Pure/network-free
 * so it can be unit-tested directly; api/seo-audit.ts does the fetching
 * (including picking which event URL to fetch, via parseSitemapEventUrls). */
export function evaluateLiveAudit(params: {
  sitemapXml: string;
  landingHtml: string;
  eventHtml?: string;
  now?: Date;
}): LiveAuditResult {
  const now = params.now ?? new Date();
  const issues: string[] = [];

  const buildTimestamp = parseSitemapLastmod(params.sitemapXml);
  if (!buildTimestamp) {
    issues.push('sitemap.xml has no <lastmod> entry — cannot determine build freshness');
  } else {
    const parsedMs = Date.parse(buildTimestamp);
    if (Number.isNaN(parsedMs)) {
      issues.push(`sitemap.xml <lastmod> is not a valid date: "${buildTimestamp}"`);
    } else {
      const ageHours = (now.getTime() - parsedMs) / MS_PER_HOUR;
      if (ageHours > SEO_AUDIT_STALE_THRESHOLD_HOURS) {
        issues.push(
          `prerender snapshot cycle looks dead: sitemap.xml build timestamp is ${ageHours.toFixed(1)}h old, exceeds the ${SEO_AUDIT_STALE_THRESHOLD_HOURS}h threshold`,
        );
      }
    }
  }

  const parsedLanding = parseSnapshotHtml(params.landingHtml);
  const landingIssues = validateSnapshotStructure(parsedLanding, {
    kind: 'website',
    locale: LOCALE_ET,
    originPrefix: PRODUCTION_ORIGIN,
  });
  issues.push(...landingIssues.map((issue) => `landing structural: ${issue}`));

  if (params.eventHtml) {
    const parsedEvent = parseSnapshotHtml(params.eventHtml);
    const eventIssues = validateSnapshotStructure(parsedEvent, {
      kind: 'event',
      locale: LOCALE_ET,
      originPrefix: PRODUCTION_ORIGIN,
    });
    issues.push(...eventIssues.map((issue) => `event structural: ${issue}`));
  }

  return { ok: issues.length === 0, issues, buildTimestamp };
}
