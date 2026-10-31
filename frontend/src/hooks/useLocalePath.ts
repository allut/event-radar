import { useCallback } from 'react';
import { localizedTo } from '../lib/urlLocale';
import { usePathLocale } from './usePathLocale';

/** Locale-prefixes an internal `to` target against the *current URL's* locale
 * (`usePathLocale` — Estonian on a bare path) — the app-wide helper every
 * `<Link to>`/`navigate()` call site should route `to` through so a click
 * doesn't drop the visitor's current locale (issue #47 follow-up). */
export function useLocalePath(): (to: string) => string {
  const locale = usePathLocale();
  return useCallback((to: string) => localizedTo(to, locale), [locale]);
}
