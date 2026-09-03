/**
 * Independent live SEO audit (issue #54) — a Vercel Serverless Function, hit
 * every 6h by its own cron-job.org job (offset from the prerender-rebuild
 * job, issue #52), mirroring the backend's `/internal/tick` keepalive
 * pattern but living on the Vercel side since the check it runs
 * (src/lib/seoAudit.ts's evaluateLiveAudit) reuses seoValidation.ts's
 * in-build-gate assertions (issue #53) unchanged, and those are TypeScript.
 *
 * Deliberately thin: all real logic lives in src/lib (seoAudit.ts,
 * seoAuditIssue.ts, seoAuditAuth.ts) so it's unit-testable under vitest —
 * this file only wires auth, the two production fetches, and the GitHub
 * report/recover calls together.
 *
 * Routing note: this path must stay excluded from vercel.json's
 * `/api/:path*` → Render backend rewrite (see the negative-lookahead there)
 * or every request here gets proxied to the backend and 404s instead of
 * running this function.
 */
import { StatusCodes } from 'http-status-codes';
// Vercel runs this file as plain Node ESM with no bundler in front (unlike
// the Vite SPA build or tsx-run scripts elsewhere in this repo), so Node's
// ESM resolver requires explicit .js extensions on every relative import —
// including transitively, in every local module this file pulls in.
import { FAVICON_ICO_PATH, LOCALES, PRODUCTION_ORIGIN, ROUTES, SEO_AUDIT_TOKEN_HEADER, SITEMAP_PATH } from '../src/constants.js';
import type { LocaleCode } from '../src/constants.js';
import { localizedPath } from '../src/lib/urlLocale.js';
import { evaluateLiveAudit, parseSitemapEventUrls } from '../src/lib/seoAudit.js';
import { reportAuditFailure, reportAuditRecovery } from '../src/lib/seoAuditIssue.js';
import { isValidAuditToken } from '../src/lib/seoAuditAuth.js';
import type { VercelRequest, VercelResponse } from './vercel';

export default async function handler(req: VercelRequest, res: VercelResponse): Promise<void> {
  if (req.method !== 'POST') {
    res.status(StatusCodes.METHOD_NOT_ALLOWED).end();
    return;
  }

  // Auth first, opaque 403 either way (OWASP audit F5): checking config
  // presence before the token let an unauthenticated caller distinguish
  // "misconfigured" (500 naming the missing env vars) from "configured but
  // wrong token" (403), fingerprinting deploy state pre-auth.
  const expectedToken = process.env.SEO_AUDIT_TOKEN;
  const githubToken = process.env.GH_ISSUE_TOKEN;
  const received = req.headers[SEO_AUDIT_TOKEN_HEADER];
  const authorized =
    typeof received === 'string' && !!expectedToken && isValidAuditToken(received, expectedToken);
  if (!authorized) {
    res.status(StatusCodes.FORBIDDEN).json({ error: 'forbidden' });
    return;
  }

  if (!githubToken) {
    // Caller has already proven possession of the shared secret, so it's
    // safe to disclose the remaining misconfiguration now.
    res.status(StatusCodes.INTERNAL_SERVER_ERROR).json({ error: 'seo-audit: GH_ISSUE_TOKEN not configured' });
    return;
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
      res.status(StatusCodes.BAD_GATEWAY).json({
        error: `failed to fetch production pages: sitemap.xml=${sitemapRes.status}, /=${landingRes.status}, robots.txt=${robotsRes.status}, favicon.ico=${faviconRes.status}`,
      });
      return;
    }
    [sitemapXml, landingHtml, robotsTxt] = await Promise.all([sitemapRes.text(), landingRes.text(), robotsRes.text()]);
    faviconContentType = faviconRes.headers.get('content-type');
  } catch (error) {
    res.status(StatusCodes.BAD_GATEWAY).json({ error: `failed to fetch production pages: ${String(error)}` });
    return;
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
  // can't see: Vercel's SPA catch-all rewrite serves /favicon.ico as a 200
  // text/html app-shell response whenever no real file exists at that path.
  if (!faviconContentType || !faviconContentType.startsWith('image/')) {
    result.issues.push(
      `favicon.ico content-type is "${faviconContentType ?? 'missing'}", expected an image/* type — Google can't use it as the site icon`,
    );
    result.ok = false;
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
    res.status(StatusCodes.INTERNAL_SERVER_ERROR).json({ ...result, reportError: String(error) });
    return;
  }

  res.status(StatusCodes.OK).json(result);
}
