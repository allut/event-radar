import { describe, it, expect } from 'vitest';
import {
  parseSnapshotHtml,
  validateSnapshotStructure,
  compareEventStaleness,
  assertEventJsonLd,
  assertWebsiteJsonLd,
  assertListJsonLd,
} from './seoValidation';
import { buildEventJsonLd, buildExploreItemListJsonLd, buildWebsiteJsonLd } from './structuredData';
import { buildSeoMeta } from '../hooks/useSeoMeta';
import { renderSnapshotHtml } from '../test/seoSnapshots';
import { makeEvent } from '../test/utils';
import { PRODUCTION_ORIGIN } from '../constants/seo';
import { SPONSORED_SLOT_ATTR } from '../_generated/sharedConstants';

describe('parseSnapshotHtml', () => {
  it('extracts title/canonical/hreflang/robots/jsonLd/price from a well-formed snapshot', () => {
    const event = makeEvent({
      title: 'Jazz Night',
      venue_name: 'Kultuurikatel',
      venue_address: 'Põhja pst 27a',
      price_min: 10,
      price_max: 15,
      currency: 'EUR',
      has_free_tier: false,
    });
    const meta = buildSeoMeta({
      title: 'Jazz Night – Kultuurikatel | Event Radar',
      locale: 'et',
      path: '/events/1',
      indexable: true,
    });
    const html = renderSnapshotHtml(
      meta,
      buildEventJsonLd(event),
      '<span data-testid="event-price" data-price-min="10" data-price-max="15" data-currency="EUR" data-has-free-tier="false">€10–€15</span>',
    );

    const parsed = parseSnapshotHtml(html);

    expect(parsed.title).toBe('Jazz Night – Kultuurikatel | Event Radar');
    expect(parsed.canonical).toBe(`${PRODUCTION_ORIGIN}/events/1`);
    expect(parsed.hreflangs.et).toBe(`${PRODUCTION_ORIGIN}/events/1`);
    expect(parsed.hreflangs.en).toBe(`${PRODUCTION_ORIGIN}/en/events/1`);
    expect(parsed.hreflangs.ru).toBe(`${PRODUCTION_ORIGIN}/ru/events/1`);
    expect(parsed.hreflangs['x-default']).toBe(`${PRODUCTION_ORIGIN}/events/1`);
    expect(parsed.robots).toBe('index, follow');
    expect(parsed.jsonLd).toHaveLength(1);
    expect((parsed.jsonLd[0] as { name: string }).name).toBe('Jazz Night');
    expect(parsed.price).toEqual({ min: 10, max: 15, currency: 'EUR', hasFreeTier: false });
  });

  it('marks an unparseable JSON-LD script as undefined rather than throwing', () => {
    const html = '<html><head><script type="application/ld+json">{not valid json</script></head><body></body></html>';
    const parsed = parseSnapshotHtml(html);
    expect(parsed.jsonLd).toEqual([undefined]);
  });

  it('returns a null price when no price marker is present', () => {
    const parsed = parseSnapshotHtml('<html><head></head><body></body></html>');
    expect(parsed.price).toBeNull();
  });
});

describe('assertEventJsonLd', () => {
  it('accepts a fully-populated builder output', () => {
    const event = makeEvent({ url: 'https://example.com/tickets', currency: 'EUR' });
    expect(assertEventJsonLd(buildEventJsonLd(event))).toEqual([]);
  });

  it('flags missing name/startDate', () => {
    const issues = assertEventJsonLd({ '@type': 'Event' });
    expect(issues).toContain('name is required');
    expect(issues).toContain('startDate must be a valid date string');
  });

  it('does not require location — an event with no venue data omits it by design (issue #46)', () => {
    const event = makeEvent({ venue_name: null, venue_address: null, lat: null, lng: null, url: null, currency: null });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd).not.toHaveProperty('location');
    expect(assertEventJsonLd(jsonLd)).toEqual([]);
  });

  it('flags a malformed location (present but with no name/address)', () => {
    const issues = assertEventJsonLd({
      '@type': 'Event',
      name: 'x',
      startDate: '2026-01-01T00:00:00Z',
      location: { '@type': 'Place' },
      image: 'https://example.com/img.jpg',
    });
    expect(issues).toContain('location must carry a name or an address');
  });

  it('does not require eventStatus/organizer (deliberately-omitted fields)', () => {
    const event = makeEvent({ url: null, currency: null });
    // No offers — image fallback still satisfies the image/offers recommendation.
    expect(assertEventJsonLd(buildEventJsonLd(event))).toEqual([]);
  });

  it('flags a malformed snapshot (deliberately broken JSON-LD fixture)', () => {
    const broken = { '@type': 'Event', name: '', startDate: 'not-a-date' };
    const issues = assertEventJsonLd(broken);
    expect(issues.length).toBeGreaterThan(0);
  });

  it('accepts an AggregateOffer with a valid price range (issue #236)', () => {
    const event = makeEvent({ price_min: 10, price_max: 15, currency: 'EUR' });
    expect(assertEventJsonLd(buildEventJsonLd(event))).toEqual([]);
  });

  it('accepts price_min: 0 (a free event) — numeric-truthiness rule', () => {
    const event = makeEvent({ price_min: 0, price_max: 5, currency: 'EUR' });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd.offers).toMatchObject({ '@type': 'AggregateOffer', lowPrice: 0, highPrice: 5 });
    expect(assertEventJsonLd(jsonLd)).toEqual([]);
  });

  it('flags offers.lowPrice > offers.highPrice', () => {
    const issues = assertEventJsonLd({
      '@type': 'Event',
      name: 'x',
      startDate: '2026-01-01T00:00:00Z',
      image: 'https://example.com/img.jpg',
      offers: { '@type': 'AggregateOffer', lowPrice: 20, highPrice: 10, priceCurrency: 'EUR' },
    });
    expect(issues).toContain('offers.lowPrice must be <= offers.highPrice');
  });

  it('flags a missing priceCurrency only when lowPrice is present', () => {
    const issues = assertEventJsonLd({
      '@type': 'Event',
      name: 'x',
      startDate: '2026-01-01T00:00:00Z',
      image: 'https://example.com/img.jpg',
      offers: { '@type': 'AggregateOffer', lowPrice: 10, highPrice: 10 },
    });
    expect(issues).toContain('offers.priceCurrency is required when lowPrice is present');
  });

  it('never newly fails an event that omits price', () => {
    const event = makeEvent({ price_min: null, url: 'https://example.com/tickets', currency: 'EUR' });
    expect(assertEventJsonLd(buildEventJsonLd(event))).toEqual([]);
  });
});

describe('assertWebsiteJsonLd', () => {
  it('accepts buildWebsiteJsonLd output', () => {
    expect(assertWebsiteJsonLd(buildWebsiteJsonLd('et'))).toEqual([]);
  });

  it('flags a non-object payload', () => {
    expect(assertWebsiteJsonLd(null)).toEqual(['jsonLd is missing or not an object']);
  });
});

describe('validateSnapshotStructure', () => {
  function validEventHtml(): string {
    const event = makeEvent({ title: 'Jazz Night' });
    const meta = buildSeoMeta({
      title: 'Jazz Night – Kultuurikatel | Event Radar',
      locale: 'et',
      path: '/events/1',
      indexable: true,
    });
    return renderSnapshotHtml(meta, buildEventJsonLd(event));
  }

  it('passes a well-formed event snapshot', () => {
    const parsed = parseSnapshotHtml(validEventHtml());
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues).toEqual([]);
  });

  it('flags a canonical that does not equal expectedCanonical (wrong-page capture)', () => {
    const parsed = parseSnapshotHtml(validEventHtml());
    const issues = validateSnapshotStructure(parsed, {
      kind: 'event',
      locale: 'et',
      originPrefix: PRODUCTION_ORIGIN,
      expectedCanonical: `${PRODUCTION_ORIGIN}/events/2`,
    });
    expect(issues.some((i) => i.includes('does not match expected'))).toBe(true);
  });

  it('passes when the canonical equals expectedCanonical', () => {
    const parsed = parseSnapshotHtml(validEventHtml());
    const issues = validateSnapshotStructure(parsed, {
      kind: 'event',
      locale: 'et',
      originPrefix: PRODUCTION_ORIGIN,
      expectedCanonical: `${PRODUCTION_ORIGIN}/events/1`,
    });
    expect(issues).toEqual([]);
  });

  it('ignores canonical identity when expectedCanonical is omitted', () => {
    const parsed = parseSnapshotHtml(validEventHtml());
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('does not match expected'))).toBe(false);
  });

  it('catches a default/missing title', () => {
    const parsed = parseSnapshotHtml('<html><head><title>Event Radar</title></head><body></body></html>');
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('app-shell default'))).toBe(true);
  });

  it('catches a missing canonical', () => {
    const meta = buildSeoMeta({ title: 'Event | Event Radar', locale: 'et', path: '/events/1' }); // indexable omitted -> noindex, no canonical
    const parsed = parseSnapshotHtml(renderSnapshotHtml(meta, buildEventJsonLd(makeEvent())));
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('canonical'))).toBe(true);
  });

  it('catches a missing hreflang alternate', () => {
    const parsed = parseSnapshotHtml(validEventHtml());
    delete parsed.hreflangs.ru;
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues).toContain('missing hreflang alternate for "ru"');
  });

  it('catches a missing icon link', () => {
    const html = validEventHtml().replace('<link rel="icon" href="/favicon.svg">', '');
    const parsed = parseSnapshotHtml(html);
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues).toContain('icon link is missing');
  });

  it('catches a data: URI icon href (the exact pre-fix defect)', () => {
    const html = validEventHtml().replace(
      '<link rel="icon" href="/favicon.svg">',
      '<link rel="icon" href="data:image/svg+xml,<svg></svg>">',
    );
    const parsed = parseSnapshotHtml(html);
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('data: URI'))).toBe(true);
  });

  it('catches deliberately malformed JSON-LD injected in a fixture', () => {
    const html = validEventHtml().replace(
      /<script type="application\/ld\+json">.*?<\/script>/s,
      '<script type="application/ld+json">{"@type":"Event"}</script>',
    );
    const parsed = parseSnapshotHtml(html);
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.startsWith('jsonLd:'))).toBe(true);
  });

  it('catches an unescaped "<" left in the JSON-LD body (OWASP audit #1)', () => {
    const html = validEventHtml().replace(
      /<script type="application\/ld\+json">.*?<\/script>/s,
      '<script type="application/ld+json">{"@type":"Event","name":"<b>x</b>"}</script>',
    );
    const parsed = parseSnapshotHtml(html);
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('unescaped "<"'))).toBe(true);
  });

  it('flags a "</script" breakout: the truncated JSON-LD body no longer parses', () => {
    const html = validEventHtml().replace(
      /<script type="application\/ld\+json">.*?<\/script>/s,
      '<script type="application/ld+json">{"@type":"Event","name":"</script><meta http-equiv="refresh" content="0"></script>',
    );
    const parsed = parseSnapshotHtml(html);
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.startsWith('jsonLd:'))).toBe(true);
  });

  it('does not flag a properly escaped "<" in event text', () => {
    const parsed = parseSnapshotHtml(validEventHtml());
    parsed.jsonLdRaw = ['{"name":"a\\u003c/script"}'];
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('unescaped "<"'))).toBe(false);
  });
});

describe("validateSnapshotStructure kind 'page'", () => {
  function faqHtml(jsonLd: object | null): string {
    const meta = buildSeoMeta({
      title: 'KKK | Event Radar',
      locale: 'et',
      path: '/faq',
      indexable: true,
    });
    return renderSnapshotHtml(meta, jsonLd);
  }

  it('passes a well-formed snapshot with zero JSON-LD scripts', () => {
    const parsed = parseSnapshotHtml(faqHtml(null));
    const issues = validateSnapshotStructure(parsed, {
      kind: 'page',
      locale: 'et',
      originPrefix: PRODUCTION_ORIGIN,
      expectedCanonical: `${PRODUCTION_ORIGIN}/faq`,
    });
    expect(issues).toEqual([]);
  });

  it('fails when the page carries a JSON-LD script', () => {
    const parsed = parseSnapshotHtml(faqHtml(buildWebsiteJsonLd('et')));
    const issues = validateSnapshotStructure(parsed, { kind: 'page', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues).toEqual(['expected no JSON-LD script, found 1']);
  });

  it('still runs the other structural checks', () => {
    const parsed = parseSnapshotHtml(faqHtml(null));
    parsed.robots = 'noindex';
    const issues = validateSnapshotStructure(parsed, { kind: 'page', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues).toEqual(['robots meta is "noindex", expected "index, follow"']);
  });
});

describe('validateSnapshotStructure Sponsored slot guard (issue #603)', () => {
  const events = [makeEvent({ id: 1, title: 'A' }), makeEvent({ id: 2, title: 'B' }), makeEvent({ id: 3, title: 'C' })];
  function listHtml(bodyHtml: string): string {
    const meta = buildSeoMeta({ title: 'Explore | Event Radar', locale: 'et', path: '/explore', indexable: true });
    return renderSnapshotHtml(meta, buildExploreItemListJsonLd(events, 'et'), bodyHtml);
  }
  const validate = (html: string) =>
    validateSnapshotStructure(parseSnapshotHtml(html), { kind: 'list', locale: 'et', originPrefix: PRODUCTION_ORIGIN });

  it('passes a list snapshot with no slot', () => {
    expect(validate(listHtml('<article>organic</article>'))).toEqual([]);
  });

  it('fails a list snapshot that contains the slot marker', () => {
    const issues = validate(listHtml(`<article ${SPONSORED_SLOT_ATTR}>ad</article>`));
    expect(issues.some((i) => i.includes('Sponsored slot'))).toBe(true);
  });
});

describe('compareEventStaleness', () => {
  function snapshotFor(event: ReturnType<typeof makeEvent>, price: { min: number | null; max: number | null; currency: string | null; hasFreeTier: boolean } | null) {
    const meta = buildSeoMeta({ title: 'x', locale: 'et', path: '/events/1', indexable: true });
    const priceHtml = price
      ? `<span data-testid="event-price" data-price-min="${price.min ?? ''}" data-price-max="${price.max ?? ''}" data-currency="${price.currency ?? ''}" data-has-free-tier="${price.hasFreeTier}"></span>`
      : '';
    return parseSnapshotHtml(renderSnapshotHtml(meta, buildEventJsonLd(event), priceHtml));
  }

  it('passes when the snapshot matches the live event exactly', () => {
    const event = makeEvent({ title: 'Jazz Night', venue_name: 'Kultuurikatel', price_min: 10, price_max: 15, currency: 'EUR', has_free_tier: false });
    const parsed = snapshotFor(event, { min: 10, max: 15, currency: 'EUR', hasFreeTier: false });
    expect(compareEventStaleness(parsed, event)).toEqual([]);
  });

  it('flags a stale title (deliberately mismatched fixture)', () => {
    const event = makeEvent({ title: 'Jazz Night' });
    const parsed = snapshotFor(event, null);
    const live = { ...event, title: 'Jazz Night (Rescheduled)' };
    const issues = compareEventStaleness(parsed, live);
    expect(issues.some((i) => i.startsWith('title is stale'))).toBe(true);
  });

  it('flags a stale venue', () => {
    const event = makeEvent({ venue_name: 'Old Venue', venue_address: null });
    const parsed = snapshotFor(event, null);
    const live = { ...event, venue_name: 'New Venue' };
    const issues = compareEventStaleness(parsed, live);
    expect(issues.some((i) => i.startsWith('venue name is stale'))).toBe(true);
  });

  it('flags a stale price (mocked live-API response with a changed price)', () => {
    const event = makeEvent({ price_min: 10, price_max: 15, currency: 'EUR', has_free_tier: false });
    const parsed = snapshotFor(event, { min: 10, max: 15, currency: 'EUR', hasFreeTier: false });
    const live = { ...event, price_max: 20 };
    const issues = compareEventStaleness(parsed, live);
    expect(issues.some((i) => i.startsWith('price_max is stale'))).toBe(true);
  });

  it('flags a price that appeared live but is missing from the snapshot', () => {
    const event = makeEvent({ price_min: null, price_max: null });
    const parsed = snapshotFor(event, null);
    const live = { ...event, price_min: 5, price_max: 5 };
    const issues = compareEventStaleness(parsed, live);
    expect(issues).toContain('price is stale: snapshot has no price, live API now has one');
  });

  it('flags a price that disappeared live (event went free/cancelled) but lingers in the snapshot', () => {
    const event = makeEvent({ price_min: 5, price_max: 5 });
    const parsed = snapshotFor(event, { min: 5, max: 5, currency: 'EUR', hasFreeTier: false });
    const live = { ...event, price_min: null, price_max: null };
    const issues = compareEventStaleness(parsed, live);
    expect(issues).toContain('price is stale: snapshot has a price, live API now has none');
  });
});

describe('assertListJsonLd', () => {
  function threeEvents() {
    return [makeEvent({ id: 1, title: 'A' }), makeEvent({ id: 2, title: 'B' }), makeEvent({ id: 3, title: 'C' })];
  }

  it('accepts buildExploreItemListJsonLd output for 3+ events', () => {
    const jsonLd = buildExploreItemListJsonLd(threeEvents(), 'et');
    expect(assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN })).toEqual([]);
  });

  it('flags @type mismatch', () => {
    const issues = assertListJsonLd({ '@type': 'Thing', itemListElement: [] }, { originPrefix: PRODUCTION_ORIGIN });
    expect(issues).toContain('@type must be "ItemList"');
  });

  it('requires itemListElement to be an array', () => {
    const issues = assertListJsonLd({ '@type': 'ItemList' }, { originPrefix: PRODUCTION_ORIGIN });
    expect(issues).toContain('itemListElement must be an array');
  });

  it('flags fewer than 3 items when no liveItemCount is supplied (defaults to the hard check)', () => {
    const jsonLd = buildExploreItemListJsonLd([makeEvent({ id: 1 })], 'et');
    const issues = assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('expected at least 3'))).toBe(true);
  });

  it('skips the >=3 check when liveItemCount proves the catalog is genuinely thin', () => {
    const jsonLd = buildExploreItemListJsonLd([makeEvent({ id: 1 })], 'et');
    const issues = assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN, liveItemCount: 1 });
    expect(issues.some((i) => i.includes('expected at least 3'))).toBe(false);
  });

  it('does not skip the >=3 check when liveItemCount shows a builder regression', () => {
    const jsonLd = buildExploreItemListJsonLd([makeEvent({ id: 1 })], 'et');
    const issues = assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN, liveItemCount: 10 });
    expect(issues.some((i) => i.includes('expected at least 3'))).toBe(true);
  });

  it('accepts a genuinely empty list', () => {
    const jsonLd = buildExploreItemListJsonLd([], 'et');
    const issues = assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN, liveItemCount: 0 });
    expect(issues).toEqual([]);
  });

  it('flags non-sequential/duplicate positions', () => {
    const jsonLd = buildExploreItemListJsonLd(threeEvents(), 'et') as unknown as { itemListElement: { position: number }[] };
    jsonLd.itemListElement[2].position = 2;
    const issues = assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('positions must be exactly'))).toBe(true);
  });

  it('flags a duplicate item.url across the list', () => {
    const jsonLd = buildExploreItemListJsonLd(threeEvents(), 'et') as unknown as {
      itemListElement: { item: { url: string } }[];
    };
    jsonLd.itemListElement[1].item.url = jsonLd.itemListElement[0].item.url;
    const issues = assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('is not unique across the list'))).toBe(true);
  });

  it('flags an item.url with no fragment allowed', () => {
    const jsonLd = buildExploreItemListJsonLd(threeEvents(), 'et') as unknown as {
      itemListElement: { item: { url: string } }[];
    };
    jsonLd.itemListElement[0].item.url += '#section';
    const issues = assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('must not contain a fragment'))).toBe(true);
  });

  it('flags an item.url that does not point at originPrefix', () => {
    const jsonLd = buildExploreItemListJsonLd(threeEvents(), 'et') as unknown as {
      itemListElement: { item: { url: string } }[];
    };
    jsonLd.itemListElement[0].item.url = 'https://evil.example.com/events/1';
    const issues = assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('does not point at'))).toBe(true);
  });

  it('requires item.image even for an event whose own assertEventJsonLd would accept offers-only', () => {
    const jsonLd = buildExploreItemListJsonLd(threeEvents(), 'et') as unknown as {
      itemListElement: { item: { image?: string } }[];
    };
    delete jsonLd.itemListElement[0].item.image;
    const issues = assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i === 'item[0]: image is required')).toBe(true);
  });

  it('prefixes a nested item failure with its index', () => {
    const jsonLd = buildExploreItemListJsonLd(threeEvents(), 'et') as unknown as {
      itemListElement: { item: { name?: string } }[];
    };
    delete jsonLd.itemListElement[1].item.name;
    const issues = assertListJsonLd(jsonLd, { originPrefix: PRODUCTION_ORIGIN });
    expect(issues).toContain('item[1]: name is required');
  });
});
