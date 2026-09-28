import { StatusCodes } from 'http-status-codes';
import { API, API_BASE, NETWORK_ERROR_CODE, ROUTES, VALIDATION_ERROR_CODE } from '../constants';
import { clearSignedInHint, isLoggingOut, getLocale } from '../lib/auth';
import { clearOrganizerSignedInHint, isOrganizerLoggingOut } from '../lib/organizerAuth';
import { clearAdminSignedInHint, isAdminLoggingOut } from '../lib/adminAuth';
import { t } from '../i18n';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    /** Machine-readable companion to `message`, when the backend sends one
     * (`detail: { message, code }` instead of a plain string) — lets a
     * caller branch on the failure reason without matching English text
     * (#444). Also set locally to VALIDATION_ERROR_CODE for a FastAPI 422
     * list `detail` (#452), which the backend never labels with a code
     * itself. Undefined for every endpoint that still sends a plain string. */
    public readonly code?: string,
    /** Field paths (`loc`, minus the leading "body") from a 422 list
     * `detail`, empty for every other error shape — lets a form highlight
     * the fields FastAPI rejected without parsing English `msg` text. */
    public readonly fields?: string[],
  ) {
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
  /** Same idea as `organizer`, but for the admin console session track (see
   * lib/adminAuth.ts). */
  admin?: boolean;
}

// POST /admin/auth/login is the one endpoint where a 401 means "wrong
// credentials", not "your session expired" — every other call through this
// client only ever gets a 401 from an expired/missing/revoked session. That
// endpoint must skip the redirect-and-clear-hint interceptor below and let
// its 401 fall through to the generic error path so the login form can show
// the real ApiError.message instead of a misleading "Session expired".
const NO_SESSION_REDIRECT_ON_401 = new Set<string>([API.adminAuthLogin]);

// Shared by request() and adminStream() — a 401 always means "your session
// expired" (except the login-form carve-out above), regardless of whether
// the response is a single JSON body or an NDJSON stream. Clears the right
// track's signed-in hint and redirects, then throws so the caller can stop.
function handleSessionExpiry401(opts: CallOptions): never {
  if (opts.admin) {
    clearAdminSignedInHint();
    if (!isAdminLoggingOut()) window.location.replace(ROUTES.adminLogin);
  } else if (opts.organizer) {
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

async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const { organizer, admin, ...fetchInit } = init;
  const hasBody = fetchInit.body !== undefined;
  // FormData (the image-upload path) must not be JSON.stringify'd or given
  // an explicit Content-Type — the browser sets the multipart boundary itself.
  const isFormData = typeof FormData !== 'undefined' && fetchInit.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(hasBody && !isFormData ? { 'Content-Type': 'application/json' } : {}),
    ...(fetchInit.headers as Record<string, string> | undefined ?? {}),
  };

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...fetchInit, headers, credentials: 'include' });
  } catch {
    // fetch() itself rejects (a TypeError, per spec) when the request never
    // leaves the browser at all — offline, DNS failure, or (the case #453
    // was filed for) an ad/tracker blocker silently killing a request whose
    // URL shape looks like an analytics beacon. Distinguishable from every
    // other failure via NETWORK_ERROR_CODE so a form can show a message that
    // actually points at the real cause instead of the generic fallback.
    throw new ApiError(0, t('network_error', getLocale()), NETWORK_ERROR_CODE);
  }

  if (res.status === StatusCodes.UNAUTHORIZED && !NO_SESSION_REDIRECT_ON_401.has(path)) {
    handleSessionExpiry401({ organizer, admin });
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as {
      detail?: string | { message?: string; code?: string } | { msg?: string; loc?: (string | number)[] }[];
    };
    const { detail } = body;
    // FastAPI's own validation-failure shape (e.g. a pydantic field_validator
    // raising ValueError) — a list of error objects, never a `.message`, and
    // its `msg` text is English-only and developer-worded ("Value error, …").
    // Never surface that; show a localized generic instead (#452).
    if (Array.isArray(detail)) {
      const fields = [...new Set(
        detail.map((item) => item.loc?.filter((p) => p !== 'body').join('.') ?? '').filter(Boolean),
      )];
      throw new ApiError(res.status, t('validation_error_generic', getLocale()), VALIDATION_ERROR_CODE, fields);
    }
    if (typeof detail === 'object' && detail !== null) {
      throw new ApiError(res.status, detail.message ?? `HTTP ${res.status}`, detail.code);
    }
    throw new ApiError(res.status, detail ?? `HTTP ${res.status}`);
  }

  if (res.status === StatusCodes.NO_CONTENT) return undefined as T;
  return res.json() as Promise<T>;
}

interface CallOptions {
  organizer?: boolean;
  admin?: boolean;
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

// Thin admin-scoped wrapper, mirroring organizerApi — every call carries
// { admin: true } so call sites (admin console routes/hooks) never have to
// remember the flag.
export const adminApi = {
  get: <T>(path: string) => api.get<T>(path, { admin: true }),
  post: <T>(path: string, body?: unknown) => api.post<T>(path, body, { admin: true }),
};

export interface NdjsonLine {
  stage: string;
  status: 'ok' | 'error';
  result: unknown;
  error: string | null;
}

// Thrown when the connection drops mid-stream (network error while reading
// the body) — distinct from a clean stream that simply reported a
// status:"error" line, and from a request that never started (ApiError).
// The /admin/pipeline job triggers (issue #159) stream NDJSON instead of
// returning a single JSON body, so they go through this reader rather than
// `request()`.
export class StreamDisconnectedError extends Error {}

export async function adminStream(
  path: string,
  onLine: (line: NdjsonLine) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', credentials: 'include', signal });

  if (res.status === StatusCodes.UNAUTHORIZED) {
    handleSessionExpiry401({ admin: true });
  }
  if (!res.ok || !res.body) {
    throw new ApiError(res.status, `HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newlineAt = buffer.indexOf('\n');
      while (newlineAt >= 0) {
        const raw = buffer.slice(0, newlineAt);
        buffer = buffer.slice(newlineAt + 1);
        if (raw.trim()) onLine(JSON.parse(raw) as NdjsonLine);
        newlineAt = buffer.indexOf('\n');
      }
    }
  } catch (err) {
    if (signal?.aborted) return;
    throw new StreamDisconnectedError(err instanceof Error ? err.message : 'Stream disconnected');
  }
}
