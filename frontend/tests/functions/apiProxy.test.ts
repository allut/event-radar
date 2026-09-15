// Lives outside functions/ on purpose: Cloudflare Pages bundles every file
// under that tree into the deployed Worker (underscore-prefixed filenames
// don't exempt them — only whole directories do), and this test's vitest
// import drags in `node:sqlite` via undici, which the Workers bundler can't
// resolve.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { proxyToBackend } from '../../functions/_shared/apiProxy';
import { BACKEND_ORIGIN } from '../../src/constants';

function makeRequest(path: string, init: RequestInit = {}) {
  return new Request(`https://eventradar.ee${path}`, init);
}

describe('/api/* backend proxy', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('strips the /api prefix and forwards to the backend origin', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('ok', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await proxyToBackend(makeRequest('/api/events/123'));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const forwarded = fetchMock.mock.calls[0][0] as Request;
    expect(forwarded.url).toBe(`${BACKEND_ORIGIN}/events/123`);
  });

  it('preserves the query string', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('ok', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await proxyToBackend(makeRequest('/api/explore?category=music'));

    const forwarded = fetchMock.mock.calls[0][0] as Request;
    expect(forwarded.url).toBe(`${BACKEND_ORIGIN}/explore?category=music`);
  });

  it('forwards the method, headers and body for a mutating request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 201 }));
    vi.stubGlobal('fetch', fetchMock);

    await proxyToBackend(
      makeRequest('/api/feedback', {
        method: 'POST',
        headers: { 'content-type': 'application/json', cookie: 'session=abc' },
        body: JSON.stringify({ eventId: 1 }),
      }),
    );

    const forwarded = fetchMock.mock.calls[0][0] as Request;
    expect(forwarded.method).toBe('POST');
    expect(forwarded.headers.get('content-type')).toBe('application/json');
    expect(forwarded.headers.get('cookie')).toBe('session=abc');
    expect(await forwarded.text()).toBe(JSON.stringify({ eventId: 1 }));
  });

  it('sends no body for a GET request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('ok', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await proxyToBackend(makeRequest('/api/feed'));

    const forwarded = fetchMock.mock.calls[0][0] as Request;
    expect(forwarded.body).toBeNull();
  });

  it('returns the backend response body, status and content-type unchanged', async () => {
    const backendResponse = new Response('{"ok":true}', {
      status: 201,
      headers: { 'content-type': 'application/json' },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(backendResponse));

    const response = await proxyToBackend(makeRequest('/api/feed'));

    expect(response.status).toBe(201);
    expect(response.headers.get('content-type')).toBe('application/json');
    expect(await response.text()).toBe('{"ok":true}');
  });

  it('strips content-encoding/content-length/transfer-encoding/connection from the backend response', async () => {
    const backendResponse = new Response('decoded body', {
      status: 200,
      headers: {
        'content-encoding': 'gzip',
        'content-length': '999',
        'transfer-encoding': 'chunked',
        connection: 'keep-alive',
        'content-type': 'text/plain',
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(backendResponse));

    const response = await proxyToBackend(makeRequest('/api/feed'));

    expect(response.headers.get('content-encoding')).toBeNull();
    expect(response.headers.get('content-length')).toBeNull();
    expect(response.headers.get('transfer-encoding')).toBeNull();
    expect(response.headers.get('connection')).toBeNull();
    expect(response.headers.get('content-type')).toBe('text/plain');
  });
});
