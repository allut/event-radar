import { useCallback, useEffect, useRef } from 'react';

/** Returns a stable `schedule(fn, delayMs)` that runs `fn` after a delay and
 * cancels any still-pending timer on unmount — so a post-verify redirect can't
 * fire (and yank the user back) after they've already navigated elsewhere. */
export function useDelayedAction(): (fn: () => void, delayMs: number) => void {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current !== null) clearTimeout(timer.current);
  }, []);

  return useCallback((fn, delayMs) => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(fn, delayMs);
  }, []);
}
