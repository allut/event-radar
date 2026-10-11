import { useSyncExternalStore } from 'react';
import { REDUCED_MOTION_QUERY } from '../constants/theme';

function subscribe(callback: () => void): () => void {
  const mql = window.matchMedia(REDUCED_MOTION_QUERY);
  mql.addEventListener('change', callback);
  return () => mql.removeEventListener('change', callback);
}

function getSnapshot(): boolean {
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

function getServerSnapshot(): boolean {
  return false;
}

/** Live prefers-reduced-motion subscription — re-renders if the OS setting
 * changes mid-session, unlike a mount-time-only matchMedia() check. Used by
 * Landing's ticker (wayfinder #186), which must render a single non-duplicated
 * static row under reduced motion rather than just killing the CSS animation
 * (freezing the duplicated-content marquee mid-loop would leave two visibly
 * overlapping copies). */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
