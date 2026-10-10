import { useLocation } from 'react-router-dom';
import { t } from '../i18n';
import { titleWithBrand } from '../utils';
import { useSeoMeta, type SeoMetaResult } from './useSeoMeta';

/** Thin useSeoMeta wrapper for every route except Landing and /events/:id —
 * the two dynamic, indexable routes that build their own useSeoMeta input.
 * Every other route just needs `{pageTitle} | {brand}` and the default
 * noindex — this covers that in one call.
 *
 * `locale` is the caller's own already-resolved display locale (from
 * useLocaleMutation/useLocalLocale/usePathLocale — whatever the page already
 * uses to render its body), not re-derived from the URL here: the organizer
 * portal and Onboarding (useLocalLocale) and the non-public useLocaleMutation
 * pages fall back to the *stored* preference on a bare path, not Estonian.
 * Deriving the SEO <title>/<html lang> independently would silently mismatch
 * the page's own rendered language. */
export function useStaticSeoMeta(titleKey: string, locale: string): SeoMetaResult {
  const { pathname } = useLocation();
  const title = titleWithBrand(t(titleKey, locale), locale);
  return useSeoMeta({ title, locale, path: pathname });
}
