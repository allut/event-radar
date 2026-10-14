import { useMemo } from 'react';
import { PAGE_QUERY_PARAM } from '../constants/api';
import { LOCALE_ET } from '../constants/core';
import {
  CANONICAL_REL,
  PRODUCTION_ORIGIN,
  ROBOTS_INDEX_FOLLOW,
  ROBOTS_NOINDEX,
  SEO_HREFLANG_CODES,
  SEO_XDEFAULT_CODE,
} from '../constants/seo';
import { canonicalUrlFor } from '../lib/urlLocale';
import { localizedPath, stripLocalePrefix } from '../utils';

export interface SeoMetaTag {
  name?: string;
  property?: string;
  content: string;
}

export interface SeoMetaLink {
  rel: string;
  href: string;
  hrefLang?: string;
}

export interface SeoMetaInput {
  /** Document <title>. */
  title: string;
  /** Resolved route locale — matches usePathLocale()/App.tsx's locale wrapper. */
  locale: string;
  /** Current pathname, bare or locale-prefixed (either is accepted — stripped internally). */
  path: string;
  /** Landing, Explore, /events/:id and /faq opt in; every other route defaults to noindex. */
  indexable?: boolean;
  /** og:description / meta description — only emitted when `indexable` is true. */
  description?: string;
  /** Absolute og:image URL — only emitted when `indexable` is true. */
  image?: string;
  /** A paged list's current page. Only a page >= 2 is self-canonical: it
   * appends `?page=N` to the canonical, every hreflang href and og:url. Page 1
   * and an omitted value keep the bare URL. A list whose view is filtered,
   * sorted or searched omits it, so every page canonicalises to page 1. */
  page?: number;
}

export interface SeoMetaResult {
  title: string;
  htmlLang: string;
  metaTags: SeoMetaTag[];
  links: SeoMetaLink[];
}

/** Pure builder behind useSeoMeta, kept separate from the hook so tests (and
 * the hook itself) can assert on plain tag/link data rather than
 * react-helmet-async's DOM side-effects — see docs/seo.md "Meta Tags". */
export function buildSeoMeta(input: SeoMetaInput): SeoMetaResult {
  const { title, locale, path, indexable = false, description, image, page } = input;
  const bare = stripLocalePrefix(path);
  const pageSuffix = page !== undefined && page >= 2 ? `?${PAGE_QUERY_PARAM}=${page}` : '';

  const metaTags: SeoMetaTag[] = [
    { name: 'robots', content: indexable ? ROBOTS_INDEX_FOLLOW : ROBOTS_NOINDEX },
  ];
  const links: SeoMetaLink[] = [];

  if (indexable) {
    const canonicalUrl = `${canonicalUrlFor(bare, locale)}${pageSuffix}`;
    links.push({ rel: CANONICAL_REL, href: canonicalUrl });

    for (const code of SEO_HREFLANG_CODES) {
      // x-default always points at the bare Estonian URL; every other code
      // (including 'et') resolves through localizedPath, which already
      // returns the bare path for Estonian.
      const href = code === SEO_XDEFAULT_CODE ? `${PRODUCTION_ORIGIN}${bare}${pageSuffix}` : `${PRODUCTION_ORIGIN}${localizedPath(bare, code)}${pageSuffix}`;
      links.push({ rel: 'alternate', href, hrefLang: code });
    }

    metaTags.push({ property: 'og:type', content: 'website' });
    metaTags.push({ property: 'og:title', content: title });
    metaTags.push({ property: 'og:url', content: canonicalUrl });
    if (description) {
      metaTags.push({ name: 'description', content: description });
      metaTags.push({ property: 'og:description', content: description });
    }
    if (image) {
      metaTags.push({ property: 'og:image', content: image });
    }
  }

  return { title, htmlLang: locale || LOCALE_ET, metaTags, links };
}

/** Shared per-route SEO hook (issue #48) — every route calls this (directly
 * or via useStaticSeoMeta) to declare its <title>, <html lang>, and default
 * `noindex`. Only Landing, Explore, /events/:id and /faq pass `indexable: true` to also get
 * OG tags, a self-referential canonical, and the three hreflang alternates +
 * x-default. Render the result via <SeoTags meta={...} /> (components/SeoTags). */
export function useSeoMeta(input: SeoMetaInput): SeoMetaResult {
  const { title, locale, path, indexable, description, image, page } = input;
  return useMemo(
    () => buildSeoMeta({ title, locale, path, indexable, description, image, page }),
    [title, locale, path, indexable, description, image, page],
  );
}
