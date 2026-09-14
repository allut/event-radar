/**
 * Catch-all backend proxy (issue #345) — Cloudflare Pages Function
 * reproducing vercel.json's `/api/:path` rewrite now that Vercel is being
 * decommissioned (issue #341). Forwards every `/api/*` request to the
 * Render Frankfurt backend (BACKEND_ORIGIN, src/constants.ts) with the
 * `/api` prefix stripped, same as the old rewrite — the backend's own route
 * shape carries no `/api` prefix.
 *
 * Same-origin proxying (rather than the SPA fetching Render directly) is
 * what lets the backend's httpOnly session cookie work as a first-party
 * cookie from the browser's perspective — see docs/adr/0001.
 *
 * Routing note: Cloudflare Pages matches the exact-path sibling functions
 * (api/seo-audit.ts, api/prerender-cadence.ts) ahead of this catch-all, so
 * those two shared-secret endpoints never reach here — their tokens never
 * get forwarded to the backend as if they were public API calls. See the
 * "Routing note" comment in each of those files.
 */
import { API_BASE, BACKEND_ORIGIN } from '../../src/constants.js';
import type { PagesFunction } from '../_shared/cloudflare.js';

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

export const onRequest: PagesFunction = async ({ request }) => {
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
};
