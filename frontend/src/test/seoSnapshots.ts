import { buildSeoMeta } from '../hooks/useSeoMeta';
import { serializeJsonLd } from '../lib/jsonLd';
import { buildEventJsonLd, buildExploreItemListJsonLd, buildWebsiteJsonLd } from '../lib/structuredData';
import { makeEvent } from './utils';

/** Mirrors components/SeoTags/SeoTags.tsx's rendering (title/meta/link/ld+json
 * escaping) closely enough to exercise the SEO parsers against a realistic
 * snapshot, without pulling react-helmet-async/jsdom-render into a test file.
 * `jsonLd: null` omits the ld+json script; `assetTags` sits in the head after
 * the icon link, `extraBodyHtml` in the body. */
export function renderSnapshotHtml(
  meta: ReturnType<typeof buildSeoMeta>,
  jsonLd: object | null,
  extraBodyHtml = '',
  assetTags = '',
): string {
  const metaTags = meta.metaTags
    .map((tag) => `<meta ${tag.name ? `name="${tag.name}"` : `property="${tag.property}"`} content="${tag.content}">`)
    .join('\n');
  const links = meta.links
    .map((link) => `<link rel="${link.rel}" href="${link.href}"${link.hrefLang ? ` hreflang="${link.hrefLang}"` : ''}>`)
    .join('\n');
  const ldJson = jsonLd === null ? '' : `<script type="application/ld+json">${serializeJsonLd(jsonLd)}</script>`;
  return `<!doctype html><html lang="${meta.htmlLang}"><head><title>${meta.title}</title>${metaTags}${links}<link rel="icon" href="/favicon.svg">${assetTags}${ldJson}</head><body>${extraBodyHtml}</body></html>`;
}

export function renderLandingHtml(assetTags = ''): string {
  const meta = buildSeoMeta({ title: 'Mis toimub Tallinnas | Event Radar', locale: 'et', path: '/', indexable: true });
  return renderSnapshotHtml(meta, buildWebsiteJsonLd('et'), '', assetTags);
}

export function renderEventHtml(assetTags = '', eventId = 1): string {
  const event = makeEvent({ id: eventId, title: 'Jazz Night' });
  const meta = buildSeoMeta({
    title: 'Jazz Night – Kultuurikatel | Event Radar',
    locale: 'et',
    path: `/events/${eventId}`,
    indexable: true,
  });
  return renderSnapshotHtml(meta, buildEventJsonLd(event), '', assetTags);
}

export function renderExploreHtml(
  locale: string,
  events = [makeEvent({ id: 1 }), makeEvent({ id: 2 }), makeEvent({ id: 3 })],
): string {
  const meta = buildSeoMeta({ title: 'Explore | Event Radar', locale, path: '/explore', indexable: true });
  return renderSnapshotHtml(meta, buildExploreItemListJsonLd(events, locale));
}
