/**
 * Independent live SEO audit (issue #54) — a Cloudflare Pages Function, hit
 * every 6h by its own cron-job.org job (offset from the prerender-rebuild
 * job, issue #52), mirroring the backend's `/internal/tick` keepalive
 * pattern but living on the Cloudflare side since the check it runs
 * (src/lib/seoAudit.ts's evaluateLiveAudit) reuses seoValidation.ts's
 * in-build-gate assertions (issue #53) unchanged, and those are TypeScript.
 *
 * Deliberately thin: all real logic lives in src/lib (seoAudit.ts,
 * seoAuditIssue.ts, seoAuditAuth.ts) so it's unit-testable under vitest —
 * this file only wires auth, the two production fetches, and the GitHub
 * report/recover calls together.
 *
 * Fetch API Request/Response, context.env for config (issue #344).
 *
 * Routing note: file-based routing puts this at the exact path
 * `/api/seo-audit`. Cloudflare Pages matches an exact-path function ahead of
 * any catch-all sibling — so the catch-all `/api/[[path]]` backend-proxy
 * function (#345) never claims this path, no negative-lookahead exclusion
 * needed. The handler is exported as `onRequest` (not `onRequestPost`) on
 * purpose: a method-specific export lets a GET fall through to the catch-all
 * proxy, which would forward this endpoint's secret header to the backend
 * (OWASP audit L-8); non-POST is answered 405 here instead.
 */
import { StatusCodes } from 'http-status-codes';
import { FAVICON_ICO_PATH, LOCALES, PRODUCTION_ORIGIN, ROBOTS_TXT_PATH, ROUTES, SEO_AUDIT_TOKEN_HEADER, SITEMAP_PATH } from '../../src/constants.js';
import type { LocaleCode } from '../../src/constants.js';
import { localizedPath } from '../../src/lib/urlLocale.js';
import { evaluateLiveAudit, parseFirstSitemapEventUrl, parseSnapshotAssetUrls } from '../../src/lib/seoAudit.js';
import { reportAuditFailure, reportAuditRecovery } from '../../src/lib/seoAuditIssue.js';
import { isValidAuditToken } from '../../src/lib/seoAuditAuth.js';
import { jsonResponse } from '../_shared/cloudflare.js';
import type { PagesFunction } from '../_shared/cloudflare.js';

interface Env {
  SEO_AUDIT_TOKEN?: string;
  GH_ISSUE_TOKEN?: string;
}

export const onRequest: PagesFunction<Env> = async ({ request, env }) => {
  if (request.method !== 'POST') {
    return new Response(null, { status: StatusCodes.METHOD_NOT_ALLOWED });
  }

  // Auth first, opaque 403 either way (OWASP audit F5): checking config
  // presence before the token let an unauthenticated caller distinguish
  // "misconfigured" (500 naming the missing env vars) from "configured but
  // wrong token" (403), fingerprinting deploy state pre-auth.
  const expectedToken = env.SEO_AUDIT_TOKEN;
  const githubToken = env.GH_ISSUE_TOKEN;
  const received = request.headers.get(SEO_AUDIT_TOKEN_HEADER);
  const authorized =
    typeof received === 'string' && !!expectedToken && isValidAuditToken(received, expectedToken);
  if (!authorized) {
    return jsonResponse(StatusCodes.FORBIDDEN, { error: 'forbidden' });
  }

  if (!githubToken) {
    // Caller has already proven possession of the shared secret, so it's
    // safe to disclose the remaining misconfiguration now.
    return jsonResponse(StatusCodes.INTERNAL_SERVER_ERROR, { error: 'seo-audit: GH_ISSUE_TOKEN not configured' });
  }

  let sitemapXml: string;
  let landingHtml: string;
  let robotsTxt: string;
  let faviconContentType: string | null;
  try {
    const [sitemapRes, landingRes, robotsRes, faviconRes] = await Promise.all([
      fetch(`${PRODUCTION_ORIGIN}${SITEMAP_PATH}`),
      fetch(`${PRODUCTION_ORIGIN}/`),
      fetch(`${PRODUCTION_ORIGIN}${ROBOTS_TXT_PATH}`),
      fetch(`${PRODUCTION_ORIGIN}${FAVICON_ICO_PATH}`),
    ]);
    if (!sitemapRes.ok || !landingRes.ok || !robotsRes.ok || !faviconRes.ok) {
      return jsonResponse(StatusCodes.BAD_GATEWAY, {
        error: `failed to fetch production pages: sitemap.xml=${sitemapRes.status}, /=${landingRes.status}, robots.txt=${robotsRes.status}, favicon.ico=${faviconRes.status}`,
      });
    }
    [sitemapXml, landingHtml, robotsTxt] = await Promise.all([sitemapRes.text(), landingRes.text(), robotsRes.text()]);
    faviconContentType = faviconRes.headers.get('content-type');
  } catch (error) {
    // Never interpolate the raw error into the response (OWASP audit G-7) —
    // a fetch TypeError can embed request details a caller shouldn't see.
    console.error('seo-audit: failed to fetch production pages', error);
    return jsonResponse(StatusCodes.BAD_GATEWAY, { error: 'failed to fetch production pages' });
  }

  // One live event page, if the catalog has any published yet — lets the
  // audit exercise validateSnapshotStructure's `kind: 'event'` path
  // (JSON-LD Event assertions), not just Landing's `kind: 'website'` path.
  // Best-effort: a non-ok or failed fetch isn't a hard failure of the whole
  // audit run — freshness + Landing structure are still checked; a flaky
  // single-event fetch shouldn't mask those.
  async function fetchEventHtml(): Promise<string | undefined> {
    const firstEventUrl = parseFirstSitemapEventUrl(sitemapXml);
    if (!firstEventUrl) return undefined;
    try {
      const eventRes = await fetch(firstEventUrl);
      return eventRes.ok ? await eventRes.text() : undefined;
    } catch {
      return undefined;
    }
  }

  // Explore's canonical URL, all 3 locales (issue #236) — best-effort, same
  // as the event fetch: a single locale's fetch failing doesn't fail the
  // whole audit run. Runs concurrently with the event fetch above (they're
  // independent), not after it.
  const exploreHtmlByLocale: Partial<Record<LocaleCode, string>> = {};
  const [eventHtml] = await Promise.all([
    fetchEventHtml(),
    ...LOCALES.map(async ({ code }) => {
      try {
        const res = await fetch(`${PRODUCTION_ORIGIN}${localizedPath(ROUTES.explore, code)}`);
        if (res.ok) exploreHtmlByLocale[code] = await res.text();
      } catch {
        // Best-effort only — see comment above.
      }
    }),
  ]);

  const result = evaluateLiveAudit({ sitemapXml, landingHtml, robotsTxt, eventHtml, exploreHtmlByLocale });

  // Catches the app-shell-fallthrough failure mode robots.txt/HTML assertions
  // can't see: the SPA-fallback rewrite serves /favicon.ico as a 200
  // text/html app-shell response whenever no real file exists at that path.
  if (!faviconContentType || !faviconContentType.startsWith('image/')) {
    result.issues.push(
      `favicon.ico content-type is "${faviconContentType ?? 'missing'}", expected an image/* type — Google can't use it as the site icon`,
    );
    result.ok = false;
  }

  // Same app-shell-fallthrough failure mode as the favicon check above, for
  // the event snapshot's own built assets (issue #97): a copied-forward
  // snapshot that ships a previous build's asset hash gets a 200 `text/html`
  // app-shell response instead of a 404, which no structural/JSON-LD check
  // can see. Best-effort, same as eventHtml's own fetch above — no event
  // snapshot yet means nothing to check here.
  if (eventHtml) {
    // Concurrent — each asset check is an independent fetch. Every check
    // returns its own issue (or null) so `result.issues` keeps the asset
    // order of the snapshot rather than completion order.
    const assetIssues = await Promise.all(
      parseSnapshotAssetUrls(eventHtml).map(async (assetUrl): Promise<string | null> => {
        try {
          const assetRes = await fetch(new URL(assetUrl, PRODUCTION_ORIGIN));
          const assetContentType = assetRes.headers.get('content-type');
          const isCss = assetUrl.endsWith('.css');
          const expectedType = isCss ? 'text/css' : 'javascript';
          if (!assetRes.ok || !assetContentType || !assetContentType.includes(expectedType)) {
            return `event snapshot asset ${assetUrl} content-type is "${assetContentType ?? 'missing'}" (status ${assetRes.status}), expected ${expectedType} — snapshot likely references a previous build's asset hash`;
          }
          return null;
        } catch (error) {
          return `event snapshot asset ${assetUrl} failed to fetch: ${String(error)}`;
        }
      }),
    );
    for (const issue of assetIssues) {
      if (issue !== null) {
        result.issues.push(issue);
        result.ok = false;
      }
    }
  }

  try {
    if (result.ok) {
      await reportAuditRecovery(githubToken);
    } else {
      await reportAuditFailure(githubToken, result.issues);
    }
  } catch (error) {
    // The audit's own pass/fail finding (`result`) is still returned in the
    // body either way — a GitHub reporting hiccup doesn't change what was
    // actually found in production. But this endpoint's entire alerting
    // mechanism *is* the GitHub issue (issue #46's Regression checks: no
    // new alerting channel), so if reporting itself is broken, that must be
    // visible somewhere an operator would notice — a non-2xx status, which
    // cron-job.org's own monitoring surfaces, rather than a 200 with the
    // problem buried in a JSON field nobody's watching. The error itself is
    // logged, not echoed in the response (OWASP audit G-7) — this call path
    // stringifies errors from GitHub API requests made with GH_ISSUE_TOKEN.
    console.error('seo-audit: failed to report audit result to GitHub', error);
    return jsonResponse(StatusCodes.INTERNAL_SERVER_ERROR, { ...result, reportError: 'failed to report audit result to GitHub' });
  }

  return jsonResponse(StatusCodes.OK, result);
};
