/**
 * Minimal stand-in for `@cloudflare/workers-types`' `EventContext`/
 * `PagesFunction` types, shared by every function under `functions/`.
 * Mirrors the old `api/vercel.ts` shim this replaces: Cloudflare supplies
 * the real types at build/runtime, and pulling in the package locally would
 * buy nothing but these two type names. Only the members a handler in this
 * tree actually touches are modelled.
 */
export interface EventContext<Env> {
  request: Request;
  env: Env;
}

export type PagesFunction<Env = unknown> = (
  context: EventContext<Env>,
) => Response | Promise<Response>;

/** `Response.json()` isn't available in every runtime this code might run
 * under (e.g. Node under vitest before Node 18's fetch API stabilized on
 * it), so build the JSON response explicitly rather than relying on it. */
export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
