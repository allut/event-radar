import { describe, it, expect } from 'vitest';
import {
  serializeRoundMarker,
  parseRoundMarker,
  isChainDepthExceeded,
  isZeroProgress,
  isMarkerStale,
  resolveRoundContext,
  resolveRoundStart,
  buildRoundMarker,
  shouldSkipCadenceTick,
  shouldCommitRoundMarker,
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

describe('resolveRoundStart', () => {
  // Enumerated against the four acceptance-criteria cases: fresh continuing
  // (resume at round + 1, issue #90), stale continuing (fresh round 1), done
  // (fresh round 1), missing (fresh round 1).
  const now = new Date('2026-08-15T12:00:00.000Z');

  it('resumes at round + 1 for a fresh (<30min) continuing marker', () => {
    const marker = makeMarker({
      burstId: '2026-08-15T11:50:00.000Z',
      round: 2,
      status: 'continuing',
      committedAt: '2026-08-15T11:45:00.000Z', // 15 min old — under the timeout
    });
    expect(resolveRoundStart(serializeRoundMarker(marker), now)).toEqual({
      burstId: marker.burstId,
      round: marker.round + 1,
    });
  });

  it('resumes at round + 1 for a marker committed seconds ago', () => {
    const marker = makeMarker({
      burstId: '2026-08-15T11:50:00.000Z',
      round: 1,
      status: 'continuing',
      committedAt: '2026-08-15T11:59:55.000Z', // 5 sec old
    });
    expect(resolveRoundStart(serializeRoundMarker(marker), now)).toEqual({
      burstId: marker.burstId,
      round: 2,
    });
  });

  it('proceeds as a fresh round 1 for a continuing marker older than 30 minutes', () => {
    const marker = makeMarker({
      burstId: '2026-08-15T09:00:00.000Z',
      round: 4,
      status: 'continuing',
      committedAt: '2026-08-15T11:20:00.000Z', // 40 min old — over the timeout
    });
    expect(resolveRoundStart(serializeRoundMarker(marker), now)).toEqual({
      burstId: now.toISOString(),
      round: 1,
    });
  });

  it('proceeds as a fresh round 1 for a done marker', () => {
    const marker = makeMarker({ status: 'done', committedAt: '2026-08-15T11:59:00.000Z' });
    expect(resolveRoundStart(serializeRoundMarker(marker), now)).toEqual({
      burstId: now.toISOString(),
      round: 1,
    });
  });

  it('proceeds as a fresh round 1 with no marker at all', () => {
    expect(resolveRoundStart(undefined, now)).toEqual({
      burstId: now.toISOString(),
      round: 1,
    });
    expect(resolveRoundStart('unrelated commit message, no marker line', now)).toEqual({
      burstId: now.toISOString(),
      round: 1,
    });
  });

  it('advances round on two consecutive resumes, simulating a real chain (local repro)', () => {
    // Round 1 finishes and commits a fresh `continuing` marker...
    const round1Marker = makeMarker({
      burstId: '2026-08-15T11:00:00.000Z',
      round: 1,
      status: 'continuing',
      committedAt: '2026-08-15T11:58:00.000Z',
    });
    const round2Start = resolveRoundStart(serializeRoundMarker(round1Marker), now);
    expect(round2Start).toEqual({ burstId: round1Marker.burstId, round: 2 });

    // ...round 2 runs, still has work queued, and commits its own fresh
    // `continuing` marker moments later.
    const round2Marker = makeMarker({
      burstId: round2Start.burstId,
      round: round2Start.round,
      status: 'continuing',
      committedAt: '2026-08-15T11:59:30.000Z',
    });
    const round3Start = resolveRoundStart(serializeRoundMarker(round2Marker), now);
    expect(round3Start).toEqual({ burstId: round1Marker.burstId, round: 3 });
  });
});

describe('shouldSkipCadenceTick', () => {
  const now = new Date('2026-08-15T12:00:00.000Z');

  it('skips for a fresh (<30min) continuing marker', () => {
    const marker = makeMarker({ status: 'continuing', committedAt: '2026-08-15T11:45:00.000Z' });
    expect(shouldSkipCadenceTick(serializeRoundMarker(marker), now)).toBe(true);
  });

  it('does not skip for a continuing marker older than 30 minutes', () => {
    const marker = makeMarker({ status: 'continuing', committedAt: '2026-08-15T11:20:00.000Z' });
    expect(shouldSkipCadenceTick(serializeRoundMarker(marker), now)).toBe(false);
  });

  it('does not skip for a done marker', () => {
    const marker = makeMarker({ status: 'done', committedAt: '2026-08-15T11:59:00.000Z' });
    expect(shouldSkipCadenceTick(serializeRoundMarker(marker), now)).toBe(false);
  });

  it('does not skip with no marker at all', () => {
    expect(shouldSkipCadenceTick(undefined, now)).toBe(false);
    expect(shouldSkipCadenceTick('unrelated commit message', now)).toBe(false);
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

describe('shouldCommitRoundMarker', () => {
  const burstId = '2026-08-15T10:00:00.000Z';
  const now = new Date('2026-08-15T12:00:00.000Z');

  it('commits (pushes) a continuing marker — the push is what triggers the next round', () => {
    const marker = buildRoundMarker(burstId, 1, { newlyRendered: 220, copiedForward: 4025, queueRemaining: 1800 }, now);
    expect(shouldCommitRoundMarker(marker)).toBe(true);
  });

  it('does not commit a done marker — nothing needs to resume, so no push should fire', () => {
    const marker = buildRoundMarker(burstId, 1, { newlyRendered: 3, copiedForward: 4269, queueRemaining: 0 }, now);
    expect(marker.status).toBe('done');
    expect(shouldCommitRoundMarker(marker)).toBe(false);
  });

  it('reproduces the overnight incident: unconditionally committing every `done` round self-triggers forever', () => {
    // Home routes never classify as `unchanged` (no Event.updated_at to diff
    // against — see classifyTarget in prerender.ts), so every fresh burst
    // renders exactly the 3 home routes (en/et/ru) and finishes with an
    // empty queue on round 1 — status is always 'done', never zero-progress.
    // A `done` marker is "no active chain" to resolveRoundStart, so if it
    // were pushed anyway, the next build starts a brand-new burst and hits
    // this exact same steady state — with nothing to ever break the cycle.
    let commitMessage: string | undefined;
    let selfTriggeredPushes = 0;
    for (let build = 0; build < 25; build++) {
      const { burstId: b, round } = resolveRoundStart(commitMessage, now);
      const marker = buildRoundMarker(b, round, { newlyRendered: 3, copiedForward: 4269, queueRemaining: 0 }, now);
      expect(marker.status).toBe('done');
      expect(round).toBe(1); // never resumes — always a fresh burst, as observed in the logs
      // This is the bug under test: scripts/prerender.ts's main() used to call
      // commitRoundMarker(marker) unconditionally here, instead of gating on
      // shouldCommitRoundMarker(marker) — so it always pushed, and the push
      // alone triggers the next Vercel build (docs/backend-ops.md).
      if (shouldCommitRoundMarker(marker)) {
        selfTriggeredPushes++;
        commitMessage = `prerender: round ${marker.round} (${marker.status})\n\n${serializeRoundMarker(marker)}`;
      } else {
        commitMessage = undefined; // no push — nothing left to trigger the next build
        break;
      }
    }
    expect(selfTriggeredPushes).toBe(0);
  });
});
