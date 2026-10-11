import type {
  AggregateOffer,
  Event as SchemaEvent,
  ItemList,
  Offer,
  Place,
  WebSite as SchemaWebSite,
  WithContext,
} from 'schema-dts';
import type { EventData } from '../components/EventCard';
import { DEFAULT_CURRENCY } from '../_generated/sharedConstants';
import { ROUTES } from '../constants/routes';
import { OG_FALLBACK_IMAGE_PATH, PRODUCTION_ORIGIN, SCHEMA_ORG_CONTEXT } from '../constants/seo';
import { t } from '../i18n';
import { localizedPath, safeUrl } from '../utils';

/** JSON-LD builder for /events/:id (issue #49). Field mapping and omissions
 * (never `organizer`, never `offers.availability`) are documented on the
 * issue and in docs/seo.md "Structured Data" — don't add either without a
 * data-model change to back them with real data. */
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
  // Numeric truthiness (CLAUDE.md) — gate on `!== null`, not on `price_min`
  // being falsy, so a free event's price_min: 0 still emits lowPrice: 0
  // rather than silently falling through to the plain-Offer branch (issue
  // #236). highPrice falls back to price_min when price_max is null (a
  // single-price event, per formatPrice's own price_min/price_max contract,
  // utils.ts) — AggregateOffer requires lowPrice <= highPrice, which a null
  // highPrice can't satisfy. seoValidation's assertEventJsonLd requires
  // priceCurrency whenever lowPrice is present, so once a price is emitted
  // here priceCurrency must be too — a free event legitimately loses its
  // currency at ingest (backend/app/ingestion/pricing.py), so default to
  // DEFAULT_CURRENCY rather than drop the field (issue that broke the
  // #236 prerender gate: item[15].offers.priceCurrency missing).
  const offers: Offer | AggregateOffer | undefined =
    event.price_min !== null
      ? {
          '@type': 'AggregateOffer',
          lowPrice: event.price_min,
          highPrice: event.price_max ?? event.price_min,
          priceCurrency: event.currency || DEFAULT_CURRENCY,
          ...(offerUrl ? { url: offerUrl } : {}),
        }
      : offerUrl || event.currency
        ? {
            '@type': 'Offer',
            ...(offerUrl ? { url: offerUrl } : {}),
            ...(event.currency ? { priceCurrency: event.currency } : {}),
          }
        : undefined;

  return {
    '@context': SCHEMA_ORG_CONTEXT,
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

/** ItemList JSON-LD for the public /explore page (issue #236) — one
 * `ListItem` per rendered card, `position` matching render order (also the
 * value explore_card_click's `position` analytics param uses, EventCard.tsx).
 * Per #224 (governs over #232's since-superseded "minimal item" note — see
 * issue #236's own note on the contradiction): each `item` is the *full*
 * `buildEventJsonLd` payload, not a hand-picked subset — one field-mapping
 * policy in the codebase rather than two — plus a top-level `url` on that
 * item pointing at our own locale-matched detail page (never emitted by
 * buildEventJsonLd itself, and distinct from its `offers.url`, the external
 * ticket vendor link). `numberOfItems`/`itemListOrder` are deliberately
 * omitted — see
 * docs/seo.md "Structured Data". */
export function buildExploreItemListJsonLd(events: EventData[], locale: string): WithContext<ItemList> {
  return {
    '@context': SCHEMA_ORG_CONTEXT,
    '@type': 'ItemList',
    itemListElement: events.map((event, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      item: {
        ...buildEventJsonLd(event),
        url: `${PRODUCTION_ORIGIN}${localizedPath(ROUTES.eventDetail(event.id), locale)}`,
      },
    })),
  };
}

/** Minimal WebSite node for Landing (issue #49) — name/url/inLanguage only,
 * no SearchAction/Organization/ItemList (see issue #46 for why each is out
 * of scope). */
export function buildWebsiteJsonLd(locale: string): WithContext<SchemaWebSite> {
  return {
    '@context': SCHEMA_ORG_CONTEXT,
    '@type': 'WebSite',
    name: t('brand', locale),
    url: `${PRODUCTION_ORIGIN}${localizedPath(ROUTES.home, locale)}`,
    inLanguage: locale,
  };
}
