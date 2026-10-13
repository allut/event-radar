import { useCallback, useRef, type RefObject } from 'react';

/** The consumer/organizer page-settled pattern (spec #551), passed to
 * usePagedQuery as `onPageSettled`. Once a new page has rendered it
 * instant-scrolls (never smooth) so the results heading sits just below
 * the sticky top bar, then focuses the heading with `preventScroll`.
 *
 * The caller's part of the pattern:
 * - the heading takes `resultsHeadingRef` and `tabIndex={-1}`, and its class
 *   composes `settleTarget` from components/shared/PageSettle.module.css
 *   (the `scroll-margin-top` that clears the top bar, read here);
 * - the results container sets `aria-busy={isPlaceholderData}`, so it is
 *   busy while the previous page shows as placeholder data. */
export function usePageSettledFocus<T extends HTMLElement = HTMLHeadingElement>(): {
  resultsHeadingRef: RefObject<T>;
  onPageSettled: () => void;
} {
  const resultsHeadingRef = useRef<T>(null);
  const onPageSettled = useCallback(() => {
    const heading = resultsHeadingRef.current;
    if (!heading) return;
    const margin = parseFloat(getComputedStyle(heading).scrollMarginTop) || 0;
    const top = heading.getBoundingClientRect().top + window.scrollY - margin;
    window.scrollTo({ top: Math.max(0, top), behavior: 'instant' });
    heading.focus({ preventScroll: true });
  }, []);
  return { resultsHeadingRef, onPageSettled };
}
