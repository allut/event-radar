/**
 * Cadence gate for the independent `prerender-cadence` Deploy Hook (issue
 * #92) — a Cloudflare Pages Function cron-job.org now hits every 6h
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
 * than duplicated), and the same PagesFunction/Env shim
 * (functions/_shared/cloudflare.ts).
 *
 * Ported from the Vercel Serverless Function this used to be (issue #344):
 * only the platform boundary changed (Fetch API Request/Response instead of
 * the VercelRequest/VercelResponse shim, context.env instead of
 * process.env) — every imported helper is untouched.
 *
 * Routing note: file-based routing puts this at the exact path
 * `/api/prerender-cadence`. Cloudflare Pages matches an exact-path function
 * ahead of any catch-all sibling — so once #345 adds a catch-all
 * `/api/[[path]]` backend-proxy function alongside this one, no
 * negative-lookahead exclusion is needed the way vercel.json requires one
 * today. That catch-all doesn't exist yet as of this ticket (#344).
 */
import { StatusCodes } from 'http-status-codes';
import {
  PRERENDER_CADENCE_GIT_BRANCH,
  PRERENDER_CADENCE_TOKEN_HEADER,
  PRERENDER_CADENCE_USER_AGENT,
  PRERENDER_CHAIN_GITHUB_REPO,
} from '../../src/constants.js';
import { githubRequest } from '../../src/lib/githubRequest.js';
import { shouldSkipCadenceTick } from '../../src/lib/prerenderChain.js';
import { isValidAuditToken } from '../../src/lib/seoAuditAuth.js';
import { jsonResponse } from '../_shared/cloudflare.js';
import type { PagesFunction } from '../_shared/cloudflare.js';

interface Env {
  PRERENDER_CADENCE_TOKEN?: string;
  PRERENDER_CADENCE_DEPLOY_HOOK_URL?: string;
  GH_PRERENDER_CHAIN_TOKEN?: string;
}

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
async function fetchTipCommitMessage(token: string | undefined): Promise<string | null> {
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

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  if (request.method !== 'POST') {
    return new Response(null, { status: StatusCodes.METHOD_NOT_ALLOWED });
  }

  // Auth first, opaque 403 either way (OWASP audit F5) — see seo-audit.ts's
  // handler for why config presence must not be checked pre-auth.
  const expectedToken = env.PRERENDER_CADENCE_TOKEN;
  const deployHookUrl = env.PRERENDER_CADENCE_DEPLOY_HOOK_URL;
  const received = request.headers.get(PRERENDER_CADENCE_TOKEN_HEADER);
  const authorized =
    typeof received === 'string' && !!expectedToken && isValidAuditToken(received, expectedToken);
  if (!authorized) {
    return jsonResponse(StatusCodes.FORBIDDEN, { error: 'forbidden' });
  }

  if (!deployHookUrl) {
    return jsonResponse(StatusCodes.INTERNAL_SERVER_ERROR, {
      error: 'prerender-cadence: PRERENDER_CADENCE_DEPLOY_HOOK_URL not configured',
    });
  }

  const commitMessage = await fetchTipCommitMessage(env.GH_PRERENDER_CHAIN_TOKEN);
  if (commitMessage !== null && shouldSkipCadenceTick(commitMessage, new Date())) {
    return jsonResponse(StatusCodes.OK, { skipped: true, reason: 'chain round in flight' });
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
    return jsonResponse(StatusCodes.BAD_GATEWAY, { error: 'failed to fire deploy hook' });
  }
  return jsonResponse(hookRes.ok ? StatusCodes.OK : StatusCodes.BAD_GATEWAY, {
    skipped: false,
    deployHookStatus: hookRes.status,
  });
};
