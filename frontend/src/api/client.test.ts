import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { ApiError, api, organizerApi } from './client';

vi.mock('../lib/auth', () => ({
  clearSignedInHint: vi.fn(),
  isLoggingOut: vi.fn(() => false),
  getLocale: vi.fn(() => 'en'),
}));

vi.mock('../lib/organizerAuth', () => ({
  clearOrganizerSignedInHint: vi.fn(),
  isOrganizerLoggingOut: vi.fn(() => false),
}));

import { clearSignedInHint, isLoggingOut } from '../lib/auth';
import { clearOrganizerSignedInHint, isOrganizerLoggingOut } from '../lib/organizerAuth';

const mockClearSignedInHint = vi.mocked(clearSignedInHint);
const mockIsLoggingOut = vi.mocked(isLoggingOut);
const mockClearOrganizerSignedInHint = vi.mocked(clearOrganizerSignedInHint);
const mockIsOrganizerLoggingOut = vi.mocked(isOrganizerLoggingOut);

function mockFetch(status: number, body: unknown = {}, ok = true) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(''),
  }));
}

const originalLocation = window.location;

beforeEach(() => {
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { replace: vi.fn() },
  });
});

afterEach(() => {
  Object.defineProperty(window, 'location', {
    writable: true,
    value: originalLocation,
  });
});

describe('api.get', () => {
  it('builds correct URL with /api prefix', async () => {
    mockFetch(StatusCodes.OK, { ok: true });
    await api.get('/events');
    expect(vi.mocked(fetch)).toHaveBeenCalledWith('/api/events', expect.any(Object));
  });

  it('does not set Content-Type on GET', async () => {
    mockFetch(StatusCodes.OK, {});
    await api.get('/events');
    const call = vi.mocked(fetch).mock.calls[0];
    const headers = (call[1] as RequestInit).headers as Record<string, string>;
    expect(headers['Content-Type']).toBeUndefined();
  });

  it('sends credentials: include so the browser attaches the session cookie', async () => {
    mockFetch(StatusCodes.OK, {});
    await api.get('/events');
    const call = vi.mocked(fetch).mock.calls[0];
    const init = call[1] as RequestInit;
    expect(init.credentials).toBe('include');
  });

  it('returns parsed JSON on success', async () => {
    mockFetch(StatusCodes.OK, { id: 1, title: 'Test' });
    const result = await api.get<{ id: number; title: string }>('/events/1');
    expect(result).toEqual({ id: 1, title: 'Test' });
  });

  it('throws ApiError with detail on non-ok response', async () => {
    mockFetch(StatusCodes.NOT_FOUND, { detail: 'Not found' }, false);
    await expect(api.get('/missing')).rejects.toThrow(ApiError);
    await expect(api.get('/missing')).rejects.toMatchObject({ message: 'Not found' });
  });

  it('throws a distinguishable ApiError when fetch itself rejects — offline, or a request blocked before it leaves the browser (#453)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(api.get('/organizer/claims/1/events/7')).rejects.toMatchObject({
      code: 'network_error',
      message: "Couldn't reach Event Radar — a browser extension may be blocking this request.",
    });
  });

  it('throws ApiError with HTTP status fallback when no detail', async () => {
    mockFetch(StatusCodes.INTERNAL_SERVER_ERROR, {}, false);
    await expect(api.get('/fail')).rejects.toMatchObject({ message: `HTTP ${StatusCodes.INTERNAL_SERVER_ERROR}` });
  });

  it('throws ApiError with message + code when detail is a structured object', async () => {
    mockFetch(StatusCodes.CONFLICT, { detail: { message: 'Dormant', code: 'claim_dormant' } }, false);
    await expect(api.get('/locked')).rejects.toMatchObject({ message: 'Dormant', code: 'claim_dormant' });
  });

  it('throws a localized generic ApiError (never "HTTP 422") when detail is a FastAPI validation list, keeping status and field names (#452)', async () => {
    mockFetch(StatusCodes.UNPROCESSABLE_ENTITY, {
      detail: [{ type: 'value_error', loc: ['body', 'title'], msg: 'Value error, title must not be blank' }],
    }, false);
    await expect(api.get('/validate')).rejects.toMatchObject({
      status: StatusCodes.UNPROCESSABLE_ENTITY,
      code: 'validation_error',
      fields: ['title'],
    });
    await expect(api.get('/validate')).rejects.not.toMatchObject({ message: `HTTP ${StatusCodes.UNPROCESSABLE_ENTITY}` });
  });

  it('on 401: calls clearSignedInHint, redirects to /login, throws ApiError', async () => {
    mockFetch(StatusCodes.UNAUTHORIZED, {}, false);
    await expect(api.get('/protected')).rejects.toThrow(ApiError);
    expect(mockClearSignedInHint).toHaveBeenCalled();
    expect(window.location.replace).toHaveBeenCalledWith('/login');
  });

  it('on 401 during logout: calls clearSignedInHint, skips the /login redirect, still throws ApiError', async () => {
    mockIsLoggingOut.mockReturnValueOnce(true);
    mockFetch(StatusCodes.UNAUTHORIZED, {}, false);
    await expect(api.get('/protected')).rejects.toThrow(ApiError);
    expect(mockClearSignedInHint).toHaveBeenCalled();
    expect(window.location.replace).not.toHaveBeenCalled();
  });

  it('resolves undefined on 204', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: StatusCodes.NO_CONTENT, json: vi.fn(), text: vi.fn() }));
    const result = await api.get('/empty');
    expect(result).toBeUndefined();
  });
});

describe('api.post', () => {
  it('sends POST method with JSON body', async () => {
    mockFetch(StatusCodes.OK, {});
    await api.post('/auth/request-link', { email: 'a@b.com' });
    const call = vi.mocked(fetch).mock.calls[0];
    const init = call[1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(init.body).toBe(JSON.stringify({ email: 'a@b.com' }));
    const headers = init.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('sends POST without body when no body arg', async () => {
    mockFetch(StatusCodes.OK, {});
    await api.post('/logout');
    const call = vi.mocked(fetch).mock.calls[0];
    const init = call[1] as RequestInit;
    expect(init.body).toBeUndefined();
  });
});

describe('api.patch', () => {
  it('sends PATCH method', async () => {
    mockFetch(StatusCodes.OK, {});
    await api.patch('/users/me', { locale: 'et' });
    const call = vi.mocked(fetch).mock.calls[0];
    expect((call[1] as RequestInit).method).toBe('PATCH');
  });
});

describe('FormData bodies', () => {
  it('sends FormData body as-is without JSON.stringify or a Content-Type header', async () => {
    mockFetch(StatusCodes.OK, {});
    const form = new FormData();
    form.append('file', new Blob(['x']), 'test.png');
    await api.post('/organizer/events/image', form, { organizer: true });
    const call = vi.mocked(fetch).mock.calls[0];
    const init = call[1] as RequestInit;
    expect(init.body).toBe(form);
    const headers = init.headers as Record<string, string>;
    expect(headers['Content-Type']).toBeUndefined();
  });
});

describe('organizer requests', () => {
  it('sends credentials: include for organizer requests too', async () => {
    mockFetch(StatusCodes.OK, {});
    await organizerApi.get('/organizer/events');
    const call = vi.mocked(fetch).mock.calls[0];
    const init = call[1] as RequestInit;
    expect(init.credentials).toBe('include');
  });

  it('on 401: clears the organizer hint and redirects to /organizer/login', async () => {
    mockFetch(StatusCodes.UNAUTHORIZED, {}, false);
    await expect(organizerApi.get('/organizer/events')).rejects.toThrow(ApiError);
    expect(mockClearOrganizerSignedInHint).toHaveBeenCalled();
    expect(mockClearSignedInHint).not.toHaveBeenCalled();
    expect(window.location.replace).toHaveBeenCalledWith('/organizer/login');
  });

  it('on 401 during organizer logout: skips the redirect', async () => {
    mockIsOrganizerLoggingOut.mockReturnValueOnce(true);
    mockFetch(StatusCodes.UNAUTHORIZED, {}, false);
    await expect(organizerApi.get('/organizer/events')).rejects.toThrow(ApiError);
    expect(mockClearOrganizerSignedInHint).toHaveBeenCalled();
    expect(window.location.replace).not.toHaveBeenCalled();
  });
});
