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
import type { LocaleCode } from '../constants.js';
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
 * longest-matching-pattern wins, `Allow` wins exact-length ties) against an
 * already-parsed rule set — split out of isPathAllowedByRobots so callers
 * checking multiple paths against the same robots.txt body (evaluateLiveAudit)
 * parse once instead of re-parsing (and recompiling every rule's RegExp) per
 * path. */
function isPathAllowedByRules(rules: RobotsRule[], path: string): boolean {
  const matching = rules.filter((rule) => rule.regex.test(path));
  if (matching.length === 0) return true;
  matching.sort((a, b) => b.patternLength - a.patternLength || (a.allow === b.allow ? 0 : a.allow ? -1 : 1));
  return matching[0].allow;
}

/** Google's robots.txt matching semantics (`*` wildcard, `$` end-anchor,
 * longest-matching-pattern wins, `Allow` wins exact-length ties) — used by
 * the live audit to catch a robots.txt regression that blocks the sitemap,
 * the OG fallback image, or the SPA's built assets (the bug this audit
 * check exists for: robots.txt's `Disallow: /` silently caught
 * /sitemap.xml, and Google Search Console reported "Couldn't fetch" with
 * nothing else in the pipeline any wiser). Thin single-path wrapper around
 * isPathAllowedByRules — re-parses robots.txt each call, so prefer parsing
 * once via parseWildcardAgentRules + isPathAllowedByRules when checking
 * several paths against the same body. */
export function isPathAllowedByRobots(robotsTxt: string, path: string): boolean {
  return isPathAllowedByRules(parseWildcardAgentRules(robotsTxt), path);
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

/** Every built-asset `<script src>` / `<link rel="stylesheet" href>` in
 * `html` that points under CRAWLABLE_ASSETS_PATH — the JS/CSS a prerendered
 * snapshot's `<head>` references, which is also the only shape
 * `api/seo-audit.ts` knows how to content-type-check (a `.css` extension
 * means "expect `text/css`", anything else means "expect a JS mime type").
 * Scoped to `<script>`/`<link rel="stylesheet">` tags specifically, not any
 * `src`/`href` in the document, so a future non-JS/CSS `/assets/*` reference
 * (a font preload, an `<img>`) can't produce a false-positive "wrong
 * content-type" finding from a check that was never meant to cover it.
 * Regex, not an HTML parser: this only needs to catch the exact tag shape
 * Vite/prerender.ts emits, and api/seo-audit.ts is already the pure/
 * network-free-logic-vs-fetching split this repo uses elsewhere
 * (evaluateLiveAudit above). Used to catch the app-shell-fallthrough failure
 * mode a copied-forward snapshot can ship (issue #97): a stale asset
 * reference that 200s as `text/html` (Vercel's SPA catch-all) instead of
 * 404ing, which no structural/JSON-LD check here would ever notice. */
export function parseSnapshotAssetUrls(html: string): string[] {
  const urls = new Set<string>();
  const tagRe = /<(script|link)\b[^>]*>/g;
  for (const [tag, tagName] of html.matchAll(tagRe)) {
    if (tagName === 'link' && !/\brel="stylesheet"/.test(tag)) continue;
    const attrRe = tagName === 'link' ? /\bhref="([^"]+)"/ : /\bsrc="([^"]+)"/;
    const match = tag.match(attrRe);
    if (match && match[1].includes(CRAWLABLE_ASSETS_PATH)) urls.add(match[1]);
  }
  return [...urls];
}

/** The live audit (issue #54): checks production (not a local build) for
 * (1) robots.txt crawlability regressions — sitemap.xml, the OG fallback
 * image, the built `/assets/`, and each `CRAWLABLE_ICON_PATHS` entry all
 * blocked-by-`Disallow` checks (the issue #54 motivating bug: a stray
 * `Disallow: /` silently caught /sitemap.xml); (2) a dead prerender cadence
 * — sitemap.xml's build timestamp older than SEO_AUDIT_STALE_THRESHOLD_HOURS
 * — and (3) structural regressions on the live Landing snapshot, (if the
 * catalog has any published events yet) one live event snapshot, and (issue
 * #236) `/explore` per locale, reusing seoValidation.ts's in-build-gate
 * checks (issue #53) unchanged rather than reimplementing them. Pure/
 * network-free so it can be unit-tested directly; api/seo-audit.ts does the
 * fetching (including picking which event URL to fetch, via
 * parseSitemapEventUrls) and its own separate favicon content-type check. */
export function evaluateLiveAudit(params: {
  sitemapXml: string;
  landingHtml: string;
  robotsTxt: string;
  eventHtml?: string;
  /** One entry per locale variant of /explore's canonical URL (issue #236) —
   * best-effort, same as eventHtml: a locale that failed to fetch is simply
   * absent rather than failing the whole audit. */
  exploreHtmlByLocale?: Partial<Record<LocaleCode, string>>;
  now?: Date;
}): LiveAuditResult {
  const now = params.now ?? new Date();
  const issues: string[] = [];

  const robotsRules = parseWildcardAgentRules(params.robotsTxt);

  if (!isPathAllowedByRules(robotsRules, SITEMAP_PATH)) {
    issues.push(`robots.txt blocks ${SITEMAP_PATH} — Google Search Console will report "Couldn't fetch"`);
  }
  if (!isPathAllowedByRules(robotsRules, OG_FALLBACK_IMAGE_PATH)) {
    issues.push(`robots.txt blocks ${OG_FALLBACK_IMAGE_PATH} — the og:image fallback can't be crawled`);
  }
  if (!isPathAllowedByRules(robotsRules, `${CRAWLABLE_ASSETS_PATH}index.js`)) {
    issues.push(`robots.txt blocks ${CRAWLABLE_ASSETS_PATH} — Googlebot can't fetch the SPA's built assets`);
  }
  for (const iconPath of CRAWLABLE_ICON_PATHS) {
    if (!isPathAllowedByRules(robotsRules, iconPath)) {
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

  // No liveItemCount re-query here (issue #236) — unlike the in-build gate,
  // this is a best-effort production spot-check with no backend fan-out of
  // its own; assertListJsonLd's >=3 check simply no-ops without it.
  for (const [locale, html] of Object.entries(params.exploreHtmlByLocale ?? {})) {
    const parsedExplore = parseSnapshotHtml(html);
    const exploreIssues = validateSnapshotStructure(parsedExplore, {
      kind: 'list',
      locale,
      originPrefix: PRODUCTION_ORIGIN,
    });
    issues.push(...exploreIssues.map((issue) => `explore (${locale}) structural: ${issue}`));
  }

  return { ok: issues.length === 0, issues, buildTimestamp };
}
