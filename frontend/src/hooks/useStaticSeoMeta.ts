import { useLocation } from 'react-router-dom';
import { t } from '../i18n';
import { useSeoMeta, type SeoMetaResult } from './useSeoMeta';

/** Thin useSeoMeta wrapper for every route except Landing and /events/:id —
 * the two dynamic, indexable routes that build their own useSeoMeta input.
 * Every other route just needs `{pageTitle} | {brand}` and the default
 * noindex — this covers that in one call.
 *
 * `locale` is the caller's own already-resolved display locale (from
 * useLocaleMutation/getLocale/useState — whatever the page already uses to
 * render its body), not re-derived from useRouteLocale() here: several
 * routes (Login, AuthVerify, Onboarding, Unsubscribe, the organizer login/
 * verify pages, NotFound) resolve their locale via getLocale(), which
 * defaults to LOCALES[0] ('en') when nothing is stored — diverging from
 * useRouteLocale()'s bare-path default of Estonian. Deriving the SEO
 * <title>/<html lang> independently would silently mismatch the page's own
 * rendered language for a first-time visitor. */
export function useStaticSeoMeta(titleKey: string, locale: string): SeoMetaResult {
  const { pathname } = useLocation();
  const title = `${t(titleKey, locale)} | ${t('brand', locale)}`;
  return useSeoMeta({ title, locale, path: pathname });
}
