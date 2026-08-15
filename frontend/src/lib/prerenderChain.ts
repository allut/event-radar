import { CHAIN_MARKER_PREFIX, CHAIN_MAX_ROUNDS, CHAIN_STALENESS_TIMEOUT_MINUTES, MS_PER_MINUTE } from '../constants';

/** Round-state carrier for the time-boxed incremental prerender pipeline
 * (issue #79) — standalone pure functions only (no I/O), so the chaining
 * state machine is unit-testable without a real Playwright browser or Vercel
 * deploy. Not wired into scripts/prerender.ts's `main()` yet; that happens in
 * later tickets (issue #83 reads/writes VERCEL_GIT_COMMIT_MESSAGE and fires
 * the Deploy Hook). Mirrors this file's existing
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
