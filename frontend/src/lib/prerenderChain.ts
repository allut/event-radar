import { CHAIN_MARKER_PREFIX, CHAIN_MAX_ROUNDS, CHAIN_STALENESS_TIMEOUT_MINUTES, MS_PER_MINUTE } from '../constants';

/** Round-state carrier for the time-boxed incremental prerender pipeline
 * (issue #79) — standalone pure functions only (no I/O), so the chaining
 * state machine is unit-testable without a real Playwright browser or Vercel
 * deploy. Wired into scripts/prerender.ts's `main()` (issue #83: reads
 * VERCEL_GIT_COMMIT_MESSAGE at build start, builds/commits the round marker
 * at the end); firing the Deploy Hook itself is a later ticket (issue #84).
 * Mirrors this repo's existing
 * fetchPublishedEventIds/buildTargets/buildSitemapXml-style decomposition. */

export type RoundStatus = 'continuing' | 'done';

export interface RoundMarker {
  /** Timestamp of the burst's first round — identifies which chain a round
   * belongs to; stable across every round in the same burst. */
  burstId: string;
  round: number;
  status: RoundStatus;
  /** Routes actually rendered this round — the only count that feeds
   * isZeroProgress; copied-forward routes never count toward progress. */
  newlyRendered: number;
  copiedForward: number;
  queueRemaining: number;
  /** ISO timestamp this marker was committed — isMarkerStale's clock. */
  committedAt: string;
}

/** Embeds `marker` as a single delimited line so it survives inside an
 * otherwise human-readable commit message — parseRoundMarker only needs to
 * find this line, not the whole message. JSON, not a hand-rolled format:
 * the field set is small and fixed, so JSON.stringify's overhead is
 * negligible against the 2048-byte VERCEL_GIT_COMMIT_MESSAGE cap even at
 * thousands-of-routes progress counts. */
export function serializeRoundMarker(marker: RoundMarker): string {
  const payload = {
    burst_id: marker.burstId,
    round: marker.round,
    status: marker.status,
    newly_rendered: marker.newlyRendered,
    copied_forward: marker.copiedForward,
    queue_remaining: marker.queueRemaining,
    committed_at: marker.committedAt,
  };
  return `${CHAIN_MARKER_PREFIX} ${JSON.stringify(payload)}`;
}

function isRoundStatus(value: unknown): value is RoundStatus {
  return value === 'continuing' || value === 'done';
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isIsoTimestamp(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value));
}

/** Parses a marker back out of `commitMessage` (typically the raw
 * VERCEL_GIT_COMMIT_MESSAGE value, which may carry other human-readable text
 * around the marker line). Never throws — malformed JSON, a missing marker
 * line, or a structurally invalid payload (wrong types, negative counts, an
 * unrecognized status) all fall back to `null`, which callers treat as "no
 * active chain" (see isMarkerStale's staleness fallback and the spec's
 * cron/self-trigger collision guard). */
export function parseRoundMarker(commitMessage: string | null | undefined): RoundMarker | null {
  if (!commitMessage) return null;
  const line = commitMessage.split('\n').find((l) => l.startsWith(CHAIN_MARKER_PREFIX));
  if (!line) return null;
  const raw = line.slice(CHAIN_MARKER_PREFIX.length).trim();

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null) return null;
  const p = parsed as Record<string, unknown>;

  if (
    typeof p.burst_id !== 'string' ||
    !isRoundStatus(p.status) ||
    !isNonNegativeInteger(p.round) ||
    p.round < 1 ||
    !isNonNegativeInteger(p.newly_rendered) ||
    !isNonNegativeInteger(p.copied_forward) ||
    !isNonNegativeInteger(p.queue_remaining) ||
    !isIsoTimestamp(p.committed_at)
  ) {
    return null;
  }

  return {
    burstId: p.burst_id,
    round: p.round,
    status: p.status,
    newlyRendered: p.newly_rendered,
    copiedForward: p.copied_forward,
    queueRemaining: p.queue_remaining,
    committedAt: p.committed_at,
  };
}

/** True once `round` has gone past CHAIN_MAX_ROUNDS — round 10 itself is
 * still "at cap" (allowed, the last permitted round of the burst); only
 * round 11+ is over cap. Callers use this to abort chaining rather than
 * fire another Deploy Hook round. */
export function isChainDepthExceeded(round: number): boolean {
  return round > CHAIN_MAX_ROUNDS;
}

/** True only when this round rendered zero new routes — copied-forward
 * routes never count toward progress, per the spec's zero-progress
 * definition, so a round that copied thousands forward but rendered nothing
 * fresh still counts as stuck. */
export function isZeroProgress(progress: { newlyRendered: number; copiedForward: number }): boolean {
  return progress.newlyRendered === 0;
}

/** True when `marker.committedAt` is older than CHAIN_STALENESS_TIMEOUT_MINUTES
 * relative to `now` — a stale `continuing` marker is treated as a crashed
 * mid-chain build rather than an active one, so cron resumes rather than
 * skipping forever. */
export function isMarkerStale(marker: RoundMarker, now: Date): boolean {
  const ageMs = now.getTime() - Date.parse(marker.committedAt);
  return ageMs > CHAIN_STALENESS_TIMEOUT_MINUTES * MS_PER_MINUTE;
}

export interface RoundStartDecision {
  /** True when this build should exit immediately without rendering
   * anything or committing a marker — see resolveRoundStart. */
  skip: boolean;
  burstId: string;
  round: number;
}

/** Cron/self-trigger collision guard (issue #85) — the very first decision
 * every build makes, before any rendering. A fresh (<CHAIN_STALENESS_TIMEOUT_MINUTES)
 * `continuing` marker means a chain is already active in flight (its own
 * self-triggered continuation, or another build reading the same in-flight
 * state), so this build skips entirely rather than risk double-rendering.
 * Anything else — missing, `done`, or a stale `continuing` marker (a
 * crashed mid-chain build) — is "no active chain": this build proceeds as a
 * normal round via resolveRoundContext.
 *
 * A stale `continuing` marker is deliberately not handed to
 * resolveRoundContext as-is: that function always resumes on `continuing`
 * regardless of age (by design — see its own tests, which resume even a
 * very old marker), because staleness is this guard's responsibility, not
 * resolveRoundContext's. So a stale marker is treated as absent here before
 * handing off, starting a fresh burst instead of "resuming" a chain nothing
 * is actually driving forward. */
export function resolveRoundStart(commitMessage: string | null | undefined, now: Date): RoundStartDecision {
  const marker = parseRoundMarker(commitMessage);
  if (marker && marker.status === 'continuing' && !isMarkerStale(marker, now)) {
    return { skip: true, burstId: marker.burstId, round: marker.round };
  }
  const effectiveMarker = marker && marker.status === 'continuing' ? null : marker;
  const { burstId, round } = resolveRoundContext(effectiveMarker, now);
  return { skip: false, burstId, round };
}

/** Determines which burst/round a build belongs to (issue #83), from the
 * marker (if any) parsed out of this build's VERCEL_GIT_COMMIT_MESSAGE.
 * Only a `continuing` marker resumes the same burst at `round + 1` — a
 * missing/unparseable marker (parseRoundMarker already returned `null`) or
 * one with `status: done` both start a fresh burst at round 1, per the
 * spec's "no active chain" fallback. `now` seeds a new burst's id (the
 * spec's burst_id is "the timestamp of the burst's first round"). */
export function resolveRoundContext(
  marker: RoundMarker | null,
  now: Date,
): { burstId: string; round: number } {
  if (marker && marker.status === 'continuing') {
    return { burstId: marker.burstId, round: marker.round + 1 };
  }
  return { burstId: now.toISOString(), round: 1 };
}

/** Builds the marker to commit for the round just completed (issue #83),
 * deciding `status` per the spec: `continuing` only if the queue isn't
 * empty *and* neither the chain-depth cap nor the zero-progress check say
 * otherwise; `done` in every other case (queue emptied, depth exceeded, or
 * zero progress). Enforcing those checks here — not just in the later
 * Deploy Hook ticket (#84) — keeps the committed marker's `status` field
 * truthful on its own, so `git log` reflects the real outcome even before
 * hook-firing is wired up. */
export function buildRoundMarker(
  burstId: string,
  round: number,
  progress: { newlyRendered: number; copiedForward: number; queueRemaining: number },
  now: Date,
): RoundMarker {
  const status: RoundStatus =
    progress.queueRemaining === 0 || isChainDepthExceeded(round) || isZeroProgress(progress)
      ? 'done'
      : 'continuing';
  return {
    burstId,
    round,
    status,
    newlyRendered: progress.newlyRendered,
    copiedForward: progress.copiedForward,
    queueRemaining: progress.queueRemaining,
    committedAt: now.toISOString(),
  };
}
