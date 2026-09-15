/**
 * SPA-fallback catch-all (issue #345) — Cloudflare Pages Function
 * reproducing vercel.json's `/((?!api/|assets/|_vercel/).*)` → app-shell.html
 * rewrite now that Vercel is being decommissioned (issue #341).
 *
 * Cloudflare Pages always serves a matching static asset before invoking any
 * Function, so this only ever runs for a path with no file in `dist/` —
 * which already excludes every prerendered route (scripts/prerender.ts
 * writes those as real `dist/<route>/index.html` files) and every built
 * asset under `/assets/*`. Cloudflare also prefers a more specific Function
 * route over this root-level catch-all, so `/api/*` requests are claimed by
 * `functions/api/[[path]].ts` (or its exact-path siblings) before they ever
 * reach here — no negative-lookahead exclusion needed, unlike vercel.json.
 *
 * Deliberately serves `app-shell.html`, not `index.html`: the build copies
 * the pristine, never-prerendered shell to `app-shell.html` *before*
 * `prerender.ts` overwrites `dist/index.html` with the Landing route's own
 * prerendered snapshot (APP_SHELL_FILENAME, src/constants.ts) — an unknown
 * client-side route must get the generic shell, not Landing's snapshot.
 *
 * `env.ASSETS.fetch()` applies Pages' own redirect rules to the requested
 * path first, including its default `.html`-extension stripping — so
 * fetching the `.html` filename directly gets back a 308 to the
 * extensionless path instead of the shell's content, which this function
 * would then hand straight to the browser as a visible redirect. Request
 * the extensionless "pretty path" instead, matching what Cloudflare's docs
 * say ASSETS.fetch expects.
 */
import { APP_SHELL_FILENAME } from '../src/constants.js';
import type { PagesFunction } from './_shared/cloudflare.js';

interface Env {
  ASSETS: { fetch: (request: Request) => Promise<Response> };
}

export const onRequest: PagesFunction<Env> = async ({ request, env }) => {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response(null, { status: 405 });
  }

  const shellPath = APP_SHELL_FILENAME.replace(/\.html$/, '');
  const shellUrl = new URL(`/${shellPath}`, request.url);
  return env.ASSETS.fetch(new Request(shellUrl, request));
};
