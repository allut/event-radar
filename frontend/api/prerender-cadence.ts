/**
 * Cadence gate for the independent `prerender-cadence` Deploy Hook (issue
 * #92) — a Vercel Serverless Function cron-job.org now hits every 6h
 * *instead of* POSTing straight to the Deploy Hook URL. Reads the production
 * branch's tip commit message and skips forwarding the request to the real
 * Deploy Hook when `shouldSkipCadenceTick` (src/lib/prerenderChain.ts) says a
 * chain round is genuinely in flight — removing the race where a
 * cadence-triggered build resumes the same fresh marker as the legitimate
 * chain continuation and both race `commitRoundMarker`'s branch push.
 *
 * Mirrors api/seo-audit.ts's shape: thin handler, shared-secret auth via the
 * same constant-time comparison (seoAuditAuth.ts's isValidAuditToken is
 * generic, not audit-specific, despite its name/module — reused as-is rather
 * than duplicated), and the same VercelRequest/VercelResponse shim (api/vercel.ts).
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
import {
  PRERENDER_CADENCE_GIT_BRANCH,
  PRERENDER_CADENCE_TOKEN_HEADER,
  PRERENDER_CADENCE_USER_AGENT,
  PRERENDER_CHAIN_GITHUB_REPO,
} from '../src/constants.js';
import { githubRequest } from '../src/lib/githubRequest.js';
import { shouldSkipCadenceTick } from '../src/lib/prerenderChain.js';
import { isValidAuditToken } from '../src/lib/seoAuditAuth.js';
import type { VercelRequest, VercelResponse } from './vercel';

/** Fetches the current tip commit message of PRERENDER_CADENCE_GIT_BRANCH.
 * `allut/event-radar` is private, so this must be an authenticated request —
 * uses the shared `githubRequest` helper (also used by seoAuditIssue.ts).
 * Reuses `GH_PRERENDER_CHAIN_TOKEN` (already provisioned with
 * `contents: write` on this repo for commitRoundMarker's git-data-API push
 * in scripts/prerender.ts) rather than `GH_ISSUE_TOKEN`, whose documented
 * scope (Issues: write) does not cover reading commits. Returns `null` on
 * missing token, any fetch/parse failure, or a non-ok response, so the
 * handler's caller can fail open (fire the hook, same as pre-#92 behavior)
 * instead of a GitHub hiccup silently killing the cadence forever. */
async function fetchTipCommitMessage(): Promise<string | null> {
  const token = process.env.GH_PRERENDER_CHAIN_TOKEN;
  if (!token) return null;
  try {
    const res = await githubRequest(
      PRERENDER_CHAIN_GITHUB_REPO,
      `/commits/${PRERENDER_CADENCE_GIT_BRANCH}`,
      token,
      PRERENDER_CADENCE_USER_AGENT,
    );
    if (!res.ok) return null;
    const body = (await res.json()) as { commit?: { message?: string } };
    return body.commit?.message ?? null;
  } catch {
    return null;
  }
}

export default async function handler(req: VercelRequest, res: VercelResponse): Promise<void> {
  if (req.method !== 'POST') {
    res.status(StatusCodes.METHOD_NOT_ALLOWED).end();
    return;
  }

  // Auth first, opaque 403 either way (OWASP audit F5) — see seo-audit.ts's
  // handler for why config presence must not be checked pre-auth.
  const expectedToken = process.env.PRERENDER_CADENCE_TOKEN;
  const deployHookUrl = process.env.PRERENDER_CADENCE_DEPLOY_HOOK_URL;
  const received = req.headers[PRERENDER_CADENCE_TOKEN_HEADER];
  const authorized =
    typeof received === 'string' && !!expectedToken && isValidAuditToken(received, expectedToken);
  if (!authorized) {
    res.status(StatusCodes.FORBIDDEN).json({ error: 'forbidden' });
    return;
  }

  if (!deployHookUrl) {
    res.status(StatusCodes.INTERNAL_SERVER_ERROR).json({
      error: 'prerender-cadence: PRERENDER_CADENCE_DEPLOY_HOOK_URL not configured',
    });
    return;
  }

  const commitMessage = await fetchTipCommitMessage();
  if (commitMessage !== null && shouldSkipCadenceTick(commitMessage, new Date())) {
    res.status(StatusCodes.OK).json({ skipped: true, reason: 'chain round in flight' });
    return;
  }

  let hookRes: Response;
  try {
    hookRes = await fetch(deployHookUrl, { method: 'POST' });
  } catch (error) {
    // Never interpolate the error into the response (OWASP audit G-7): a
    // fetch TypeError commonly embeds the failed URL, which would disclose
    // PRERENDER_CADENCE_DEPLOY_HOOK_URL — itself a credential (an
    // unauthenticated POST endpoint that triggers a production rebuild).
    console.error('prerender-cadence: failed to fire deploy hook', error);
    res.status(StatusCodes.BAD_GATEWAY).json({ error: 'failed to fire deploy hook' });
    return;
  }
  res.status(hookRes.ok ? StatusCodes.OK : StatusCodes.BAD_GATEWAY).json({
    skipped: false,
    deployHookStatus: hookRes.status,
  });
}
