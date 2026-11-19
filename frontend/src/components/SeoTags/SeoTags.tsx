import { memo, useMemo } from 'react';
import { Helmet } from 'react-helmet-async';
import { JSONLD_SCRIPT_TYPE } from '../../constants/seo';
import type { SeoMetaResult } from '../../hooks/useSeoMeta';
import { serializeJsonLd } from '../../lib/jsonLd';

/** Renders a useSeoMeta() result (plus an optional schema.org JSON-LD object,
 * built by src/lib/structuredData.ts's builder functions — issue #49) via
 * react-helmet-async. Kept as a thin, untested render shell — the tag/link/
 * JSON-LD data it renders is what useSeoMeta/buildSeoMeta's and the
 * structured-data builders' own unit tests cover.
 *
 * memo'd + the JSON-LD serialization is useMemo'd: callers like Explore
 * already memoize `jsonLd` itself, but without memo here every keystroke in
 * unrelated route state (e.g. the search box) re-ran JSON.stringify over the
 * full payload (Big-O audit H3). */
function SeoTags({ meta, jsonLd }: { meta: SeoMetaResult; jsonLd?: object }) {
  const jsonLdScript = useMemo(
    () => (jsonLd ? serializeJsonLd(jsonLd) : undefined),
    [jsonLd],
  );
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
      {jsonLdScript && (
        // react-helmet-async assigns a <script> child string as raw innerHTML
        // (not HTML-escaped) — an unescaped "</script" inside event-sourced
        // text (title/venue) would otherwise break out of the tag.
        <script type={JSONLD_SCRIPT_TYPE}>{jsonLdScript}</script>
      )}
    </Helmet>
  );
}

export default memo(SeoTags);
