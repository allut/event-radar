// Leading underscore keeps Cloudflare Pages from treating this as a route
// (and bundling it into the deployed Worker) — its vitest imports drag in
// `node:sqlite` via undici, which the Workers bundler can't resolve.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { onRequestPost } from './prerender-cadence';
import { PRERENDER_CADENCE_TOKEN_HEADER } from '../../src/constants';
import { buildRoundMarker, serializeRoundMarker } from '../../src/lib/prerenderChain';

interface Env {
  PRERENDER_CADENCE_TOKEN?: string;
  PRERENDER_CADENCE_DEPLOY_HOOK_URL?: string;
  GH_PRERENDER_CHAIN_TOKEN?: string;
}

const BASE_ENV: Env = {
  PRERENDER_CADENCE_TOKEN: 'shared-secret',
  PRERENDER_CADENCE_DEPLOY_HOOK_URL: 'https://hooks.example/deploy',
  GH_PRERENDER_CHAIN_TOKEN: 'gh-token',
};

function makeContext(headers: Record<string, string>, method = 'POST', env: Env = BASE_ENV) {
  return {
    request: new Request('https://eventradar.ee/api/prerender-cadence', { method, headers }),
    env,
  };
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
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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

    await onRequestPost(makeContext({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'shared-secret' }));

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

    const res = await onRequestPost(makeContext({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'shared-secret' }));

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ skipped: true, reason: 'chain round in flight' });
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

    const res = await onRequestPost(makeContext({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'shared-secret' }));

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ skipped: false, deployHookStatus: 200 });
    expect(fetchMock).toHaveBeenCalledTimes(2); // commit read + deploy hook POST
    expect(String(fetchMock.mock.calls[1][0])).toBe('https://hooks.example/deploy');
  });

  it('fails open (fires the hook) when GH_PRERENDER_CHAIN_TOKEN is not configured', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({}) });
    vi.stubGlobal('fetch', fetchMock);

    const res = await onRequestPost(
      makeContext({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'shared-secret' }, 'POST', {
        ...BASE_ENV,
        GH_PRERENDER_CHAIN_TOKEN: undefined,
      }),
    );

    expect(await res.json()).toEqual({ skipped: false, deployHookStatus: 200 });
    expect(fetchMock).toHaveBeenCalledTimes(1); // only the deploy hook — no commit-read call attempted
  });

  it('rejects requests with an invalid token', async () => {
    const res = await onRequestPost(makeContext({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'wrong' }));
    expect(res.status).toBe(403);
  });

  it('rejects non-POST requests before checking the token', async () => {
    const res = await onRequestPost(makeContext({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'shared-secret' }, 'GET'));
    expect(res.status).toBe(405);
  });

  it('returns an opaque 403 (not 500) when the shared secret itself is unconfigured', async () => {
    const res = await onRequestPost(
      makeContext({ [PRERENDER_CADENCE_TOKEN_HEADER]: 'anything' }, 'POST', {
        ...BASE_ENV,
        PRERENDER_CADENCE_TOKEN: undefined,
      }),
    );
    expect(res.status).toBe(403);
  });
});
