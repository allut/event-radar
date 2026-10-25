// SEO: canonical/hreflang/robots/JSON-LD, icons, sitemap, and the live SEO audit.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { LOCALES } from '../_generated/sharedConstants.js';

// ─── SEO ─────────────────────────────────────────────────────────────────────
// Absolute production origin — canonical/hreflang/og:url/og:image values are
// meaningless as relative URLs (crawlers and link-unfurlers read them with no
// browser location context), so useSeoMeta always resolves against this.
export const PRODUCTION_ORIGIN = 'https://eventradar.ee';
// Branded 1200×630 fallback OG image (frontend/public/og-fallback.png),
// served whenever an event has no image_url — same asset for all locales.
export const OG_FALLBACK_IMAGE_PATH = '/og-fallback.png';
// Vite's built JS/CSS output dir (must match vite.config.ts's `build.assetsDir`,
// which is unset there and so defaults to Vite's own 'assets') — robots.txt
// must explicitly Allow this or Googlebot can't fetch the SPA's own bundle
// when rendering a route (see buildRobotsTxt in scripts/prerender.ts).
export const CRAWLABLE_ASSETS_PATH = '/assets/';
// Site icon asset paths (Google Search Console site-icon requirement) — every
// path Googlebot-Image must be able to fetch, plus favicon.ico which needs
// its own live-audit content-type check (api/seo-audit.ts) since it's the
// one that silently 200s as the SPA shell when missing rather than 404ing.
export const FAVICON_ICO_PATH = '/favicon.ico';
export const ICON_96_PATH = '/icon-96.png';
export const ICON_192_PATH = '/icon-192.png';
export const ICON_512_PATH = '/icon-512.png';
export const ICON_MASKABLE_512_PATH = '/icon-maskable-512.png';
export const APPLE_TOUCH_ICON_PATH = '/apple-touch-icon.png';
export const CRAWLABLE_ICON_PATHS: string[] = [
  FAVICON_ICO_PATH,
  '/favicon.svg',
  ICON_96_PATH,
  ICON_192_PATH,
  ICON_512_PATH,
  ICON_MASKABLE_512_PATH,
  APPLE_TOUCH_ICON_PATH,
  '/site.webmanifest',
];
// <link rel> value index.html emits for the site icon, read back by
// seoValidation.ts's in-build gate as a CSS selector — same
// selector-from-shared-value pattern as CANONICAL_LINK_SELECTOR below.
export const ICON_REL = 'icon';
export const ICON_LINK_SELECTOR = `link[rel="${ICON_REL}"]`;
// og:description/meta description target length — Google truncates around
// ~155–160 chars; truncateForMeta (utils.ts) cuts at a word boundary under this.
export const SEO_DESCRIPTION_MAX_LENGTH = 157;

// Hreflang code for "no specific locale matches" — useSeoMeta (producer)
// and scripts/prerender.ts's buildSitemapXml (producer) both special-case
// this code to resolve to the bare Estonian URL rather than a localizedPath
// lookup; kept as one constant since both sites must agree.
export const SEO_XDEFAULT_CODE = 'x-default';
// Every LOCALES code plus SEO_XDEFAULT_CODE, in the order useSeoMeta emits
// hreflang <link> alternates.
export const SEO_HREFLANG_CODES: string[] = [...LOCALES.map((l) => l.code), SEO_XDEFAULT_CODE];
// robots meta content emitted by useSeoMeta and checked by seoValidation.ts's
// in-build validation gate (issue #53) — one pair of constants so the two
// can't silently drift.
export const ROBOTS_INDEX_FOLLOW = 'index, follow';
// seoValidation.ts's rich-result minimum item count for a JSON-LD ItemList
// (below this, Google's rich-result eligibility for the list drops).
export const SEO_RICH_ITEM_LIST_MIN = 3;
export const ROBOTS_NOINDEX = 'noindex';
// <link rel> value useSeoMeta emits for the canonical URL, read back by both
// seoValidation.ts (in-build gate) and scripts/prerender.ts (content-ready
// wait selector) as a CSS selector.
export const CANONICAL_REL = 'canonical';
export const CANONICAL_LINK_SELECTOR = `link[rel="${CANONICAL_REL}"]`;
// <script type> SeoTags renders its JSON-LD payload under, read back by
// seoValidation.ts and scripts/prerender.ts's embedChangeMarker as a CSS
// selector — one pair so a type-attribute typo can't silently break either.
export const JSONLD_SCRIPT_TYPE = 'application/ld+json';
export const JSONLD_SCRIPT_SELECTOR = `script[type="${JSONLD_SCRIPT_TYPE}"]`;

// sitemap.xml's dist-relative filename (prerender.ts writes it, api/seo-audit.ts
// fetches it) and its absolute-origin-relative path (referenced from
// robots.txt's Sitemap directive and the live audit's production fetch).
export const SITEMAP_FILENAME = 'sitemap.xml';
export const SITEMAP_PATH = `/${SITEMAP_FILENAME}`;
export const ROBOTS_TXT_FILENAME = 'robots.txt';
export const ROBOTS_TXT_PATH = `/${ROBOTS_TXT_FILENAME}`;

// Live-audit (issue #54, api/seo-audit.ts + src/lib/seoAudit.ts): sitemap.xml's
// <lastmod> (target.updatedAt when available, else the build timestamp — see
// prerender.ts's buildSitemapXml) older than this is treated as a dead prerender cadence.
// 6h backend publish/geocode cadence (LLM_PASS_INTERVAL_HOURS, backend
// app/constants/jobs.py) + a 2h buffer.
export const SEO_AUDIT_STALE_THRESHOLD_HOURS = 8;
// GitHub repo the live audit files/updates/closes its failure issue against
// (CLAUDE.md "Issue tracker") and the fixed label it searches/tags by.
export const SEO_AUDIT_GITHUB_REPO = 'allut/event-radar';
export const SEO_AUDIT_ISSUE_LABEL = 'seo-audit-failure';
export const GITHUB_API_BASE_URL = 'https://api.github.com';
// GitHub REST API version header (X-GitHub-Api-Version) — pinned so a future
// GitHub default-version bump can't silently change response shapes.
export const GITHUB_API_VERSION = '2022-11-28';
// Shared-secret header cron-job.org sends on its seo-audit ping, mirroring
// the backend's /internal/tick pattern (docs/backend-ops.md "External Cron Jobs"). Distinct from
// PRERENDER_CADENCE_TOKEN_HEADER and the backend's own X-Internal-Token: if
// both Cloudflare Pages Functions ever shared one header name, a future
// refactor that merged their handlers could forward this header's value to
// the backend under a name it wasn't meant for — a shared name with the
// backend's header would leak SEO_AUDIT_TOKEN into that proxied request.
export const SEO_AUDIT_TOKEN_HEADER = 'x-seo-audit-token';

// JSON-LD @context (structuredData.ts).
export const SCHEMA_ORG_CONTEXT = 'https://schema.org';

// GitHub API User-Agent for lib/seoAuditIssue.ts's githubRequest() call.
export const SEO_AUDIT_USER_AGENT = 'event-radar-seo-audit';
