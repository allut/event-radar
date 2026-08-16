/**
 * Minimal stand-in for `@vercel/node`'s request/response types, shared by
 * every function under `api/`. That package is the platform's own build
 * toolchain (21 MB, and the sole source of every `npm audit` finding in this
 * tree) and Vercel supplies it at build time — listing it locally bought
 * nothing but these two type names, so it was dropped. `@types/node` is
 * already a devDependency, so this shim costs no new package. Structurally
 * identical to the real types for the members declared here; only the
 * members an actual handler in this tree touches are modelled.
 */
import type { IncomingMessage, ServerResponse } from 'node:http';

export type VercelRequest = IncomingMessage & {
  query: Record<string, string | string[]>;
  body: unknown;
};
export type VercelResponse = ServerResponse & {
  status(code: number): VercelResponse;
  json(body: unknown): VercelResponse;
};
