import { useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { LOCALE_ET } from '../constants';
import { localeFromPath, localizedTo } from '../utils';

/** Locale-prefixes an internal `to` target against the *current URL's* locale
 * segment (falling back to Estonian on a bare path) — the app-wide helper
 * every `<Link to>`/`navigate()` call site should route `to` through so a
 * click doesn't drop the visitor's current locale (issue #47 follow-up).
 *
 * Reads `useLocation().pathname`, not `useParams`/`useRouteLocale`,
 * deliberately: `Footer` is mounted outside `<Routes>` (App.tsx) so
 * `useParams()` is permanently `{}` there, and tests rendering via
 * `renderWithProviders(ui)` with no `pathPattern` (TopBar/EventCard/Footer)
 * have no `<Routes>` either — `useLocation` works on every reachable path. */
export function useLocalePath(): (to: string) => string {
  const location = useLocation();
  return useCallback(
    (to: string) => localizedTo(to, localeFromPath(location.pathname) ?? LOCALE_ET),
    [location.pathname],
  );
}
