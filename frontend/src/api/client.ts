import { StatusCodes } from 'http-status-codes';
import { ROUTES } from '../constants';
import { clearSignedInHint, isLoggingOut } from '../lib/auth';
import { clearOrganizerSignedInHint, isOrganizerLoggingOut } from '../lib/organizerAuth';

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

interface RequestOptions extends RequestInit {
  /** Use the organizer session cookie's clear/redirect targets instead of the
   * consumer ones on a 401 — see lib/organizerAuth.ts for why the two tracks
   * are kept separate. The session credential itself travels as an httpOnly
   * cookie the browser attaches automatically; this flag no longer selects a
   * token. */
  organizer?: boolean;
}

async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const { organizer, ...fetchInit } = init;
  const hasBody = fetchInit.body !== undefined;
  // FormData (the image-upload path) must not be JSON.stringify'd or given
  // an explicit Content-Type — the browser sets the multipart boundary itself.
  const isFormData = typeof FormData !== 'undefined' && fetchInit.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(hasBody && !isFormData ? { 'Content-Type': 'application/json' } : {}),
    ...(fetchInit.headers as Record<string, string> | undefined ?? {}),
  };

  const res = await fetch(`/api${path}`, { ...fetchInit, headers, credentials: 'include' });

  if (res.status === StatusCodes.UNAUTHORIZED) {
    if (organizer) {
      clearOrganizerSignedInHint();
      if (!isOrganizerLoggingOut()) window.location.replace(ROUTES.organizerLogin);
    } else {
      clearSignedInHint();
      // A 401 during an explicit logout is an expected side effect of the
      // cache-clear race described in lib/auth.ts, not a real session expiry —
      // skip the hard redirect so it doesn't override the logout navigation.
      if (!isLoggingOut()) window.location.replace(ROUTES.login);
    }
    throw new ApiError(StatusCodes.UNAUTHORIZED, 'Session expired');
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new ApiError(res.status, body.detail ?? `HTTP ${res.status}`);
  }

  if (res.status === StatusCodes.NO_CONTENT) return undefined as T;
  return res.json() as Promise<T>;
}

interface CallOptions {
  organizer?: boolean;
}

function jsonOrFormBody(body: unknown): BodyInit | undefined {
  if (body === undefined) return undefined;
  if (typeof FormData !== 'undefined' && body instanceof FormData) return body;
  return JSON.stringify(body);
}

export const api = {
  get: <T>(path: string, opts?: CallOptions) => request<T>(path, opts),
  post: <T>(path: string, body?: unknown, opts?: CallOptions) =>
    request<T>(path, {
      method: 'POST',
      body: jsonOrFormBody(body),
      ...opts,
    }),
  patch: <T>(path: string, body?: unknown, opts?: CallOptions) =>
    request<T>(path, {
      method: 'PATCH',
      body: jsonOrFormBody(body),
      ...opts,
    }),
  delete: <T>(path: string, opts?: CallOptions) => request<T>(path, { method: 'DELETE', ...opts }),
};

// Thin organizer-scoped wrapper — every call carries { organizer: true } so
// call sites (organizer routes/hooks) never have to remember the flag.
export const organizerApi = {
  get: <T>(path: string) => api.get<T>(path, { organizer: true }),
  post: <T>(path: string, body?: unknown) => api.post<T>(path, body, { organizer: true }),
  patch: <T>(path: string, body?: unknown) => api.patch<T>(path, body, { organizer: true }),
  delete: <T>(path: string) => api.delete<T>(path, { organizer: true }),
};
