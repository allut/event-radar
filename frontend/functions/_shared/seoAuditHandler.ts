/**
 * Independent live SEO audit (issue #54) — hit every 6h by its own
 * cron-job.org job (offset from the prerender-rebuild job, issue #52),
 * mirroring the backend's `/internal/tick` keepalive pattern but living on
 * the Cloudflare side since the check it runs (src/lib/seoAudit.ts's
 * evaluateLiveAudit) reuses seoValidation.ts's in-build-gate assertions
 * (issue #53) unchanged, and those are TypeScript.
 *
 * Deliberately thin: all real logic lives in src/lib (seoAudit.ts,
 * seoAuditIssue.ts, seoAuditAuth.ts) so it's unit-testable under vitest —
 * this file only wires auth, the two production fetches, and the GitHub
 * report/recover calls together.
 *
 * Ported from the Vercel Serverless Function this used to be (issue #344):
 * only the platform boundary changed (Fetch API Request/Response instead of
 * the VercelRequest/VercelResponse shim, context.env instead of
 * process.env) — every imported helper is untouched.
 *
 * Lives under `_shared/` rather than at `functions/api/seo-audit.ts` — see
 * `_shared/apiProxy.ts`'s module comment for why: a 2026-09-15 production
 * incident found Cloudflare's documented exact-path-beats-catch-all Function
 * routing precedence did not hold, so `functions/[[path]].ts` is now the
 * sole routed Function and dispatches here itself by exact pathname.
 */
import { StatusCodes } from 'http-status-codes';
import { FAVICON_ICO_PATH, LOCALES, PRODUCTION_ORIGIN, ROUTES, SEO_AUDIT_TOKEN_HEADER, SITEMAP_PATH } from '../../src/constants.js';
import type { LocaleCode } from '../../src/constants.js';
import { localizedPath } from '../../src/lib/urlLocale.js';
import { evaluateLiveAudit, parseSitemapEventUrls, parseSnapshotAssetUrls } from '../../src/lib/seoAudit.js';
import { reportAuditFailure, reportAuditRecovery } from '../../src/lib/seoAuditIssue.js';
import { isValidAuditToken } from '../../src/lib/seoAuditAuth.js';
import { jsonResponse } from './cloudflare.js';

export interface SeoAuditEnv {
  SEO_AUDIT_TOKEN?: string;
  GH_ISSUE_TOKEN?: string;
}

export async function handleSeoAudit(request: Request, env: SeoAuditEnv): Promise<Response> {
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
      fetch(`${PRODUCTION_ORIGIN}/robots.txt`),
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
    return jsonResponse(StatusCodes.BAD_GATEWAY, { error: `failed to fetch production pages: ${String(error)}` });
  }

  // One live event page, if the catalog has any published yet — lets the
  // audit exercise validateSnapshotStructure's `kind: 'event'` path
  // (JSON-LD Event assertions), not just Landing's `kind: 'website'` path.
  let eventHtml: string | undefined;
  const [firstEventUrl] = parseSitemapEventUrls(sitemapXml);
  if (firstEventUrl) {
    try {
      const eventRes = await fetch(firstEventUrl);
      if (eventRes.ok) {
        eventHtml = await eventRes.text();
      }
      // A non-ok fetch here isn't treated as a hard failure of the whole
      // audit run — freshness + Landing structure are still checked; a
      // flaky single-event fetch shouldn't mask those.
    } catch {
      // Same reasoning — best-effort only.
    }
  }

  // Explore's canonical URL, all 3 locales (issue #236) — best-effort, same
  // as eventHtml above: a single locale's fetch failing doesn't fail the
  // whole audit run.
  const exploreHtmlByLocale: Partial<Record<LocaleCode, string>> = {};
  await Promise.all(
    LOCALES.map(async ({ code }) => {
      try {
        const res = await fetch(`${PRODUCTION_ORIGIN}${localizedPath(ROUTES.explore, code)}`);
        if (res.ok) exploreHtmlByLocale[code] = await res.text();
      } catch {
        // Best-effort only — see comment above.
      }
    }),
  );

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
    for (const assetUrl of parseSnapshotAssetUrls(eventHtml)) {
      const absoluteUrl = `${PRODUCTION_ORIGIN}${assetUrl}`;
      try {
        const assetRes = await fetch(absoluteUrl);
        const assetContentType = assetRes.headers.get('content-type');
        const isCss = assetUrl.endsWith('.css');
        const expectedType = isCss ? 'text/css' : 'javascript';
        if (!assetRes.ok || !assetContentType || !assetContentType.includes(expectedType)) {
          result.issues.push(
            `event snapshot asset ${assetUrl} content-type is "${assetContentType ?? 'missing'}" (status ${assetRes.status}), expected ${expectedType} — snapshot likely references a previous build's asset hash`,
          );
          result.ok = false;
        }
      } catch (error) {
        result.issues.push(`event snapshot asset ${assetUrl} failed to fetch: ${String(error)}`);
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
    // problem buried in a JSON field nobody's watching.
    return jsonResponse(StatusCodes.INTERNAL_SERVER_ERROR, { ...result, reportError: String(error) });
  }

  return jsonResponse(StatusCodes.OK, result);
}
