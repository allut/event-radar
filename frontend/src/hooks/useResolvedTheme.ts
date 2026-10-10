import { useSyncExternalStore } from 'react';
import { getResolvedTheme, subscribeTheme, type ResolvedTheme } from '../lib/theme';

/** Live resolved-theme subscription, mirroring useAuth(). Lets any
 * globally mounted chrome (PrefsMenu / PrefsRows) re-render when the effective
 * theme changes from a source other than its own state (a matchMedia
 * flip, another tab's write, an override expiring on load). */
export function useResolvedTheme(): ResolvedTheme {
  return useSyncExternalStore(subscribeTheme, getResolvedTheme, getResolvedTheme);
}
