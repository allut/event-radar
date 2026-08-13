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
import type { VercelRequest, VercelResponse } from '@vercel/node';
import { StatusCodes } from 'http-status-codes';
import { PRODUCTION_ORIGIN, SEO_AUDIT_TOKEN_HEADER } from '../src/constants';
import { evaluateLiveAudit, parseSitemapEventUrls } from '../src/lib/seoAudit';
import { reportAuditFailure, reportAuditRecovery } from '../src/lib/seoAuditIssue';
import { isValidAuditToken } from '../src/lib/seoAuditAuth';

export default async function handler(req: VercelRequest, res: VercelResponse): Promise<void> {
  const expectedToken = process.env.SEO_AUDIT_TOKEN;
  const githubToken = process.env.GH_ISSUE_TOKEN;
  if (!expectedToken || !githubToken) {
    res.status(StatusCodes.INTERNAL_SERVER_ERROR).json({ error: 'seo-audit: SEO_AUDIT_TOKEN/GH_ISSUE_TOKEN not configured' });
    return;
  }

  const received = req.headers[SEO_AUDIT_TOKEN_HEADER];
  if (typeof received !== 'string' || !isValidAuditToken(received, expectedToken)) {
    res.status(StatusCodes.FORBIDDEN).json({ error: 'invalid token' });
    return;
  }

  let sitemapXml: string;
  let landingHtml: string;
  try {
    const [sitemapRes, landingRes] = await Promise.all([
      fetch(`${PRODUCTION_ORIGIN}/sitemap.xml`),
      fetch(`${PRODUCTION_ORIGIN}/`),
    ]);
    if (!sitemapRes.ok || !landingRes.ok) {
      res.status(StatusCodes.BAD_GATEWAY).json({
        error: `failed to fetch production pages: sitemap.xml=${sitemapRes.status}, /=${landingRes.status}`,
      });
      return;
    }
    [sitemapXml, landingHtml] = await Promise.all([sitemapRes.text(), landingRes.text()]);
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

  const result = evaluateLiveAudit({ sitemapXml, landingHtml, eventHtml });

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
