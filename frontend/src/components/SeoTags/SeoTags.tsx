import { Helmet } from 'react-helmet-async';
import type { SeoMetaResult } from '../../hooks/useSeoMeta';

/** Renders a useSeoMeta() result (plus an optional schema.org JSON-LD object,
 * built by src/lib/structuredData.ts's builder functions — issue #49) via
 * react-helmet-async. Kept as a thin, untested render shell — the tag/link/
 * JSON-LD data it renders is what useSeoMeta/buildSeoMeta's and the
 * structured-data builders' own unit tests cover (see docs/frontend.md). */
export default function SeoTags({ meta, jsonLd }: { meta: SeoMetaResult; jsonLd?: object }) {
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
      {jsonLd && (
        // react-helmet-async assigns a <script> child string as raw innerHTML
        // (not HTML-escaped) — an unescaped "</script" inside event-sourced
        // text (title/venue) would otherwise break out of the tag.
        <script type="application/ld+json">{JSON.stringify(jsonLd).replace(/</g, '\\u003c')}</script>
      )}
    </Helmet>
  );
}
