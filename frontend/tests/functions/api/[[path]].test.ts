// Lives outside functions/ on purpose: Cloudflare Pages bundles every file
// under that tree into the deployed Worker (underscore-prefixed filenames
// don't exempt them — only whole directories do), and this test's vitest
// import drags in `node:sqlite` via undici, which the Workers bundler can't
// resolve.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { onRequest } from '../../../functions/api/[[path]]';
import { BACKEND_ORIGIN } from '../../../src/constants';

function makeContext(path: string, init: RequestInit = {}, env: Record<string, string> = {}) {
  return {
    request: new Request(`https://eventradar.ee${path}`, init),
    env,
  };
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

    await onRequest(makeContext('/api/events/123'));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const forwarded = fetchMock.mock.calls[0][0] as Request;
    expect(forwarded.url).toBe(`${BACKEND_ORIGIN}/events/123`);
  });

  it('preserves the query string', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('ok', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await onRequest(makeContext('/api/explore?category=music'));

    const forwarded = fetchMock.mock.calls[0][0] as Request;
    expect(forwarded.url).toBe(`${BACKEND_ORIGIN}/explore?category=music`);
  });

  it('forwards the method, headers and body for a mutating request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 201 }));
    vi.stubGlobal('fetch', fetchMock);

    await onRequest(
      makeContext('/api/feedback', {
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

    await onRequest(makeContext('/api/feed'));

    const forwarded = fetchMock.mock.calls[0][0] as Request;
    expect(forwarded.body).toBeNull();
  });

  it('returns the backend response body, status and content-type unchanged', async () => {
    const backendResponse = new Response('{"ok":true}', {
      status: 201,
      headers: { 'content-type': 'application/json' },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(backendResponse));

    const response = await onRequest(makeContext('/api/feed'));

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

    const response = await onRequest(makeContext('/api/feed'));

    expect(response.headers.get('content-encoding')).toBeNull();
    expect(response.headers.get('content-length')).toBeNull();
    expect(response.headers.get('transfer-encoding')).toBeNull();
    expect(response.headers.get('connection')).toBeNull();
    expect(response.headers.get('content-type')).toBe('text/plain');
  });

  // OWASP audit G-2: `new URL(relative, base)` discards `base`'s authority
  // for a protocol-relative path, which a `/api//host/...` request produces
  // once the /api prefix is stripped — resolving to an attacker-controlled
  // host instead of the backend, with the visitor's session cookie forwarded.
  it('rejects a path that resolves to a host other than BACKEND_ORIGIN (protocol-relative //)', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const response = await onRequest(makeContext('/api//evil.example.com/steal'));

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects a path with three leading slashes', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const response = await onRequest(makeContext('/api///evil.example.com/x'));

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects a backslash-based host-override attempt', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const response = await onRequest(makeContext('/api/\\/evil.example.com/x'));

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // OWASP audit G-1: real client IP is forwarded edge-authenticated so
  // app.rate_limit.client_key() can trust it across the two-hop topology.
  describe('client-IP handoff', () => {
    it('forwards cf-connecting-ip as X-Client-IP with X-Edge-Auth when EDGE_SHARED_SECRET is configured', async () => {
      const fetchMock = vi.fn().mockResolvedValue(new Response('ok', { status: 200 }));
      vi.stubGlobal('fetch', fetchMock);

      await onRequest(
        makeContext(
          '/api/events/1',
          { headers: { 'cf-connecting-ip': '203.0.113.7' } },
          { EDGE_SHARED_SECRET: 'topsecret' },
        ),
      );

      const forwarded = fetchMock.mock.calls[0][0] as Request;
      expect(forwarded.headers.get('x-client-ip')).toBe('203.0.113.7');
      expect(forwarded.headers.get('x-edge-auth')).toBe('topsecret');
    });

    it('strips any client-supplied X-Forwarded-For/X-Client-IP/X-Edge-Auth (forgeable)', async () => {
      const fetchMock = vi.fn().mockResolvedValue(new Response('ok', { status: 200 }));
      vi.stubGlobal('fetch', fetchMock);

      await onRequest(
        makeContext(
          '/api/events/1',
          {
            headers: {
              'x-forwarded-for': '1.2.3.4',
              'x-client-ip': '9.9.9.9',
              'x-edge-auth': 'forged',
            },
          },
          { EDGE_SHARED_SECRET: 'topsecret' },
        ),
      );

      const forwarded = fetchMock.mock.calls[0][0] as Request;
      expect(forwarded.headers.get('x-forwarded-for')).toBeNull();
      expect(forwarded.headers.get('x-client-ip')).toBeNull();
      expect(forwarded.headers.get('x-edge-auth')).toBeNull();
    });

    it('does not set X-Client-IP/X-Edge-Auth when EDGE_SHARED_SECRET is not configured', async () => {
      const fetchMock = vi.fn().mockResolvedValue(new Response('ok', { status: 200 }));
      vi.stubGlobal('fetch', fetchMock);

      await onRequest(makeContext('/api/events/1', { headers: { 'cf-connecting-ip': '203.0.113.7' } }));

      const forwarded = fetchMock.mock.calls[0][0] as Request;
      expect(forwarded.headers.get('x-client-ip')).toBeNull();
      expect(forwarded.headers.get('x-edge-auth')).toBeNull();
    });
  });
});
