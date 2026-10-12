/**
 * Catch-all backend proxy (issue #345) — a Cloudflare Pages Function that
 * forwards every `/api/*` request to the Render Frankfurt backend
 * (BACKEND_ORIGIN, src/constants/api.ts) with the `/api` prefix stripped — the
 * backend's own route shape carries no `/api` prefix.
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
import { StatusCodes } from 'http-status-codes';
import { API_BASE, BACKEND_ORIGIN } from '../../src/constants/api.js';
import { PRERENDER_CADENCE_TOKEN_HEADER } from '../../src/constants/prerender.js';
import { SEO_AUDIT_TOKEN_HEADER } from '../../src/constants/seo.js';
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

interface Env {
  EDGE_SHARED_SECRET?: string;
}

export const onRequest: PagesFunction<Env> = async ({ request, env }) => {
  const url = new URL(request.url);
  const backendUrl = new URL(url.pathname.slice(API_BASE.length) + url.search, BACKEND_ORIGIN);

  // OWASP audit G-2: `new URL(relative, base)` discards `base`'s authority
  // when `relative` is protocol-relative (starts with `//`), which a request
  // path beginning `/api//host/...` produces after the API_BASE prefix is
  // stripped — resolving to an attacker-controlled host instead of the
  // backend. Cloudflare's router happens not to route such a path to this
  // function today, but that's undocumented platform behavior, not a
  // guarantee this code should rely on. Assert the resolved origin instead.
  if (backendUrl.origin !== BACKEND_ORIGIN) {
    return new Response(null, { status: StatusCodes.BAD_REQUEST });
  }

  // OWASP audit G-1: strip any client-supplied X-Forwarded-For/X-Client-IP
  // (forgeable) and replace with the edge-authenticated pair the backend's
  // client_key() trusts — cf-connecting-ip is set by the Cloudflare edge
  // itself, before this Function runs, so it can't be spoofed by the caller.
  const headers = new Headers(request.headers);
  headers.delete('x-forwarded-for');
  headers.delete('forwarded');
  headers.delete('x-client-ip');
  headers.delete('x-edge-auth');
  // OWASP audit L-8: the two shared-secret endpoints are exact-path siblings, but
  // never let their tokens ride a request that does reach this catch-all.
  headers.delete(SEO_AUDIT_TOKEN_HEADER);
  headers.delete(PRERENDER_CADENCE_TOKEN_HEADER);
  const clientIp = request.headers.get('cf-connecting-ip');
  if (clientIp && env.EDGE_SHARED_SECRET) {
    headers.set('x-client-ip', clientIp);
    headers.set('x-edge-auth', env.EDGE_SHARED_SECRET);
  }

  const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
  const init: RequestInit & { duplex?: 'half' } = {
    method: request.method,
    headers,
    redirect: 'manual',
  };
  if (hasBody) {
    init.body = request.body;
    // Required by fetch implementations (Workers runtime and undici alike)
    // whenever a Request carries a streamed (ReadableStream) body.
    init.duplex = 'half';
  }

  const backendResponse = await fetch(new Request(backendUrl, init));
  const responseHeaders = new Headers(backendResponse.headers);
  for (const header of STRIPPED_RESPONSE_HEADERS) responseHeaders.delete(header);

  return new Response(backendResponse.body, {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
    headers: responseHeaders,
  });
};
