import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import handler from './prerender-cadence';
import { PRERENDER_CADENCE_TOKEN_HEADER } from '../src/constants';
import { buildRoundMarker, serializeRoundMarker } from '../src/lib/prerenderChain';
import type { VercelRequest, VercelResponse } from './vercel';

function makeReq(headers: Record<string, string>, method = 'POST'): VercelRequest {
  return { headers, query: {}, body: undefined, method } as unknown as VercelRequest;
}

function makeRes(): VercelResponse & { statusCode: number; body: unknown } {
  const res = {
    statusCode: 0,
    body: undefined as unknown,
    status(code: number) {
      res.statusCode = code;
      return res;
    },
    json(body: unknown) {
      res.body = body;
      return res;
    },
    end() {
      return res;
    },
  };
  return res as unknown as VercelResponse & { statusCode: number; body: unknown };
}

function mockGithubCommitFetch(commitMessage: string) {
  return vi.fn().mockImplementation((url: string) => {
    if (String(url).includes('/commits/')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ commit: { message: commitMessage } }),
      });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
}

describe('prerender-cadence handler', () => {
  beforeEach(() => {
    process.env.PRERENDER_CADENCE_TOKEN = 'shared-secret';
    process.env.PRERENDER_CADENCE_DEPLOY_HOOK_URL = 'https://hooks.example/deploy';
    process.env.GH_PRERENDER_CHAIN_TOKEN = 'gh-token';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.PRERENDER_CADENCE_TOKEN;
    delete process.env.PRERENDER_CADENCE_DEPLOY_HOOK_URL;
    delete process.env.GH_PRERENDER_CHAIN_TOKEN;
  });

  it('sends an authenticated request to read the tip commit', async () => {
    const now = new Date('2026-08-15T12:00:00.000Z');
    const marker = buildRoundMarker(
      now.toISOString(),
      3,
      { newlyRendered: 10, copiedForward: 5, queueRemaining: 100 },
      now,
    );
    const fetchMock = mockGithubCommitFetch(serializeRoundMarker(marker));
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-15T12:10:00.000Z')); // marker is 10min old — fresh

    const res = makeRes();
    await handler(makeReq({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'shared-secret' }), res);

    const [commitUrl, commitInit] = fetchMock.mock.calls[0];
    expect(String(commitUrl)).toContain('/commits/release');
    expect(commitInit.headers.Authorization).toBe('Bearer gh-token');
    expect(commitInit.headers['User-Agent']).toBeTruthy();

    vi.useRealTimers();
  });

  it('skips forwarding to the deploy hook when a fresh continuing marker is at the tip commit', async () => {
    const now = new Date('2026-08-15T12:00:00.000Z');
    const marker = buildRoundMarker(
      now.toISOString(),
      3,
      { newlyRendered: 10, copiedForward: 5, queueRemaining: 100 },
      now,
    );
    const fetchMock = mockGithubCommitFetch(serializeRoundMarker(marker));
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-15T12:10:00.000Z')); // 10min old — fresh, within 30min window

    const res = makeRes();
    await handler(makeReq({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'shared-secret' }), res);

    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ skipped: true, reason: 'chain round in flight' });
    expect(fetchMock).toHaveBeenCalledTimes(1); // only the commit read — deploy hook never fired

    vi.useRealTimers();
  });

  it('forwards to the deploy hook when the tip commit has no in-flight marker', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/commits/')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ commit: { message: 'chore: unrelated commit' } }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
    });
    vi.stubGlobal('fetch', fetchMock);

    const res = makeRes();
    await handler(makeReq({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'shared-secret' }), res);

    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ skipped: false, deployHookStatus: 200 });
    expect(fetchMock).toHaveBeenCalledTimes(2); // commit read + deploy hook POST
    expect(String(fetchMock.mock.calls[1][0])).toBe('https://hooks.example/deploy');
  });

  it('fails open (fires the hook) when GH_PRERENDER_CHAIN_TOKEN is not configured', async () => {
    delete process.env.GH_PRERENDER_CHAIN_TOKEN;
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({}) });
    vi.stubGlobal('fetch', fetchMock);

    const res = makeRes();
    await handler(makeReq({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'shared-secret' }), res);

    expect(res.body).toEqual({ skipped: false, deployHookStatus: 200 });
    expect(fetchMock).toHaveBeenCalledTimes(1); // only the deploy hook — no commit-read call attempted
  });

  it('rejects requests with an invalid token', async () => {
    const res = makeRes();
    await handler(makeReq({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'wrong' }), res);
    expect(res.statusCode).toBe(403);
  });

  it('rejects non-POST requests before checking the token', async () => {
    const res = makeRes();
    await handler(makeReq({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'shared-secret' }, 'GET'), res);
    expect(res.statusCode).toBe(405);
  });

  it('returns an opaque 403 (not 500) when the shared secret itself is unconfigured', async () => {
    delete process.env.PRERENDER_CADENCE_TOKEN;
    const res = makeRes();
    await handler(makeReq({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'anything' }), res);
    expect(res.statusCode).toBe(403);
  });
});
