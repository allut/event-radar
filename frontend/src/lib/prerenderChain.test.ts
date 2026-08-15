import { describe, it, expect } from 'vitest';
import {
  serializeRoundMarker,
  parseRoundMarker,
  isChainDepthExceeded,
  isZeroProgress,
  isMarkerStale,
  resolveRoundContext,
  buildRoundMarker,
  type RoundMarker,
} from './prerenderChain';
import { CHAIN_MAX_ROUNDS, CHAIN_STALENESS_TIMEOUT_MINUTES } from '../constants';

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

describe('serializeRoundMarker / parseRoundMarker', () => {
  it('round-trips a realistic marker without loss', () => {
    const marker = makeMarker();
    expect(parseRoundMarker(serializeRoundMarker(marker))).toEqual(marker);
  });

  it('round-trips when the serialized marker is embedded inside a larger commit message', () => {
    const marker = makeMarker();
    const commitMessage = `prerender: round ${marker.round} continuation\n\n${serializeRoundMarker(marker)}\n`;
    expect(parseRoundMarker(commitMessage)).toEqual(marker);
  });

  it('fits within the 2048-byte VERCEL_GIT_COMMIT_MESSAGE cap for thousands-of-routes progress counts', () => {
    const marker = makeMarker({
      newlyRendered: 9999,
      copiedForward: 9999,
      queueRemaining: 9999,
      round: CHAIN_MAX_ROUNDS,
    });
    const bytes = Buffer.byteLength(serializeRoundMarker(marker), 'utf-8');
    expect(bytes).toBeLessThan(2048);
  });

  it('returns null for a missing marker', () => {
    expect(parseRoundMarker(null)).toBeNull();
    expect(parseRoundMarker(undefined)).toBeNull();
    expect(parseRoundMarker('')).toBeNull();
    expect(parseRoundMarker('a plain commit message with no marker')).toBeNull();
  });

  it('returns null for malformed JSON without throwing', () => {
    expect(() => parseRoundMarker('prerender-chain: {not valid json')).not.toThrow();
    expect(parseRoundMarker('prerender-chain: {not valid json')).toBeNull();
  });

  it('returns null for a structurally invalid payload (missing/wrong-typed fields) without throwing', () => {
    const cases = [
      'prerender-chain: {}',
      'prerender-chain: {"burst_id":"x","round":0,"status":"continuing","newly_rendered":1,"copied_forward":1,"queue_remaining":1,"committed_at":"2026-08-15T10:00:00.000Z"}',
      'prerender-chain: {"burst_id":"x","round":1,"status":"bogus","newly_rendered":1,"copied_forward":1,"queue_remaining":1,"committed_at":"2026-08-15T10:00:00.000Z"}',
      'prerender-chain: {"burst_id":"x","round":1,"status":"done","newly_rendered":-1,"copied_forward":1,"queue_remaining":1,"committed_at":"2026-08-15T10:00:00.000Z"}',
      'prerender-chain: {"burst_id":"x","round":1,"status":"done","newly_rendered":1,"copied_forward":1,"queue_remaining":1,"committed_at":"not-a-date"}',
      'prerender-chain: "just a string"',
      'prerender-chain: null',
    ];
    for (const commitMessage of cases) {
      expect(() => parseRoundMarker(commitMessage)).not.toThrow();
      expect(parseRoundMarker(commitMessage)).toBeNull();
    }
  });
});

describe('isChainDepthExceeded', () => {
  it(`is false at the cap (round ${CHAIN_MAX_ROUNDS})`, () => {
    expect(isChainDepthExceeded(CHAIN_MAX_ROUNDS)).toBe(false);
  });

  it(`is true just over the cap (round ${CHAIN_MAX_ROUNDS + 1})`, () => {
    expect(isChainDepthExceeded(CHAIN_MAX_ROUNDS + 1)).toBe(true);
  });

  it('is false for an early round', () => {
    expect(isChainDepthExceeded(1)).toBe(false);
  });
});

describe('isZeroProgress', () => {
  it('is true when newly-rendered is 0 regardless of copied-forward count', () => {
    expect(isZeroProgress({ newlyRendered: 0, copiedForward: 0 })).toBe(true);
    expect(isZeroProgress({ newlyRendered: 0, copiedForward: 5000 })).toBe(true);
  });

  it('is false whenever newly-rendered is greater than 0', () => {
    expect(isZeroProgress({ newlyRendered: 1, copiedForward: 0 })).toBe(false);
    expect(isZeroProgress({ newlyRendered: 220, copiedForward: 4025 })).toBe(false);
  });
});

describe('isMarkerStale', () => {
  const committedAt = '2026-08-15T10:00:00.000Z';

  it(`is false just under the ${CHAIN_STALENESS_TIMEOUT_MINUTES}-minute window`, () => {
    const marker = makeMarker({ committedAt });
    const now = new Date(Date.parse(committedAt) + (CHAIN_STALENESS_TIMEOUT_MINUTES * 60 * 1000 - 1000));
    expect(isMarkerStale(marker, now)).toBe(false);
  });

  it(`is true just over the ${CHAIN_STALENESS_TIMEOUT_MINUTES}-minute window`, () => {
    const marker = makeMarker({ committedAt });
    const now = new Date(Date.parse(committedAt) + (CHAIN_STALENESS_TIMEOUT_MINUTES * 60 * 1000 + 1000));
    expect(isMarkerStale(marker, now)).toBe(true);
  });

  it('is false at exactly the window boundary', () => {
    const marker = makeMarker({ committedAt });
    const now = new Date(Date.parse(committedAt) + CHAIN_STALENESS_TIMEOUT_MINUTES * 60 * 1000);
    expect(isMarkerStale(marker, now)).toBe(false);
  });
});

describe('resolveRoundContext', () => {
  const now = new Date('2026-08-15T12:00:00.000Z');

  it('resumes the same burst at round + 1 for a continuing marker', () => {
    const marker = makeMarker({ burstId: '2026-08-15T10:00:00.000Z', round: 3, status: 'continuing' });
    expect(resolveRoundContext(marker, now)).toEqual({ burstId: '2026-08-15T10:00:00.000Z', round: 4 });
  });

  it('starts a fresh burst at round 1 with no marker', () => {
    expect(resolveRoundContext(null, now)).toEqual({ burstId: now.toISOString(), round: 1 });
  });

  it('starts a fresh burst at round 1 for a done marker', () => {
    const marker = makeMarker({ burstId: '2026-08-15T10:00:00.000Z', round: 5, status: 'done' });
    expect(resolveRoundContext(marker, now)).toEqual({ burstId: now.toISOString(), round: 1 });
  });
});

describe('buildRoundMarker', () => {
  const now = new Date('2026-08-15T12:00:00.000Z');
  const burstId = '2026-08-15T10:00:00.000Z';

  it('is continuing when the queue is non-empty and under both checks', () => {
    const marker = buildRoundMarker(burstId, 3, { newlyRendered: 220, copiedForward: 4025, queueRemaining: 1800 }, now);
    expect(marker).toEqual({
      burstId,
      round: 3,
      status: 'continuing',
      newlyRendered: 220,
      copiedForward: 4025,
      queueRemaining: 1800,
      committedAt: now.toISOString(),
    });
  });

  it('is done when the queue is empty', () => {
    const marker = buildRoundMarker(burstId, 2, { newlyRendered: 100, copiedForward: 50, queueRemaining: 0 }, now);
    expect(marker.status).toBe('done');
  });

  it('is done when the chain-depth cap is exceeded, even with a non-empty queue', () => {
    const marker = buildRoundMarker(
      burstId,
      CHAIN_MAX_ROUNDS + 1,
      { newlyRendered: 100, copiedForward: 50, queueRemaining: 1000 },
      now,
    );
    expect(marker.status).toBe('done');
  });

  it('is done on zero progress, even with a non-empty queue', () => {
    const marker = buildRoundMarker(
      burstId,
      3,
      { newlyRendered: 0, copiedForward: 5000, queueRemaining: 1000 },
      now,
    );
    expect(marker.status).toBe('done');
  });
});
