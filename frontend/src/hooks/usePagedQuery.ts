import { useCallback, useEffect, useRef, useState } from 'react';
import { keepPreviousData, useQuery, type QueryKey } from '@tanstack/react-query';
import { useLocation, useNavigationType, useSearchParams } from 'react-router-dom';
import { PAGINATION_MAX_OFFSET } from '../_generated/sharedConstants';
import { PAGE_QUERY_PARAM } from '../constants/api';
import type { PagerAnnouncement, PagerProps } from '../components/Pager';
import { isListParamsNavigation, usePageParam } from './usePageParam';

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
  /** Runs once the real data for a new page has rendered, only after a push
   * (a pager link) or POP (back/forward) — never on first mount, a silent
   * `replace`, or a setListParams filter change. */
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
    placeholderData: keepPreviousData,
    enabled: enabled && !malformed && !beyondCeiling,
  });
  const { data, isSuccess, isPlaceholderData } = query;

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

  const [announcement, setAnnouncement] = useState<PagerAnnouncement | null>(null);
  const onPageSettledRef = useRef(onPageSettled);
  useEffect(() => {
    onPageSettledRef.current = onPageSettled;
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
  // is already cached (back to a fresh page) settles in the same commit.
  const previousPageRef = useRef(page);
  const pendingSettleRef = useRef<number | null>(null);
  useEffect(() => {
    if (previousPageRef.current === page) return;
    previousPageRef.current = page;
    const counts =
      navigationType === 'POP' ||
      (navigationType === 'PUSH' && !isListParamsNavigation(location.state));
    pendingSettleRef.current = counts ? page : null;
    setAnnouncement(null);
  }, [page, navigationType, location.state]);

  // A stale link past the offset ceiling: land on the deepest reachable page.
  useEffect(() => {
    if (!beyondCeiling) return;
    pendingSettleRef.current = null;
    replacePage(maxPage);
  }, [beyondCeiling, maxPage, replacePage]);

  useEffect(() => {
    if (!isSuccess || isPlaceholderData || data === undefined) return;
    const requestedOffset = (page - 1) * pageSize;
    if (offset !== requestedOffset) {
      // Server-placed offset (e.g. the Admin Reports locate): sync silently.
      pendingSettleRef.current = null;
      replacePage(Math.floor(offset / pageSize) + 1);
      return;
    }
    if (itemCount === 0 && total > 0 && !holdEmptyPage && page !== lastPage) {
      // Past the end, or a refetch emptied this page: land on the real last page.
      pendingSettleRef.current = null;
      replacePage(lastPage);
      return;
    }
    if (pendingSettleRef.current !== page) return;
    pendingSettleRef.current = null;
    setAnnouncement(
      itemCount > 0
        ? { page, lastPage, from: offset + 1, to: offset + itemCount, total, totalIsLowerBound }
        : null,
    );
    onPageSettledRef.current?.();
  }, [
    data,
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
    replacePage,
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
