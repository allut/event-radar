/**
 * SPA-fallback catch-all (issue #345) — a Cloudflare Pages Function that
 * serves `app-shell.html` for any route with no matching file in `dist/`.
 *
 * Cloudflare Pages is *documented* to serve a matching static asset before
 * invoking any Function, which would make this only ever run for a path
 * with no file in `dist/` — already excluding every prerendered route
 * (scripts/prerender.ts writes those as real `dist/<route>/index.html`
 * files) and every built asset under `/assets/*`. In production that
 * precedence did not hold (issue #354): this root-level `[[path]].ts`
 * catch-all was observed swallowing *every* non-`/api` request, including
 * `/assets/*.js`/`.css` and plain `public/`-copied files like
 * `favicon.svg` that unquestionably exist in `dist/`, serving the app-shell
 * for all of them — breaking prerendered SEO pages, the sitemap, and the
 * app itself (the shell's own JS/CSS came back as `text/html`, so the SPA
 * never mounted). Rather than trust that precedence, this now explicitly
 * tries `env.ASSETS.fetch()` against the *original* request first and only
 * falls through to the shell on a 404 — self-defending against that
 * platform behavior regardless of which Cloudflare-side quirk causes it.
 * Cloudflare also prefers a more specific Function route over this
 * root-level catch-all, so `/api/*` requests are claimed by
 * `functions/api/[[path]].ts` (or its exact-path siblings) before they ever
 * reach here — no negative-lookahead exclusion needed.
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
import { APP_SHELL_FILENAME } from '../src/constants.js';
import type { PagesFunction } from './_shared/cloudflare.js';

interface Env {
  ASSETS: { fetch: (request: Request) => Promise<Response> };
}

export const onRequest: PagesFunction<Env> = async ({ request, env }) => {
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
