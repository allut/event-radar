import { parseHTML } from 'linkedom';
import type { EventData } from '../components/EventCard';
// .js extensions required: this module is also imported (transitively) by
// functions/api/seo-audit.ts, which Cloudflare Pages runs as unbundled ESM.
import { t } from '../i18n.js';
import {
  CANONICAL_LINK_SELECTOR,
  EVENT_PRICE_SELECTOR,
  ICON_LINK_SELECTOR,
  JSONLD_SCRIPT_SELECTOR,
  PRICE_DATA_ATTR,
  ROBOTS_INDEX_FOLLOW,
  SEO_HREFLANG_CODES,
  SEO_RICH_ITEM_LIST_MIN,
} from '../constants.js';

/** In-build validation gate for the prerender pipeline (issue #53) — pure
 * functions only (no filesystem/network access), so the same logic parses
 * and validates a snapshot whether it came from a local dist/ file (the
 * in-build gate, scripts/prerender.ts) or a fetch() against production (the
 * live-audit ticket, issue #54, which reuses this module rather than
 * reimplementing it). Uses `jsdom` directly (not ambient DOM globals) so it
 * behaves identically under plain `tsx` script execution, vitest, and (issue
 * #54's live audit) a Cloudflare Workers runtime — `linkedom` rather than
 * `jsdom` specifically because jsdom needs real Node internals (`fs`, `vm`)
 * that aren't available there, while linkedom is a pure-JS HTML parser. */

export interface ParsedSnapshot {
  title: string | null;
  canonical: string | null;
  /** hreflang code -> href, from every <link rel="alternate" hreflang> tag. */
  hreflangs: Record<string, string>;
  robots: string | null;
  /** href of the first <link rel="icon">, or null if none is present — a
   * `data:` URI here is the exact defect Google's site-icon crawlability
   * requirement forbids (a crawlable URL is required). */
  iconHref: string | null;
  /** Parsed contents of every <script type="application/ld+json">; `undefined`
   * entries mark a script whose body failed to JSON.parse. */
  jsonLd: (unknown | undefined)[];
  /** Raw price fields off the event-detail price marker (see EventDetail.tsx),
   * present only when the page actually rendered a price. */
  price: EventPriceSnapshot | null;
}

export interface EventPriceSnapshot {
  min: number | null;
  max: number | null;
  currency: string | null;
  hasFreeTier: boolean;
}

export function parseSnapshotHtml(html: string): ParsedSnapshot {
  const { document } = parseHTML(html);

  const title = document.querySelector('title')?.textContent?.trim() ?? null;
  const canonical = document.querySelector(CANONICAL_LINK_SELECTOR)?.getAttribute('href') ?? null;
  const robots = document.querySelector('meta[name="robots"]')?.getAttribute('content') ?? null;
  const iconHref = document.querySelector(ICON_LINK_SELECTOR)?.getAttribute('href') ?? null;

  const hreflangs: Record<string, string> = {};
  document.querySelectorAll('link[rel="alternate"][hreflang]').forEach((el) => {
    const code = el.getAttribute('hreflang');
    const href = el.getAttribute('href');
    if (code && href) hreflangs[code] = href;
  });

  const jsonLd: (unknown | undefined)[] = [];
  document.querySelectorAll(JSONLD_SCRIPT_SELECTOR).forEach((el) => {
    try {
      jsonLd.push(JSON.parse(el.textContent ?? ''));
    } catch {
      jsonLd.push(undefined);
    }
  });

  const priceEl = document.querySelector(EVENT_PRICE_SELECTOR);
  const rawMin = priceEl?.getAttribute(PRICE_DATA_ATTR.min) ?? null;
  const rawMax = priceEl?.getAttribute(PRICE_DATA_ATTR.max) ?? null;
  const price: EventPriceSnapshot | null = priceEl
    ? {
        min: rawMin !== null && rawMin !== '' ? Number(rawMin) : null,
        max: rawMax !== null && rawMax !== '' ? Number(rawMax) : null,
        currency: priceEl.getAttribute(PRICE_DATA_ATTR.currency) || null,
        hasFreeTier: priceEl.getAttribute(PRICE_DATA_ATTR.hasFreeTier) === 'true',
      }
    : null;

  return { title, canonical, hreflangs, robots, iconHref, jsonLd, price };
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
}

/** Runtime assertion against Google's documented required Event fields
 * (`name`, `startDate` — `location` is also documented as required, but see
 * below) plus its "at least one of `image`/`offers`" recommendation —
 * `image` is always present via the OG-fallback asset (structuredData.ts),
 * so this only fires if the builder itself regresses. `eventStatus`/
 * `organizer`/`offers.availability` are deliberately never emitted (issue
 * #46's out-of-scope decisions, since none is backed by real data) and are
 * not checked here — their absence is not a failure. */
export function assertEventJsonLd(jsonLd: unknown): string[] {
  const issues: string[] = [];
  const obj = asRecord(jsonLd);
  if (!obj) return ['jsonLd is missing or not an object'];

  if (obj['@type'] !== 'Event') issues.push('@type must be "Event"');
  if (!isNonEmptyString(obj.name)) issues.push('name is required');
  if (!isNonEmptyString(obj.startDate) || Number.isNaN(Date.parse(obj.startDate))) {
    issues.push('startDate must be a valid date string');
  }

  // Google lists `location` as required for Event rich results, but
  // `buildEventJsonLd` (structuredData.ts) deliberately omits it when an
  // event's venue_name/venue_address are both null — a state the data model
  // allows (Event.venue_name is a nullable column) and issue #46 accepts as
  // meaning that event just isn't rich-result eligible. Failing the build
  // over an event that legitimately has no venue data would block every
  // deploy on a data-completeness gap, not a bug — so only the *shape* of
  // `location`, when present, is checked here.
  const location = asRecord(obj.location);
  if (location && !isNonEmptyString(location.name) && !isNonEmptyString(location.address)) {
    issues.push('location must carry a name or an address');
  }

  const hasImage = isNonEmptyString(obj.image);
  const hasOffers = asRecord(obj.offers) !== null;
  if (!hasImage && !hasOffers) issues.push('at least one of image/offers is required');

  // Narrow structural check on offers.lowPrice/highPrice/priceCurrency
  // (AggregateOffer, issue #236) — fires only when lowPrice is present, so
  // an event that omits price (price_min === null) never newly fails here.
  const offers = asRecord(obj.offers);
  if (offers && offers.lowPrice !== undefined) {
    if (typeof offers.lowPrice !== 'number') issues.push('offers.lowPrice must be a number');
    if (typeof offers.highPrice !== 'number') issues.push('offers.highPrice must be a number');
    if (
      typeof offers.lowPrice === 'number' &&
      typeof offers.highPrice === 'number' &&
      offers.lowPrice > offers.highPrice
    ) {
      issues.push('offers.lowPrice must be <= offers.highPrice');
    }
    if (!isNonEmptyString(offers.priceCurrency)) issues.push('offers.priceCurrency is required when lowPrice is present');
  }

  return issues;
}

/** Runtime assertion for the /explore page's `ItemList` node (issue #236) —
 * checked against the same structural discipline as `assertEventJsonLd`,
 * plus list-specific shape (position sequencing, per-item url uniqueness).
 * `liveItemCount`, when passed, is the actual published-event count behind
 * the page's own query at validation time (mirrors `compareEventStaleness`'s
 * live re-fetch, though this is a count-only check, not a full staleness
 * diff — /explore is exempt from that, see prerender.ts) — it's what lets a
 * genuinely thin calendar (fewer than 3 events exist) skip the >=3 check
 * without hardcoding a minimum that would also swallow a real builder
 * regression (an `itemListElement` that's short despite there being enough
 * live events to fill it). When omitted (e.g. the live audit, which doesn't
 * re-query /explore), the >=3 check is skipped entirely — best-effort,
 * matching this module's other live-audit-only omissions. */
export function assertListJsonLd(jsonLd: unknown, options: { originPrefix: string; liveItemCount?: number }): string[] {
  const issues: string[] = [];
  const obj = asRecord(jsonLd);
  if (!obj) return ['jsonLd is missing or not an object'];

  if (obj['@type'] !== 'ItemList') issues.push('@type must be "ItemList"');

  const rawItems = obj.itemListElement;
  if (!Array.isArray(rawItems)) {
    return [...issues, 'itemListElement must be an array'];
  }

  if (
    rawItems.length < SEO_RICH_ITEM_LIST_MIN &&
    (options.liveItemCount === undefined || options.liveItemCount >= SEO_RICH_ITEM_LIST_MIN)
  ) {
    issues.push(
      `itemListElement has only ${rawItems.length} entr${rawItems.length === 1 ? 'y' : 'ies'}, expected at least ${SEO_RICH_ITEM_LIST_MIN}`,
    );
  }

  const seenUrls = new Set<string>();
  const positions: number[] = [];
  rawItems.forEach((raw, i) => {
    const entry = asRecord(raw);
    if (!entry) {
      issues.push(`item[${i}]: entry is not an object`);
      return;
    }
    if (entry['@type'] !== 'ListItem') issues.push(`item[${i}]: @type must be "ListItem"`);
    if (typeof entry.position === 'number' && Number.isInteger(entry.position)) {
      positions.push(entry.position);
    } else {
      issues.push(`item[${i}]: position must be an integer`);
    }

    const item = asRecord(entry.item);
    if (!item) {
      issues.push(`item[${i}]: item is missing or not an object`);
      return;
    }
    issues.push(...assertEventJsonLd(item).map((issue) => `item[${i}]: ${issue}`));

    const url = isNonEmptyString(item.url) ? item.url : null;
    if (!url) {
      issues.push(`item[${i}]: url is required`);
    } else {
      if (!url.startsWith(options.originPrefix)) {
        issues.push(`item[${i}]: url "${url}" does not point at ${options.originPrefix}`);
      }
      if (url.includes('#')) issues.push(`item[${i}]: url must not contain a fragment`);
      if (seenUrls.has(url)) issues.push(`item[${i}]: url "${url}" is not unique across the list`);
      seenUrls.add(url);
    }

    if (!isNonEmptyString(item.image)) issues.push(`item[${i}]: image is required`);
  });

  const expectedPositions = Array.from({ length: rawItems.length }, (_, i) => i + 1);
  const sortedPositions = [...positions].sort((a, b) => a - b);
  if (
    positions.length !== rawItems.length ||
    !expectedPositions.every((p, i) => sortedPositions[i] === p)
  ) {
    issues.push(`positions must be exactly 1..${rawItems.length} with no gaps or repeats`);
  }

  return issues;
}

/** Runtime assertion for Landing's minimal WebSite node (structuredData.ts's
 * `buildWebsiteJsonLd` — name/url/inLanguage only, by design). */
export function assertWebsiteJsonLd(jsonLd: unknown): string[] {
  const issues: string[] = [];
  const obj = asRecord(jsonLd);
  if (!obj) return ['jsonLd is missing or not an object'];

  if (obj['@type'] !== 'WebSite') issues.push('@type must be "WebSite"');
  if (!isNonEmptyString(obj.name)) issues.push('name is required');
  if (!isNonEmptyString(obj.url)) issues.push('url is required');
  if (!isNonEmptyString(obj.inLanguage)) issues.push('inLanguage is required');

  return issues;
}

export interface StructuralValidationOptions {
  kind: 'event' | 'website' | 'list';
  locale: string;
  /** PRODUCTION_ORIGIN — canonical/hreflang hrefs must be absolute URLs on it. */
  originPrefix: string;
  /** `kind: 'list'` only — see assertListJsonLd's doc comment. */
  liveItemCount?: number;
}

/** Structural-correctness half of the gate (issue #53): valid JSON-LD per the
 * field/omission policy, a non-default title, a canonical URL, and the three
 * hreflang alternates (+ x-default) — everything `useSeoMeta`/`SeoTags` is
 * supposed to emit for an indexable route. */
export function validateSnapshotStructure(
  parsed: ParsedSnapshot,
  { kind, locale, originPrefix, liveItemCount }: StructuralValidationOptions,
): string[] {
  const issues: string[] = [];
  const shellDefaultTitle = t('brand', locale);

  if (!isNonEmptyString(parsed.title)) {
    issues.push('title is missing');
  } else if (parsed.title.trim() === shellDefaultTitle) {
    issues.push(`title is the unrendered app-shell default ("${shellDefaultTitle}")`);
  }

  if (!parsed.canonical) {
    issues.push('canonical link is missing');
  } else if (!parsed.canonical.startsWith(originPrefix)) {
    issues.push(`canonical link "${parsed.canonical}" does not point at ${originPrefix}`);
  }

  for (const code of SEO_HREFLANG_CODES) {
    if (!parsed.hreflangs[code]) issues.push(`missing hreflang alternate for "${code}"`);
  }

  if (parsed.robots !== ROBOTS_INDEX_FOLLOW) {
    issues.push(`robots meta is "${parsed.robots ?? 'missing'}", expected "${ROBOTS_INDEX_FOLLOW}"`);
  }

  if (!parsed.iconHref) {
    issues.push('icon link is missing');
  } else if (parsed.iconHref.startsWith('data:')) {
    issues.push('icon link is a data: URI, not a crawlable URL — Google cannot fetch a site icon from it');
  }

  if (parsed.jsonLd.length !== 1) {
    issues.push(`expected exactly one JSON-LD script, found ${parsed.jsonLd.length}`);
  } else {
    const jsonLdIssues =
      kind === 'event'
        ? assertEventJsonLd(parsed.jsonLd[0])
        : kind === 'list'
          ? assertListJsonLd(parsed.jsonLd[0], { originPrefix, liveItemCount })
          : assertWebsiteJsonLd(parsed.jsonLd[0]);
    issues.push(...jsonLdIssues.map((issue) => `jsonLd: ${issue}`));
  }

  return issues;
}

type LiveEventFields = Pick<
  EventData,
  'title' | 'venue_name' | 'venue_address' | 'price_min' | 'price_max' | 'currency' | 'has_free_tier'
>;

/** Non-staleness half of the gate (issue #53): the snapshot's title/venue
 * (read off its own JSON-LD — `buildEventJsonLd` maps `name`/`location`
 * straight off `event.title`/`venue_name`/`venue_address`, so they're an
 * exact mirror) and price (read off the `data-price-*` marker left by
 * EventDetail.tsx, since price isn't part of the JSON-LD payload — issue
 * #46 defers `AggregateOffer`) must match what the live API returns right
 * now for the same event. `formatPrice` (frontend/src/utils.ts) renders a
 * price exactly when `price_min` is non-null — see its implementation —
 * so that's the presence signal used here, without needing to import it
 * (utils.ts pulls in `dompurify`, which requires a DOM global `formatPrice`
 * doesn't otherwise need, and this module must also run under plain Node). */
export function compareEventStaleness(parsed: ParsedSnapshot, live: LiveEventFields): string[] {
  const issues: string[] = [];
  const jsonLd = asRecord(parsed.jsonLd[0]);

  const snapshotTitle = jsonLd && typeof jsonLd.name === 'string' ? jsonLd.name : null;
  if (snapshotTitle !== live.title) {
    issues.push(`title is stale: snapshot has ${JSON.stringify(snapshotTitle)}, live API returns ${JSON.stringify(live.title)}`);
  }

  const location = jsonLd ? asRecord(jsonLd.location) : null;
  const snapshotVenueName = location && typeof location.name === 'string' ? location.name : null;
  const snapshotVenueAddress = location && typeof location.address === 'string' ? location.address : null;
  if (snapshotVenueName !== (live.venue_name ?? null)) {
    issues.push(
      `venue name is stale: snapshot has ${JSON.stringify(snapshotVenueName)}, live API returns ${JSON.stringify(live.venue_name)}`,
    );
  }
  if (snapshotVenueAddress !== (live.venue_address ?? null)) {
    issues.push(
      `venue address is stale: snapshot has ${JSON.stringify(snapshotVenueAddress)}, live API returns ${JSON.stringify(live.venue_address)}`,
    );
  }

  const liveHasPrice = live.price_min !== null;
  if (!parsed.price && liveHasPrice) {
    issues.push('price is stale: snapshot has no price, live API now has one');
  } else if (parsed.price && !liveHasPrice) {
    issues.push('price is stale: snapshot has a price, live API now has none');
  } else if (parsed.price && liveHasPrice) {
    if (parsed.price.min !== live.price_min) {
      issues.push(`price_min is stale: snapshot ${parsed.price.min}, live ${live.price_min}`);
    }
    if (parsed.price.max !== live.price_max) {
      issues.push(`price_max is stale: snapshot ${parsed.price.max}, live ${live.price_max}`);
    }
    if (parsed.price.currency !== (live.currency ?? null)) {
      issues.push(`currency is stale: snapshot ${JSON.stringify(parsed.price.currency)}, live ${JSON.stringify(live.currency)}`);
    }
    if (parsed.price.hasFreeTier !== live.has_free_tier) {
      issues.push(`has_free_tier is stale: snapshot ${parsed.price.hasFreeTier}, live ${live.has_free_tier}`);
    }
  }

  return issues;
}
