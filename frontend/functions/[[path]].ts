/**
 * Single Cloudflare Pages Function entry point for the whole site (issue
 * #345, restructured 2026-09-15). Originally this file only handled the
 * SPA-fallback rewrite and relied on Cloudflare's file-based routing to hand
 * `/api/*` off to sibling Function files (`functions/api/[[path]].ts`,
 * `functions/api/seo-audit.ts`, `functions/api/prerender-cadence.ts`) ahead
 * of this root catch-all, per Cloudflare's documented
 * exact-path/nested-catch-all-beats-root-catch-all precedence.
 *
 * That precedence did not hold in production (~2 weeks after #345/#354
 * shipped): every `/api/*` request on eventradar.ee was being answered by
 * this file's own SPA-fallback logic — serving the prerendered Landing page
 * HTML for GET requests, and this file's blanket 405 for anything else —
 * without ever reaching the sibling Function files or the Render backend at
 * all. Unlike the #354 static-asset case (below), a Function can't
 * self-defend against never being invoked in the first place. So this file
 * is now the *only* routed Function in the project: the three former
 * siblings' logic moved to plain functions under `_shared/` (a directory
 * Cloudflare's route scanner excludes, per `_shared/apiProxy.ts`'s module
 * comment) and this file dispatches to them itself, by exact pathname
 * match, before falling through to the SPA-fallback logic below. There is
 * now exactly one Function route, so there is no cross-file precedence left
 * for the platform to get wrong.
 *
 * SPA-fallback rewrite (issue #345), reproducing vercel.json's
 * `/((?!api/|assets/|_vercel/).*)` → app-shell.html rewrite now that Vercel
 * is being decommissioned (issue #341):
 *
 * Cloudflare Pages is *documented* to serve a matching static asset before
 * invoking any Function, which would make this only ever run for a path
 * with no file in `dist/` — already excluding every prerendered route
 * (scripts/prerender.ts writes those as real `dist/<route>/index.html`
 * files) and every built asset under `/assets/*`. In production that
 * precedence did not hold either (issue #354): this root-level `[[path]].ts`
 * catch-all was observed swallowing *every* non-`/api` request, including
 * `/assets/*.js`/`.css` and plain `public/`-copied files like
 * `favicon.svg` that unquestionably exist in `dist/`, serving the app-shell
 * for all of them — breaking prerendered SEO pages, the sitemap, and the
 * app itself (the shell's own JS/CSS came back as `text/html`, so the SPA
 * never mounted). Rather than trust that precedence, this explicitly tries
 * `env.ASSETS.fetch()` against the *original* request first and only falls
 * through to the shell on a 404 — self-defending against that platform
 * behavior regardless of which Cloudflare-side quirk causes it.
 *
 * Deliberately serves `app-shell.html`, not `index.html`, once a route is
 * confirmed to have no real asset: the build copies the pristine,
 * never-prerendered shell to `app-shell.html` *before* `prerender.ts`
 * overwrites `dist/index.html` with the Landing route's own prerendered
 * snapshot (APP_SHELL_FILENAME, src/constants.ts) — an unknown client-side
 * route must get the generic shell, not Landing's snapshot.
 *
 * `env.ASSETS.fetch()` applies Pages' own redirect rules to the requested
 * path first, including its default `.html`-extension stripping — so
 * fetching the `.html` filename directly gets back a 308 to the
 * extensionless path instead of the shell's content, which this function
 * would then hand straight to the browser as a visible redirect. Request
 * the extensionless "pretty path" instead, matching what Cloudflare's docs
 * say ASSETS.fetch expects.
 */
import { API_BASE, APP_SHELL_FILENAME } from '../src/constants.js';
import type { PagesFunction } from './_shared/cloudflare.js';
import { proxyToBackend } from './_shared/apiProxy.js';
import { handleSeoAudit } from './_shared/seoAuditHandler.js';
import type { SeoAuditEnv } from './_shared/seoAuditHandler.js';
import { handlePrerenderCadence } from './_shared/prerenderCadenceHandler.js';
import type { PrerenderCadenceEnv } from './_shared/prerenderCadenceHandler.js';

interface Env extends SeoAuditEnv, PrerenderCadenceEnv {
  ASSETS: { fetch: (request: Request) => Promise<Response> };
}

export const onRequest: PagesFunction<Env> = async ({ request, env }) => {
  const url = new URL(request.url);

  // Exact-path shared-secret endpoints, checked ahead of the generic API
  // proxy below so their tokens never get forwarded to the backend as if
  // they were public API calls.
  if (url.pathname === `${API_BASE}/seo-audit`) {
    return handleSeoAudit(request, env);
  }
  if (url.pathname === `${API_BASE}/prerender-cadence`) {
    return handlePrerenderCadence(request, env);
  }
  if (url.pathname === API_BASE || url.pathname.startsWith(`${API_BASE}/`)) {
    return proxyToBackend(request);
  }

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response(null, { status: 405 });
  }

  // Try the real asset first (issue #354) — a prerendered route, a built
  // /assets/* file, or any other real dist/ file must win here even though
  // the platform is documented to have already served it before this
  // Function ever ran. Only a genuine miss (404) falls through to the shell.
  const directResponse = await env.ASSETS.fetch(request);
  if (directResponse.status !== 404) {
    return directResponse;
  }

  const shellPath = APP_SHELL_FILENAME.replace(/\.html$/, '');
  const shellUrl = new URL(`/${shellPath}`, request.url);
  return env.ASSETS.fetch(new Request(shellUrl, request));
};
