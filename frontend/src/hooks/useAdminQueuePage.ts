import { useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient, type QueryKey } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { StatusCodes } from 'http-status-codes';
import { ApiError } from '../api/client';
import { PAGE_QUERY_PARAM, QUERY_KEYS } from '../constants/api';
import { MOBILE_BREAKPOINT_PX } from '../constants/core';
import { usePagedQuery, type UsePagedQueryOptions } from './usePagedQuery';
import { parsePageParam } from './usePageParam';

/** A row the admin acted on this page: its snapshot, what was done, and the
 * slot it held on screen when it was acted on. */
export interface TaggedRow<TItem, TKind extends string> {
  item: TItem;
  kind: TKind;
  slot: number;
}

/** Rows to render for one page of a resolving queue (spec #551): the server's
 * rows in order, with each tagged row put back in the slot it held when it
 * was acted on, even once the server stops returning it. Rows the refetch
 * pulled up from the next page therefore land at the bottom. */
export function mergeQueueRows<TItem>(
  serverItems: readonly TItem[],
  tagged: ReadonlyMap<number, { item: TItem; slot: number }>,
  getId: (item: TItem) => number,
): TItem[] {
  const rows = serverItems.filter((item) => !tagged.has(getId(item)));
  const bySlot = Array.from(tagged.values()).sort((a, b) => a.slot - b.slot);
  for (const { item, slot } of bySlot) rows.splice(Math.min(slot, rows.length), 0, item);
  return rows;
}

/** Where a row sat when the admin acted on it: the page offset and its slot
 * in the rendered rows. Capture it with `actionSpot` when the action is
 * triggered (in the mutation variables) and hand it back to `tagRow`. */
export interface ActionSpot {
  offset: number;
  slot: number;
}

interface TagState<TItem, TKind extends string> {
  /** The offset of the page the tags were made on. */
  offset: number;
  byId: ReadonlyMap<number, TaggedRow<TItem, TKind>>;
}

export interface UseAdminQueuePageOptions<TData, TItem>
  extends Pick<UsePagedQueryOptions<TData, TItem>, 'queryKey' | 'pageSize' | 'fetchPage' | 'select'> {
  getId: (item: TItem) => number;
  /** The key prefix one action invalidates, refetching whichever of its
   * queries is mounted. Defaults to `queryKey`; Claims pass the whole
   * claims prefix, since an action moves a claim between tabs. */
  invalidateKey?: QueryKey;
  /** Route-specific resets once a new page has settled (e.g. the note draft),
   * after the shared ones: first row selected and focused, tags cleared,
   * list scroll reset. A silent replace onto another page (a refetch that
   * emptied this one clamps) runs it too, after selecting the first row but
   * without moving focus or scroll. */
  onPageSettled?: () => void;
}

/** One page of an admin queue whose rows get resolved (Submissions, Claims,
 * Reports — spec #551). Wraps usePagedQuery with the split-view behaviour:
 *
 * - `tagRow` records a successful row-removing action and triggers one
 *   background refetch of the current page (no debounce), so the next page
 *   never skips rows. Tagged rows stay in place; pulled-up rows append.
 *   Pass it the `actionSpot(item)` captured when the action was triggered
 *   (in the mutation variables): onSuccess runs with the latest render, so an
 *   action that resolves after the admin changed page must not tag onto the
 *   new one, and one whose row a refetch already dropped still tags in place.
 * - The page is held (`holdEmptyPage`) while it has tagged rows, so clearing
 *   a last page leaves the admin on it with the no-items label.
 * - A page change selects and focuses the first row, resets the list's
 *   scroll (and on mobile scrolls the list top into view) and clears tags.
 *
 * Pass `listRef` and `rows` to AdminQueueSplitView, and put
 * `<Pager {...pagerProps} />` in its `listFooter`. */
export function useAdminQueuePage<TData, TItem, TKind extends string>({
  queryKey,
  pageSize,
  fetchPage,
  select,
  getId,
  invalidateKey = queryKey,
  onPageSettled,
}: UseAdminQueuePageOptions<TData, TItem>) {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const requestedOffset = (parsePageParam(searchParams.get(PAGE_QUERY_PARAM)).page - 1) * pageSize;
  const listRef = useRef<HTMLDivElement>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tags, setTags] = useState<TagState<TItem, TKind> | null>(null);

  // The offset of the last page whose real data rendered, so a silent move to
  // another page (a clamp replace) can run the resets a push/POP settle runs.
  const settledOffsetRef = useRef<number | null>(null);

  const paged = usePagedQuery({
    queryKey,
    pageSize,
    fetchPage,
    select,
    holdEmptyPage: tags !== null && tags.byId.size > 0 && tags.offset === requestedOffset,
    onPageSettled: () => {
      settledOffsetRef.current = paged.offset;
      const first = paged.items[0];
      setSelectedId(first === undefined ? null : getId(first));
      setTags(null);
      const list = listRef.current;
      if (list) {
        list.scrollTop = 0;
        if (window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX}px)`).matches) {
          list.scrollIntoView({ block: 'start', behavior: 'auto' });
        }
        const firstRow = list.firstElementChild;
        if (firstRow instanceof HTMLElement) firstRow.focus({ preventScroll: true });
      }
      onPageSettled?.();
    },
  });
  const { items: serverItems, offset, isSuccess, isPlaceholderData } = paged;

  // Declared after usePagedQuery so a push/POP settle in the same commit has
  // already recorded its offset and this does nothing.
  const settled = isSuccess && !isPlaceholderData;
  const firstId = serverItems[0] === undefined ? null : getId(serverItems[0]);
  const onPageSettledRef = useRef(onPageSettled);
  useEffect(() => {
    onPageSettledRef.current = onPageSettled;
  });
  useEffect(() => {
    if (!settled) return;
    const previous = settledOffsetRef.current;
    settledOffsetRef.current = offset;
    if (previous === null || previous === offset) return;
    setSelectedId(firstId);
    setTags(null);
    onPageSettledRef.current?.();
  }, [settled, offset, firstId]);

  // Tags only count on the page they were made on (a page change, even a
  // silent replace, leaves them behind).
  const pageTags = useMemo(
    () => (tags !== null && tags.offset === offset ? tags.byId : new Map<number, TaggedRow<TItem, TKind>>()),
    [tags, offset],
  );

  const rows = useMemo(() => mergeQueueRows(serverItems, pageTags, getId), [serverItems, pageTags, getId]);

  /** The spot to capture when an action on `item` is triggered. */
  const actionSpot = (item: TItem): ActionSpot => {
    const id = getId(item);
    return { offset, slot: Math.max(0, rows.findIndex((row) => getId(row) === id)) };
  };

  /** Record a successful row-removing action and refetch the page once.
   * `spot` is the `actionSpot` captured when the action was triggered; when
   * the admin has since left that page, the row is not tagged and only the
   * refetch runs. On the same page it always tags, at the row's current slot
   * or (if a refetch already dropped it) the captured one. Returns whether
   * it tagged, so the route only resets its note draft for this page. */
  const tagRow = (item: TItem, kind: TKind, spot: ActionSpot): boolean => {
    const id = getId(item);
    const samePage = spot.offset === offset && spot.offset === requestedOffset;
    // One background refetch of the active page per action; the list's other
    // cached pages are only marked stale.
    void queryClient.invalidateQueries({ queryKey: invalidateKey });
    if (!samePage) return false;
    const shownSlot = rows.findIndex((row) => getId(row) === id);
    const slot = shownSlot === -1 ? spot.slot : shownSlot;
    setTags((prev) => {
      const byId = new Map(prev !== null && prev.offset === offset ? prev.byId : []);
      byId.set(id, { item, kind, slot: byId.get(id)?.slot ?? slot });
      return { offset, byId };
    });
    return true;
  };

  /** For a failed action's onError: a 409/404 means another admin already
   * resolved (or removed) the row, so refetch the page and the queue counts
   * to drop it and realign the offsets. Other errors leave the list as is. */
  const resyncAfterFailedAction = (err: unknown): void => {
    if (!(err instanceof ApiError)) return;
    if (err.status !== StatusCodes.CONFLICT && err.status !== StatusCodes.NOT_FOUND) return;
    void queryClient.invalidateQueries({ queryKey: invalidateKey });
    void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminCounts] });
  };

  return {
    ...paged,
    rows,
    /** This page's acted-on rows, by id. */
    tags: pageTags,
    tagRow,
    actionSpot,
    resyncAfterFailedAction,
    selectedId,
    setSelectedId,
    listRef,
  };
}
