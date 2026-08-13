import type { Event as SchemaEvent, Offer, Place, WebSite as SchemaWebSite, WithContext } from 'schema-dts';
import type { EventData } from '../components/EventCard';
import { OG_FALLBACK_IMAGE_PATH, PRODUCTION_ORIGIN } from '../constants';
import { t } from '../i18n';
import { localizedPath, safeUrl } from '../utils';

/** JSON-LD builder for /events/:id (issue #49). Field mapping and omissions
 * (never `organizer`, never `offers.availability`) are documented on the
 * issue and in docs/frontend.md — don't add either without a data-model
 * change to back them with real data. */
export function buildEventJsonLd(event: EventData): WithContext<SchemaEvent> {
  const location: Place | undefined =
    event.venue_name || event.venue_address
      ? {
          '@type': 'Place',
          ...(event.venue_name ? { name: event.venue_name } : {}),
          ...(event.venue_address ? { address: event.venue_address } : {}),
          ...(event.lat != null && event.lng != null
            ? { geo: { '@type': 'GeoCoordinates', latitude: event.lat, longitude: event.lng } }
            : {}),
        }
      : undefined;

  const offerUrl = safeUrl(event.url);
  const offers: Offer | undefined =
    offerUrl || event.currency
      ? {
          '@type': 'Offer',
          ...(offerUrl ? { url: offerUrl } : {}),
          ...(event.currency ? { priceCurrency: event.currency } : {}),
        }
      : undefined;

  return {
    '@context': 'https://schema.org',
    '@type': 'Event',
    name: event.title,
    startDate: event.starts_at,
    ...(event.ends_at ? { endDate: event.ends_at } : {}),
    ...(location ? { location } : {}),
    // Same fallback asset/URL as og:image (useSeoMeta) — the two must never
    // pick a different fallback independently.
    image: safeUrl(event.image_url) ?? `${PRODUCTION_ORIGIN}${OG_FALLBACK_IMAGE_PATH}`,
    ...(offers ? { offers } : {}),
  };
}

/** Minimal WebSite node for Landing (issue #49) — name/url/inLanguage only,
 * no SearchAction/Organization/ItemList (see issue #46 for why each is out
 * of scope). */
export function buildWebsiteJsonLd(locale: string): WithContext<SchemaWebSite> {
  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: t('brand', locale),
    url: `${PRODUCTION_ORIGIN}${localizedPath('/', locale)}`,
    inLanguage: locale,
  };
}
