/**
 * Cadence gate for the independent `prerender-cadence` Deploy Hook (issue
 * #92) — cron-job.org hits this every 6h *instead of* POSTing straight to
 * the Deploy Hook URL. Reads the production branch's tip commit message and
 * skips forwarding the request to the real Deploy Hook when
 * `shouldSkipCadenceTick` (src/lib/prerenderChain.ts) says a chain round is
 * genuinely in flight — removing the race where a cadence-triggered build
 * resumes the same fresh marker as the legitimate chain continuation and
 * both race `commitRoundMarker`'s branch push.
 *
 * Mirrors seoAuditHandler.ts's shape: thin handler, shared-secret auth via
 * the same constant-time comparison (seoAuditAuth.ts's isValidAuditToken is
 * generic, not audit-specific, despite its name/module — reused as-is rather
 * than duplicated).
 *
 * Ported from the Vercel Serverless Function this used to be (issue #344):
 * only the platform boundary changed (Fetch API Request/Response instead of
 * the VercelRequest/VercelResponse shim, context.env instead of
 * process.env) — every imported helper is untouched.
 *
 * Lives under `_shared/` rather than at `functions/api/prerender-cadence.ts`
 * — see `_shared/apiProxy.ts`'s module comment for why: a 2026-09-15
 * production incident found Cloudflare's documented exact-path-beats-catch-
 * all Function routing precedence did not hold, so `functions/[[path]].ts`
 * is now the sole routed Function and dispatches here itself by exact
 * pathname.
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
import { jsonResponse } from './cloudflare.js';

export interface PrerenderCadenceEnv {
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

export async function handlePrerenderCadence(request: Request, env: PrerenderCadenceEnv): Promise<Response> {
  if (request.method !== 'POST') {
    return new Response(null, { status: StatusCodes.METHOD_NOT_ALLOWED });
  }

  // Auth first, opaque 403 either way (OWASP audit F5) — see
  // seoAuditHandler.ts's handler for why config presence must not be
  // checked pre-auth.
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
    return jsonResponse(StatusCodes.BAD_GATEWAY, { error: `failed to fire deploy hook: ${String(error)}` });
  }
  return jsonResponse(hookRes.ok ? StatusCodes.OK : StatusCodes.BAD_GATEWAY, {
    skipped: false,
    deployHookStatus: hookRes.status,
  });
}
