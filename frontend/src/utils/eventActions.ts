import { type QueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { API, QUERY_KEYS } from '../constants/api';
import { SIGNAL_CLICK_EXTERNAL } from '../constants/feedback';

export function trackExternalClick(eventId: number): void {
  api.post(API.feedback, { event_id: eventId, signal: SIGNAL_CLICK_EXTERNAL }).catch(() => undefined);
}

/** Copy text to the clipboard. Returns true on success, false if the
 * clipboard API is unavailable or blocked (caller surfaces the failure). */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Shares a page (native share sheet, falling back to a clipboard copy) — the
 * logic behind EventDetail's and EventCard's Share menu item, factored out so
 * both call sites (issue #128) stay in sync. Returns 'shared' when the native
 * share sheet handled it (no further UI needed), 'copied'/'failed' for the
 * clipboard-fallback outcome the caller should surface as a toast, or
 * 'cancelled' when the user dismissed the native share sheet. */
export async function shareEvent(title: string | undefined, url: string): Promise<'shared' | 'copied' | 'failed' | 'cancelled'> {
  if (navigator.share) {
    try {
      await navigator.share({ title, url });
      return 'shared';
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return 'cancelled';
      // unsupported/blocked share — fall through to copy
    }
  }
  return (await copyToClipboard(url)) ? 'copied' : 'failed';
}

interface CachedEventLike {
  id: number;
}
interface CachedEventsPage {
  events: CachedEventLike[];
}

function patchEventInPage<T extends CachedEventsPage>(page: T, eventId: number, patch: object): T {
  if (!Array.isArray(page?.events) || !page.events.some((e) => e.id === eventId)) return page;
  return { ...page, events: page.events.map((e) => (e.id === eventId ? { ...e, ...patch } : e)) };
}

/** Writes `patch` (e.g. `{ my_signal }`, `{ reported }`) onto one event's row in
 * every cached Feed / Explore page / event-detail payload, so a save/like/report
 * is reflected everywhere without refetching (an Explore refetch re-scores
 * server-side). Saved-tab payloads are deliberately left alone: membership
 * there changes with the signal, so callers invalidate them instead. */
export function patchCachedEvent(queryClient: QueryClient, eventId: number, patch: object): void {
  for (const key of [QUERY_KEYS.feed, QUERY_KEYS.explore]) {
    queryClient.setQueriesData<CachedEventsPage>({ queryKey: [key] }, (old) =>
      old ? patchEventInPage(old, eventId, patch) : old,
    );
  }
  queryClient.setQueriesData<CachedEventLike>({ queryKey: [QUERY_KEYS.event] }, (old) =>
    old && old.id === eventId ? { ...old, ...patch } : old,
  );
}
