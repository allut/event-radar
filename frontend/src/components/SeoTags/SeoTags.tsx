import { Helmet } from 'react-helmet-async';
import type { SeoMetaResult } from '../../hooks/useSeoMeta';

/** Renders a useSeoMeta() result via react-helmet-async. Kept as a thin,
 * untested render shell — the tag/link data it renders is what
 * useSeoMeta/buildSeoMeta's own unit tests cover (see docs/frontend.md). */
export default function SeoTags({ meta }: { meta: SeoMetaResult }) {
  return (
    <Helmet htmlAttributes={{ lang: meta.htmlLang }}>
      <title>{meta.title}</title>
      {meta.metaTags.map((tag) => (
        <meta
          key={tag.name ?? tag.property}
          {...(tag.name ? { name: tag.name } : { property: tag.property })}
          content={tag.content}
        />
      ))}
      {meta.links.map((link) => (
        <link key={`${link.rel}-${link.hrefLang ?? link.href}`} rel={link.rel} href={link.href} {...(link.hrefLang ? { hrefLang: link.hrefLang } : {})} />
      ))}
    </Helmet>
  );
}
