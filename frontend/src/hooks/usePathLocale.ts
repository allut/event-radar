import { useLocation } from 'react-router-dom';
import { LOCALE_ET } from '../constants/core';
import { localeFromPath } from '../lib/urlLocale';

/** The current URL's locale: its `/en`/`/ru` prefix, else Estonian on a bare
 * path (or an unrecognized segment). The saved preference is deliberately
 * not consulted, so a page and the Footer under it can never disagree
 * (issue #497) — BareLocaleGate (App.tsx) redirects a bare path to the
 * saved non-Estonian prefix before this reads it, except on the `noRedirect`
 * SEO routes and the catch-all NotFound, which render Estonian when bare.
 *
 * Reads `useLocation().pathname`, not `useParams()`,
 * deliberately: `Footer` is mounted outside `<Routes>` (App.tsx) so
 * `useParams()` is permanently `{}` there, and tests rendering via
 * `renderWithProviders(ui)` with no `pathPattern` (TopBar/EventCard/Footer)
 * have no `<Routes>` either — `useLocation` works on every reachable path.
 * A locale switch navigates to the new prefix, so callers re-render with it. */
export function usePathLocale(): string {
  const { pathname } = useLocation();
  return localeFromPath(pathname) ?? LOCALE_ET;
}
