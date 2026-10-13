import { useCallback, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { LIST_PARAMS_NAV_STATE, PAGE_QUERY_PARAM } from '../constants/api';

/** Parses the raw `?page` value. Only a plain integer ≥ 2 is a real page:
 * `0`, negatives, non-integers and an explicit `1` are all malformed and
 * normalize to page 1 (with the param dropped) — page 1 omits it. */
export function parsePageParam(raw: string | null): { page: number; malformed: boolean } {
  if (raw === null) return { page: 1, malformed: false };
  if (/^[1-9]\d*$/.test(raw)) {
    const n = Number(raw);
    if (n >= 2 && Number.isSafeInteger(n)) return { page: n, malformed: false };
  }
  return { page: 1, malformed: true };
}

/** True when a router location's `state` marks it as written by
 * setListParams — a filter/sort/search/tab change, not a page change. */
export function isListParamsNavigation(state: unknown): boolean {
  return typeof state === 'object' && state !== null && LIST_PARAMS_NAV_STATE in state;
}

export interface UsePageParamOptions {
  /** `{ name: defaultValue }` for the route's params: a param left at its
   * default is dropped from the URL by setListParams. A route whose own
   * serializer already omits defaults can skip this. */
  defaults?: Record<string, string>;
}

export type ListParamsUpdater = (params: URLSearchParams) => URLSearchParams;

/** URL state for a paged list (spec #551). Reads and normalizes `?page`
 * (a malformed value `replace`s to page 1 with the param dropped), and
 * returns `setListParams`, the single writer for every filter, sort, search
 * or tab param: it drops `page` and default-valued params, and lands as one
 * push. */
export function usePageParam({ defaults }: UsePageParamOptions = {}): {
  page: number;
  /** True while a malformed `?page` is being replaced; nothing should fetch. */
  malformed: boolean;
  setListParams: (updater: ListParamsUpdater) => void;
} {
  const [searchParams, setSearchParams] = useSearchParams();
  const { page, malformed } = parsePageParam(searchParams.get(PAGE_QUERY_PARAM));

  useEffect(() => {
    if (!malformed) return;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete(PAGE_QUERY_PARAM);
        return next;
      },
      { replace: true },
    );
  }, [malformed, setSearchParams]);

  const defaultsRef = useRef(defaults);
  useEffect(() => {
    defaultsRef.current = defaults;
  });

  const setListParams = useCallback(
    (updater: ListParamsUpdater) => {
      setSearchParams(
        (prev) => {
          const next = updater(new URLSearchParams(prev));
          next.delete(PAGE_QUERY_PARAM);
          for (const [name, value] of Object.entries(defaultsRef.current ?? {})) {
            if (next.get(name) === value) next.delete(name);
          }
          return next;
        },
        { state: { [LIST_PARAMS_NAV_STATE]: true } },
      );
    },
    [setSearchParams],
  );

  return { page, malformed, setListParams };
}
