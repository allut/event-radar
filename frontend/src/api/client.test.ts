import { describe, it, expect, vi, beforeEach } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { ApiError, api } from './client';

vi.mock('../lib/auth', () => ({
  getToken: vi.fn(() => null),
  clearToken: vi.fn(),
}));

import { getToken, clearToken } from '../lib/auth';

const mockGetToken = vi.mocked(getToken);
const mockClearToken = vi.mocked(clearToken);

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

  it('does not set Authorization when no token', async () => {
    mockGetToken.mockReturnValueOnce(null);
    mockFetch(StatusCodes.OK, {});
    await api.get('/events');
    const call = vi.mocked(fetch).mock.calls[0];
    const headers = (call[1] as RequestInit).headers as Record<string, string>;
    expect(headers['Authorization']).toBeUndefined();
  });

  it('sets Authorization when token present', async () => {
    mockGetToken.mockReturnValueOnce('mytoken');
    mockFetch(StatusCodes.OK, {});
    await api.get('/events');
    const call = vi.mocked(fetch).mock.calls[0];
    const headers = (call[1] as RequestInit).headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer mytoken');
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

  it('throws ApiError with HTTP status fallback when no detail', async () => {
    mockFetch(StatusCodes.INTERNAL_SERVER_ERROR, {}, false);
    await expect(api.get('/fail')).rejects.toMatchObject({ message: `HTTP ${StatusCodes.INTERNAL_SERVER_ERROR}` });
  });

  it('on 401: calls clearToken, redirects to /login, throws ApiError', async () => {
    mockFetch(StatusCodes.UNAUTHORIZED, {}, false);
    await expect(api.get('/protected')).rejects.toThrow(ApiError);
    expect(mockClearToken).toHaveBeenCalled();
    expect(window.location.replace).toHaveBeenCalledWith('/login');
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
