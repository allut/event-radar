import { useCallback, useSyncExternalStore } from 'react';

function fits(el: HTMLElement): boolean {
  // The element's own computed `top` is the sticky offset its CSS sets, so
  // the guard and the stylesheet can't disagree about it.
  const top = parseFloat(getComputedStyle(el).top) || 0;
  return el.offsetHeight + top <= window.innerHeight;
}

function getServerSnapshot(): boolean {
  return false;
}

/** Whether `el`, stuck at its CSS `top` offset, fits inside the viewport —
 * re-measured on element resize and window resize. EventDetail's wide-band
 * rail (#478) only goes `position: sticky` while this is true, so a tall
 * rail (long ET/RU title, venue, claim form) never clips below the fold. */
export function useFitsViewport(el: HTMLElement | null): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      window.addEventListener('resize', onChange);
      // jsdom (tests) has no ResizeObserver; window resize still covers it there.
      const observer = el && typeof ResizeObserver !== 'undefined' ? new ResizeObserver(onChange) : null;
      if (el) observer?.observe(el);
      return () => {
        window.removeEventListener('resize', onChange);
        observer?.disconnect();
      };
    },
    [el],
  );
  const getSnapshot = useCallback(() => (el ? fits(el) : false), [el]);
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
