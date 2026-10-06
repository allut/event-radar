import { useMemo } from 'react';
import {
  CANONICAL_REL,
  LOCALE_ET,
  PRODUCTION_ORIGIN,
  ROBOTS_INDEX_FOLLOW,
  ROBOTS_NOINDEX,
  SEO_HREFLANG_CODES,
  SEO_XDEFAULT_CODE,
} from '../constants';
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
  /** Resolved route locale — matches useRouteLocale()/App.tsx's locale wrapper. */
  locale: string;
  /** Current pathname, bare or locale-prefixed (either is accepted — stripped internally). */
  path: string;
  /** Landing, Explore, /events/:id and /faq opt in; every other route defaults to noindex. */
  indexable?: boolean;
  /** og:description / meta description — only emitted when `indexable` is true. */
  description?: string;
  /** Absolute og:image URL — only emitted when `indexable` is true. */
  image?: string;
}

export interface SeoMetaResult {
  title: string;
  htmlLang: string;
  metaTags: SeoMetaTag[];
  links: SeoMetaLink[];
}

/** Pure builder behind useSeoMeta, kept separate from the hook so tests (and
 * the hook itself) can assert on plain tag/link data rather than
 * react-helmet-async's DOM side-effects — see docs/frontend.md. */
export function buildSeoMeta(input: SeoMetaInput): SeoMetaResult {
  const { title, locale, path, indexable = false, description, image } = input;
  const bare = stripLocalePrefix(path);

  const metaTags: SeoMetaTag[] = [
    { name: 'robots', content: indexable ? ROBOTS_INDEX_FOLLOW : ROBOTS_NOINDEX },
  ];
  const links: SeoMetaLink[] = [];

  if (indexable) {
    const canonicalUrl = canonicalUrlFor(bare, locale);
    links.push({ rel: CANONICAL_REL, href: canonicalUrl });

    for (const code of SEO_HREFLANG_CODES) {
      // x-default always points at the bare Estonian URL; every other code
      // (including 'et') resolves through localizedPath, which already
      // returns the bare path for Estonian.
      const href = code === SEO_XDEFAULT_CODE ? `${PRODUCTION_ORIGIN}${bare}` : `${PRODUCTION_ORIGIN}${localizedPath(bare, code)}`;
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
  const { title, locale, path, indexable, description, image } = input;
  return useMemo(
    () => buildSeoMeta({ title, locale, path, indexable, description, image }),
    [title, locale, path, indexable, description, image],
  );
}
