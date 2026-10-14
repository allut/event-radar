import { useCallback, useEffect, useRef, useState } from 'react';
import { keepPreviousData, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { useLocation, useNavigationType, useSearchParams } from 'react-router-dom';
import { PAGINATION_MAX_OFFSET } from '../_generated/sharedConstants';
import { PAGE_QUERY_PARAM } from '../constants/api';
import type { PagerAnnouncement, PagerProps } from '../components/Pager';
import { isPagerNavigation, usePageParam } from './usePageParam';

/** The paging fields a list's response maps onto (`select`). */
export interface PagedSlice<TItem> {
  items: TItem[];
  total: number;
  offset: number;
  totalIsLowerBound?: boolean;
}

export interface UsePagedQueryOptions<TData, TItem> {
  /** The list's own key (filters, tab, locale…); the page is appended. */
  queryKey: QueryKey;
  pageSize: number;
  fetchPage: (request: { limit: number; offset: number; page: number }) => Promise<TData>;
  select: (data: TData) => PagedSlice<TItem>;
  /** Runs once the real data for a new page has rendered, only after a
   * <Pager> link push or a POP (back/forward) — never on first mount, a
   * silent `replace`, a setListParams filter change or any other app link
   * (nav, preset chips) that lands on a different page. A clamp that
   * redirects a pager push or POP settles on the page it lands on. */
  onPageSettled?: () => void;
  /** While true, an emptied page is held instead of clamped to the last page
   * (admin queues pass "there are tagged rows"). */
  holdEmptyPage?: boolean;
  enabled?: boolean;
}

export type PagedPagerProps = Omit<PagerProps, 'locale' | 'dropOnPageChange' | 'className' | 'liveNoun'>;

/** The data layer of a paged list (spec #551): one page per query with
 * keep-previous-data, the past-end clamp, server-placed offset sync and the
 * page-settled hook. Pair it with <Pager {...pagerProps} />. */
export function usePagedQuery<TData, TItem>({
  queryKey,
  pageSize,
  fetchPage,
  select,
  onPageSettled,
  holdEmptyPage = false,
  enabled = true,
}: UsePagedQueryOptions<TData, TItem>) {
  const { page, malformed } = usePageParam();
  const [, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const navigationType = useNavigationType();
  const location = useLocation();

  // The backend rejects an offset past PAGINATION_MAX_OFFSET (422), so the
  // deepest reachable page is the last one whose offset is within it. A
  // deeper (stale) link never fetches; it replaces to that page below.
  const maxPage = Math.floor(PAGINATION_MAX_OFFSET / pageSize) + 1;
  const beyondCeiling = page > maxPage;

  const query = useQuery({
    queryKey: [...queryKey, page],
    queryFn: () => fetchPage({ limit: pageSize, offset: (page - 1) * pageSize, page }),
    // A caller-disabled query (Explore's emptied facet) matches nothing, so it
    // must not keep showing the previous key's rows: TanStack applies the
    // placeholder to a disabled query too. The malformed/past-ceiling cases
    // keep it, since they replace to a real page straight away.
    placeholderData: enabled ? keepPreviousData : undefined,
    enabled: enabled && !malformed && !beyondCeiling,
  });
  const { data, dataUpdatedAt, isSuccess, isPlaceholderData } = query;

  const slice = data === undefined ? null : select(data);
  const items = slice?.items ?? [];
  // Past the ceiling only maxPage pages are reachable: the label and the
  // announcement then use the lower-bound form over the reachable count.
  const reachableCount = maxPage * pageSize;
  const serverTotal = slice?.total ?? 0;
  const cappedAtCeiling = serverTotal > reachableCount;
  const total = cappedAtCeiling ? reachableCount : serverTotal;
  const offset = slice?.offset ?? 0;
  const totalIsLowerBound = (slice?.totalIsLowerBound ?? false) || cappedAtCeiling;
  const itemCount = items.length;
  const lastPage = Math.max(1, Math.ceil(total / pageSize));

  // An announcement belongs to the history entry it was made on: any later
  // navigation (page change, filter push, silent replace) retires it.
  const [announced, setAnnounced] = useState<{
    key: string;
    announcement: PagerAnnouncement | null;
  } | null>(null);
  const announcement = announced?.key === location.key ? announced.announcement : null;
  const onPageSettledRef = useRef(onPageSettled);
  // Callers pass an inline key array, so the settle effect reads it from a
  // ref instead of re-running on every render.
  const queryKeyRef = useRef(queryKey);
  useEffect(() => {
    onPageSettledRef.current = onPageSettled;
    queryKeyRef.current = queryKey;
  });

  const replacePage = useCallback(
    (target: number) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (target <= 1) next.delete(PAGE_QUERY_PARAM);
          else next.set(PAGE_QUERY_PARAM, String(target));
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // Page-change detection. Declared before the settle effect so a page that
  // is already cached (back to a fresh page) settles in the same commit. A
  // pending settle belongs to the history entry that made it: any move to
  // another entry retires it at once, so a filter push before its data lands
  // (same page, new entry) stays silent, and so does a later Back to it.
  const previousPageRef = useRef(page);
  // `minUpdatedAt`: only data fetched at or after it may settle (0 = any).
  const pendingSettleRef = useRef<{ page: number; key: string; minUpdatedAt: number } | null>(null);
  // Set when a silent replace redirects a counted page change (the page the
  // user asked for emptied): the replace's target settles in its place.
  const carrySettleRef = useRef<{ minUpdatedAt: number } | null>(null);
  useEffect(() => {
    if (pendingSettleRef.current !== null && pendingSettleRef.current.key !== location.key) {
      pendingSettleRef.current = null;
    }
    if (previousPageRef.current === page) return;
    previousPageRef.current = page;
    const carried = carrySettleRef.current;
    carrySettleRef.current = null;
    const counts =
      carried !== null ||
      navigationType === 'POP' ||
      (navigationType === 'PUSH' && isPagerNavigation(location.state));
    pendingSettleRef.current = counts ? { page, key: location.key, minUpdatedAt: carried?.minUpdatedAt ?? 0 } : null;
  }, [page, navigationType, location.state, location.key]);

  // A stale link past the offset ceiling: land on the deepest reachable page.
  useEffect(() => {
    if (!beyondCeiling) return;
    pendingSettleRef.current = null;
    replacePage(maxPage);
  }, [beyondCeiling, maxPage, replacePage]);

  useEffect(() => {
    if (!isSuccess || isPlaceholderData || data === undefined) return;
    const pending = pendingSettleRef.current;
    const pendingHere = pending !== null && pending.page === page && pending.key === location.key;
    // A silent replace; when it redirects the user's own page change, the
    // target page settles (focus, announcement) instead of focus dropping.
    const redirect = (target: number, minUpdatedAt = 0) => {
      carrySettleRef.current = pendingHere ? { minUpdatedAt } : null;
      pendingSettleRef.current = null;
      replacePage(target);
    };
    const requestedOffset = (page - 1) * pageSize;
    if (offset !== requestedOffset) {
      // Server-placed offset (e.g. the Admin Reports locate): sync silently.
      redirect(Math.floor(offset / pageSize) + 1);
      return;
    }
    if (itemCount === 0 && !holdEmptyPage && page !== lastPage) {
      // Past the end, or a refetch emptied this page: land on the real last
      // page (total 0 has lastPage 1, so a stale ?page=5 returns to page 1).
      // The list just shrank, so the target's cached copy predates this
      // response: mark it stale so it refetches, and settle only on data at
      // least as new as this response (never on numbers it contradicts).
      if (pendingHere) void queryClient.invalidateQueries({ queryKey: queryKeyRef.current, refetchType: 'none' });
      redirect(lastPage, dataUpdatedAt);
      return;
    }
    if (!pendingHere || dataUpdatedAt < pending.minUpdatedAt) return;
    pendingSettleRef.current = null;
    setAnnounced({
      key: location.key,
      announcement:
        itemCount > 0
          ? { page, lastPage, from: offset + 1, to: offset + itemCount, total, totalIsLowerBound }
          : null,
    });
    onPageSettledRef.current?.();
  }, [
    data,
    dataUpdatedAt,
    isSuccess,
    isPlaceholderData,
    page,
    pageSize,
    offset,
    itemCount,
    total,
    totalIsLowerBound,
    lastPage,
    holdEmptyPage,
    location.key,
    replacePage,
    queryClient,
  ]);

  const pagerProps: PagedPagerProps = {
    page,
    lastPage,
    offset,
    itemCount,
    total,
    totalIsLowerBound,
    announcement,
  };

  return {
    /** The raw response of the page on screen, for fields beyond the slice. */
    data,
    items,
    total,
    totalIsLowerBound,
    offset,
    page,
    lastPage,
    isLoading: query.isLoading,
    isError: query.isError,
    isSuccess,
    isFetching: query.isFetching,
    isPlaceholderData,
    refetch: query.refetch,
    pagerProps,
  };
}
