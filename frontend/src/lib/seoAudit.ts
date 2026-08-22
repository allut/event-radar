// .js extensions required: this module is also imported (transitively) by
// api/seo-audit.ts, which Vercel runs as unbundled Node ESM.
import {
  CRAWLABLE_ASSETS_PATH,
  CRAWLABLE_ICON_PATHS,
  LOCALE_ET,
  MS_PER_HOUR,
  OG_FALLBACK_IMAGE_PATH,
  PRODUCTION_ORIGIN,
  SEO_AUDIT_STALE_THRESHOLD_HOURS,
  SITEMAP_PATH,
} from '../constants.js';
import { parseSnapshotHtml, validateSnapshotStructure } from './seoValidation.js';

/** One `Allow:`/`Disallow:` rule parsed out of a `User-agent: *` group,
 * carrying its original pattern length for Google's longest-match-wins
 * tie-break (isPathAllowedByRobots). */
interface RobotsRule {
  allow: boolean;
  regex: RegExp;
  patternLength: number;
}

/** Converts one robots.txt pattern (`*` wildcard, optional trailing `$`
 * end-anchor) into the equivalent prefix-matching RegExp, per Google's
 * documented robots.txt matching semantics. */
function robotsPatternToRegex(pattern: string): RegExp {
  const endAnchored = pattern.endsWith('$');
  const body = endAnchored ? pattern.slice(0, -1) : pattern;
  const escaped = body.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(`^${escaped}${endAnchored ? '$' : ''}`);
}

/** Parses the `User-agent: *` group out of a robots.txt body into
 * Allow/Disallow rules. Other User-agent groups are ignored — Googlebot
 * (the only crawler this audit cares about) falls back to `*` when no
 * Googlebot-specific group exists, which is the case for this site's
 * generated robots.txt (buildRobotsTxt, scripts/prerender.ts). */
function parseWildcardAgentRules(robotsTxt: string): RobotsRule[] {
  const rules: RobotsRule[] = [];
  let inWildcardGroup = false;
  for (const rawLine of robotsTxt.split('\n')) {
    const line = rawLine.split('#')[0].trim();
    if (!line) continue;
    const [directiveRaw, ...rest] = line.split(':');
    const directive = directiveRaw.trim().toLowerCase();
    const value = rest.join(':').trim();
    if (directive === 'user-agent') {
      inWildcardGroup = value === '*';
      continue;
    }
    if (!inWildcardGroup) continue;
    if (directive === 'allow' || directive === 'disallow') {
      if (!value) continue; // `Disallow:` with an empty value means "allow everything"
      rules.push({ allow: directive === 'allow', regex: robotsPatternToRegex(value), patternLength: value.length });
    }
  }
  return rules;
}

/** Google's robots.txt matching semantics (`*` wildcard, `$` end-anchor,
 * longest-matching-pattern wins, `Allow` wins exact-length ties) — used by
 * the live audit to catch a robots.txt regression that blocks the sitemap,
 * the OG fallback image, or the SPA's built assets (the bug this audit
 * check exists for: robots.txt's `Disallow: /` silently caught
 * /sitemap.xml, and Google Search Console reported "Couldn't fetch" with
 * nothing else in the pipeline any wiser). */
export function isPathAllowedByRobots(robotsTxt: string, path: string): boolean {
  const rules = parseWildcardAgentRules(robotsTxt);
  const matching = rules.filter((rule) => rule.regex.test(path));
  if (matching.length === 0) return true;
  matching.sort((a, b) => b.patternLength - a.patternLength || (a.allow === b.allow ? 0 : a.allow ? -1 : 1));
  return matching[0].allow;
}

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
  robotsTxt: string;
  eventHtml?: string;
  now?: Date;
}): LiveAuditResult {
  const now = params.now ?? new Date();
  const issues: string[] = [];

  if (!isPathAllowedByRobots(params.robotsTxt, SITEMAP_PATH)) {
    issues.push(`robots.txt blocks ${SITEMAP_PATH} — Google Search Console will report "Couldn't fetch"`);
  }
  if (!isPathAllowedByRobots(params.robotsTxt, OG_FALLBACK_IMAGE_PATH)) {
    issues.push(`robots.txt blocks ${OG_FALLBACK_IMAGE_PATH} — the og:image fallback can't be crawled`);
  }
  if (!isPathAllowedByRobots(params.robotsTxt, `${CRAWLABLE_ASSETS_PATH}index.js`)) {
    issues.push(`robots.txt blocks ${CRAWLABLE_ASSETS_PATH} — Googlebot can't fetch the SPA's built assets`);
  }
  for (const iconPath of CRAWLABLE_ICON_PATHS) {
    if (!isPathAllowedByRobots(params.robotsTxt, iconPath)) {
      issues.push(`robots.txt blocks ${iconPath} — Google can't crawl the site icon`);
    }
  }

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
