import { useParams } from 'react-router-dom';
import { LOCALE_ET } from '../constants';
import { isValidLocale } from '../utils';

/** Resolves the current route's locale from the `:locale` URL segment that
 * App.tsx's locale-routing wrapper matches every route against. Absent or
 * unrecognized segments fall back to Estonian — the bare-path default per
 * the locale-routing spec (issue #47). */
export function useRouteLocale(): string {
  const { locale } = useParams<{ locale?: string }>();
  return isValidLocale(locale) ? locale : LOCALE_ET;
}
