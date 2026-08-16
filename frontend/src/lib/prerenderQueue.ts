/** Priority-queue + time-box primitives for the incremental prerender render
 * pass (issue #82) — standalone pure functions only (no I/O, no Playwright),
 * so the cap-stopping and ordering behavior is unit-testable without a real
 * browser or a 10-minute wait. Wired into scripts/prerender.ts's render loop.
 * Mirrors src/lib/prerenderChain.ts's decomposition (issue #81): the stateful
 * script owns I/O, this module owns the decision logic. */

export interface QueueCandidate {
  /** Set for /events/:id targets only — mirrors PrerenderTarget.eventId in
   * scripts/prerender.ts. Home routes carry neither this nor updatedAt. */
  eventId?: number;
  /** ISO Event.updated_at — set alongside eventId only. */
  updatedAt?: string;
}

/** Orders `items` home-routes-first (all locales), then event routes
 * oldest-unrendered-first by `updatedAt`. A stable sort, so items that tie
 * (home routes against each other, or same-`updatedAt` event routes across
 * locale variants) keep their relative input order. */
export function prioritizeRenderQueue<T extends QueueCandidate>(items: T[]): T[] {
  return [...items]
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const aIsHome = a.item.eventId === undefined;
      const bIsHome = b.item.eventId === undefined;
      if (aIsHome !== bIsHome) return aIsHome ? -1 : 1;
      if (!aIsHome && !bIsHome) {
        const diff = Date.parse(a.item.updatedAt as string) - Date.parse(b.item.updatedAt as string);
        if (diff !== 0) return diff;
      }
      return a.index - b.index;
    })
    .map(({ item }) => item);
}

export interface BudgetedCursor {
  /** Returns the next not-yet-claimed index, or `null` once the queue is
   * exhausted or `now()` has reached `deadlineMs` — the hard-cap stopping
   * point. Never blocks/waits; callers stop pulling once they see `null`. */
  next(): number | null;
  /** Indices never claimed because the deadline hit first — the routes that
   * stay queued for the next round/cadence tick (issue #82's "queue
   * remaining" count). Empty once the cap wasn't hit before the queue drained. */
  remaining(): number[];
}

/** A single-cursor, budget-aware index allocator shared by every concurrent
 * render-pool lane in scripts/prerender.ts — plain incrementing state, safe
 * under concurrent async workers since JS only interleaves at `await`
 * points and `next()` itself awaits nothing. `now` is injectable so the cap
 * is verifiable with a fake clock instead of a real 10-minute wait. */
export function createBudgetedCursor(
  total: number,
  deadlineMs: number,
  now: () => number = Date.now,
): BudgetedCursor {
  let cursor = 0;
  return {
    next(): number | null {
      if (cursor >= total || now() >= deadlineMs) return null;
      return cursor++;
    },
    remaining(): number[] {
      return Array.from({ length: Math.max(0, total - cursor) }, (_, i) => cursor + i);
    },
  };
}
