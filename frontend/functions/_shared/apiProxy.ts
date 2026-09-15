/**
 * Backend proxy (issue #345) — forwards a `/api/*` request to the Render
 * Frankfurt backend (BACKEND_ORIGIN, src/constants.ts) with the `/api`
 * prefix stripped, reproducing vercel.json's old `/api/:path` rewrite. The
 * backend's own route shape carries no `/api` prefix.
 *
 * Same-origin proxying (rather than the SPA fetching Render directly) is
 * what lets the backend's httpOnly session cookie work as a first-party
 * cookie from the browser's perspective — see docs/adr/0001.
 *
 * Lives under `_shared/` (a Cloudflare Pages Functions routing exclusion —
 * an underscore-prefixed *directory*, unlike an underscore-prefixed
 * filename, is never scanned into the route manifest) rather than at
 * `functions/api/[[path]].ts`: a 2026-09-15 production incident found
 * `/api/*` traffic on eventradar.ee being answered entirely by the
 * SPA-fallback catch-all (`functions/[[path]].ts`) instead of this proxy —
 * Cloudflare's documented "more specific Function route wins" precedence
 * between multiple routed files did not hold. This module is now only ever
 * invoked by that root file's own explicit pathname dispatch, so there is
 * exactly one routed Function and no cross-file precedence for the platform
 * to get wrong.
 */
import { API_BASE, BACKEND_ORIGIN } from '../../src/constants.js';

// Stripped from the backend's response before it's re-emitted: `fetch()`
// transparently decodes a compressed body (if the backend or anything
// between Cloudflare and Render compresses it) but leaves the original
// wire-encoding headers on the Response object describing bytes that no
// longer match what's actually being sent — forwarding them verbatim would
// have the browser try to re-decode an already-decoded body, or truncate it
// against a stale Content-Length. `connection`/`transfer-encoding` are
// hop-by-hop and meaningless to re-emit on a fresh response.
const STRIPPED_RESPONSE_HEADERS = [
  'content-encoding',
  'content-length',
  'transfer-encoding',
  'connection',
];

export async function proxyToBackend(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const backendUrl = new URL(url.pathname.slice(API_BASE.length) + url.search, BACKEND_ORIGIN);

  const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
  const init: RequestInit & { duplex?: 'half' } = {
    method: request.method,
    headers: request.headers,
    redirect: 'manual',
  };
  if (hasBody) {
    init.body = request.body;
    // Required by fetch implementations (Workers runtime and undici alike)
    // whenever a Request carries a streamed (ReadableStream) body.
    init.duplex = 'half';
  }

  const backendResponse = await fetch(new Request(backendUrl, init));
  const headers = new Headers(backendResponse.headers);
  for (const header of STRIPPED_RESPONSE_HEADERS) headers.delete(header);

  return new Response(backendResponse.body, {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
    headers,
  });
}
