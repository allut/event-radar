import { useSyncExternalStore } from 'react';
import { getThemePreference, subscribeTheme, type ThemePreference } from '../lib/theme';

/** Live theme-preference subscription, mirroring useLocale(). Lets any
 * globally mounted chrome (ThemeSelector) re-render when the stored
 * preference changes from a source other than its own state (a matchMedia
 * flip, another tab's write). */
export function useThemePreference(): ThemePreference {
  return useSyncExternalStore(subscribeTheme, getThemePreference, getThemePreference);
}
