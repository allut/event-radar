import { StatusCodes } from 'http-status-codes';
import { clearToken, getToken, isLoggingOut } from '../lib/auth';
import { clearOrganizerToken, getOrganizerToken, isOrganizerLoggingOut } from '../lib/organizerAuth';

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

interface RequestOptions extends RequestInit {
  /** Attach the organizer session token instead of the consumer one, and
   * redirect to /organizer/login (not /login) on a 401 — see
   * lib/organizerAuth.ts for why the two tracks are kept separate. */
  organizer?: boolean;
}

async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const { organizer, ...fetchInit } = init;
  const token = organizer ? getOrganizerToken() : getToken();
  const hasBody = fetchInit.body !== undefined;
  // FormData (the image-upload path) must not be JSON.stringify'd or given
  // an explicit Content-Type — the browser sets the multipart boundary itself.
  const isFormData = typeof FormData !== 'undefined' && fetchInit.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(hasBody && !isFormData ? { 'Content-Type': 'application/json' } : {}),
    ...(fetchInit.headers as Record<string, string> | undefined ?? {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`/api${path}`, { ...fetchInit, headers });

  if (res.status === StatusCodes.UNAUTHORIZED) {
    if (organizer) {
      clearOrganizerToken();
      if (!isOrganizerLoggingOut()) window.location.replace('/organizer/login');
    } else {
      clearToken();
      // A 401 during an explicit logout is an expected side effect of the
      // cache-clear race described in lib/auth.ts, not a real session expiry —
      // skip the hard redirect so it doesn't override the logout navigation.
      if (!isLoggingOut()) window.location.replace('/login');
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
