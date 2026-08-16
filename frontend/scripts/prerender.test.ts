import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { maybeFireDeployHook } from './prerender';
import type { RoundMarker } from '../src/lib/prerenderChain';

/** Mocked-integration tests (issue #84) for the Deploy Hook chaining trigger
 * — exercises maybeFireDeployHook against a mocked global fetch and an
 * injected PRERENDER_CHAIN_DEPLOY_HOOK_URL, per the enumerated failure-mode
 * checklist in issue #79/#84's acceptance criteria. No real network, no
 * Playwright, no real Vercel deploy. */

function makeMarker(overrides: Partial<RoundMarker> = {}): RoundMarker {
  return {
    burstId: '2026-08-15T10:00:00.000Z',
    round: 3,
    status: 'continuing',
    newlyRendered: 220,
    copiedForward: 4025,
    queueRemaining: 1800,
    committedAt: '2026-08-15T10:20:00.000Z',
    ...overrides,
  };
}

const DEPLOY_HOOK_URL = 'https://api.vercel.com/v1/integrations/deploy/prj_test/abc123';

describe('maybeFireDeployHook', () => {
  const originalEnv = process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL;
  let fetchMock: ReturnType<typeof vi.fn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'log').mockImplementation(() => {});
  });

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL;
    } else {
      process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL = originalEnv;
    }
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('fires the Deploy Hook POST exactly once for a continuing-eligible round', async () => {
    process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL = DEPLOY_HOOK_URL;
    fetchMock.mockResolvedValue(new Response(null, { status: 200 }));

    await maybeFireDeployHook(makeMarker({ status: 'continuing', queueRemaining: 1800 }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(DEPLOY_HOOK_URL, { method: 'POST' });
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('does not fire the hook for round 11 (over the chain-depth cap) with a non-empty queue (status already done)', async () => {
    process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL = DEPLOY_HOOK_URL;

    // buildRoundMarker already forces status: done once the chain-depth cap
    // is exceeded (round > CHAIN_MAX_ROUNDS === 10 — round 10 itself is
    // still "at cap", allowed) — this asserts maybeFireDeployHook trusts
    // that field rather than re-deriving the cap check itself.
    await maybeFireDeployHook(
      makeMarker({ round: 11, status: 'done', newlyRendered: 300, queueRemaining: 900 }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('does not warn on zero-progress when the chain-depth cap is also exceeded (routine, not a stuck-catalog alert)', async () => {
    process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL = DEPLOY_HOOK_URL;

    await maybeFireDeployHook(
      makeMarker({ round: 11, status: 'done', newlyRendered: 0, copiedForward: 4000, queueRemaining: 900 }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('does not fire the hook and logs a WARNING with round/burst context on zero-progress abort', async () => {
    process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL = DEPLOY_HOOK_URL;

    await maybeFireDeployHook(
      makeMarker({
        burstId: '2026-08-15T09:00:00.000Z',
        round: 4,
        status: 'done',
        newlyRendered: 0,
        copiedForward: 5000,
        queueRemaining: 700,
      }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalledTimes(1);
    const [message] = warnSpy.mock.calls[0];
    expect(message).toContain('round 4');
    expect(message).toContain('2026-08-15T09:00:00.000Z');
    expect(message).toContain('zero-progress');
    // No separate admin-facing alert — WARNING log only.
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it('does not fire the hook and does not warn on a natural empty-queue completion', async () => {
    process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL = DEPLOY_HOOK_URL;

    await maybeFireDeployHook(
      makeMarker({ status: 'done', newlyRendered: 0, copiedForward: 4245, queueRemaining: 0 }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('does not throw and skips the POST when PRERENDER_CHAIN_DEPLOY_HOOK_URL is unset', async () => {
    delete process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL;

    await expect(maybeFireDeployHook(makeMarker({ status: 'continuing' }))).resolves.toBeUndefined();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('swallows a failed Deploy Hook POST (non-2xx) rather than throwing', async () => {
    process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL = DEPLOY_HOOK_URL;
    fetchMock.mockResolvedValue(new Response(null, { status: 500 }));

    await expect(maybeFireDeployHook(makeMarker({ status: 'continuing' }))).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledTimes(1);
  });

  it('swallows a network-level fetch failure rather than throwing', async () => {
    process.env.PRERENDER_CHAIN_DEPLOY_HOOK_URL = DEPLOY_HOOK_URL;
    fetchMock.mockRejectedValue(new Error('network down'));

    await expect(maybeFireDeployHook(makeMarker({ status: 'continuing' }))).resolves.toBeUndefined();

    expect(errorSpy).toHaveBeenCalledTimes(1);
  });
});
