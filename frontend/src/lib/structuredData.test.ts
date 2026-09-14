import { describe, it, expect } from 'vitest';
import { buildEventJsonLd, buildExploreItemListJsonLd, buildWebsiteJsonLd } from './structuredData';
import { makeEvent } from '../test/utils';
import { OG_FALLBACK_IMAGE_PATH, PRODUCTION_ORIGIN } from '../constants';

describe('buildEventJsonLd', () => {
  it('maps the documented fields for a fully-populated event', () => {
    const event = makeEvent({
      title: 'Jazz Night',
      starts_at: '2026-08-20T18:00:00Z',
      ends_at: '2026-08-20T21:00:00Z',
      venue_name: 'Kultuurikatel',
      venue_address: 'Põhja pst 27a, Tallinn',
      lat: 59.4444,
      lng: 24.7444,
      url: 'https://example.com/tickets/1',
      image_url: 'https://example.com/image.jpg',
      currency: 'EUR',
    });

    const jsonLd = buildEventJsonLd(event);

    expect(jsonLd).toEqual({
      '@context': 'https://schema.org',
      '@type': 'Event',
      name: 'Jazz Night',
      startDate: '2026-08-20T18:00:00Z',
      endDate: '2026-08-20T21:00:00Z',
      location: {
        '@type': 'Place',
        name: 'Kultuurikatel',
        address: 'Põhja pst 27a, Tallinn',
        geo: { '@type': 'GeoCoordinates', latitude: 59.4444, longitude: 24.7444 },
      },
      image: 'https://example.com/image.jpg',
      offers: {
        '@type': 'Offer',
        url: 'https://example.com/tickets/1',
        priceCurrency: 'EUR',
      },
    });
  });

  it('never emits organizer or offers.availability', () => {
    const event = makeEvent({ url: 'https://example.com/tickets/1', currency: 'EUR' });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd).not.toHaveProperty('organizer');
    expect(jsonLd.offers).not.toHaveProperty('availability');
  });

  it('falls back to the shared OG fallback image when image_url is null', () => {
    const event = makeEvent({ image_url: null });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd.image).toBe(`${PRODUCTION_ORIGIN}${OG_FALLBACK_IMAGE_PATH}`);
  });

  it('omits location entirely when venue_name and venue_address are both null', () => {
    const event = makeEvent({ venue_name: null, venue_address: null, lat: null, lng: null });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd).not.toHaveProperty('location');
  });

  it('omits geo when lat/lng are null but keeps venue name/address', () => {
    const event = makeEvent({ venue_name: 'Venue', venue_address: null, lat: null, lng: null });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd.location).toEqual({ '@type': 'Place', name: 'Venue' });
  });

  it('omits endDate when ends_at is null', () => {
    const event = makeEvent({ ends_at: null });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd).not.toHaveProperty('endDate');
  });

  it('omits offers entirely when there is no url and no currency', () => {
    const event = makeEvent({ url: null, currency: null });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd).not.toHaveProperty('offers');
  });

  it('drops an unsafe event URL from offers.url rather than emitting it', () => {
    const event = makeEvent({ url: 'javascript:alert(1)', currency: 'EUR' });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd.offers).toEqual({ '@type': 'Offer', priceCurrency: 'EUR' });
  });

  it('emits an AggregateOffer with lowPrice/highPrice/priceCurrency when price_min is set (issue #236)', () => {
    const event = makeEvent({ price_min: 10, price_max: 20, currency: 'EUR', url: 'https://example.com/tickets' });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd.offers).toEqual({
      '@type': 'AggregateOffer',
      lowPrice: 10,
      highPrice: 20,
      priceCurrency: 'EUR',
      url: 'https://example.com/tickets',
    });
  });

  it('emits lowPrice: 0 for a free event rather than omitting price (numeric-truthiness rule)', () => {
    const event = makeEvent({ price_min: 0, price_max: 0, currency: 'EUR' });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd.offers).toMatchObject({ '@type': 'AggregateOffer', lowPrice: 0, highPrice: 0 });
  });

  it('defaults priceCurrency to EUR for a free event with no currency (production shape that broke the #236 prerender gate)', () => {
    const event = makeEvent({ price_min: 0, price_max: 0, currency: null });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd.offers).toMatchObject({ '@type': 'AggregateOffer', lowPrice: 0, highPrice: 0, priceCurrency: 'EUR' });
  });

  it('defaults priceCurrency to EUR for a paid event with no currency', () => {
    const event = makeEvent({ price_min: 10, price_max: null, currency: null });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd.offers).toMatchObject({ '@type': 'AggregateOffer', lowPrice: 10, highPrice: 10, priceCurrency: 'EUR' });
  });

  it('falls back highPrice to price_min when price_max is null (a single-price event)', () => {
    const event = makeEvent({ price_min: 12, price_max: null, currency: 'EUR' });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd.offers).toMatchObject({ lowPrice: 12, highPrice: 12 });
  });

  it('omits price fields entirely when price_min is null, same as today', () => {
    const event = makeEvent({ price_min: null, url: 'https://example.com/tickets', currency: 'EUR' });
    const jsonLd = buildEventJsonLd(event);
    expect(jsonLd.offers).toEqual({ '@type': 'Offer', url: 'https://example.com/tickets', priceCurrency: 'EUR' });
  });
});

describe('buildExploreItemListJsonLd', () => {
  it('builds one ListItem per event, 1-based position matching render order', () => {
    const events = [makeEvent({ id: 1, title: 'A' }), makeEvent({ id: 2, title: 'B' })];
    const jsonLd = buildExploreItemListJsonLd(events, 'et');

    expect(jsonLd['@type']).toBe('ItemList');
    expect(jsonLd.itemListElement).toHaveLength(2);
    const [first, second] = jsonLd.itemListElement as unknown as { '@type': string; position: number; item: { name: string; url: string } }[];
    expect(first).toMatchObject({ '@type': 'ListItem', position: 1 });
    expect(first.item.name).toBe('A');
    expect(second).toMatchObject({ '@type': 'ListItem', position: 2 });
    expect(second.item.name).toBe('B');
  });

  it('sets item.url to the locale-matched canonical detail URL, distinct from offers.url', () => {
    const events = [makeEvent({ id: 42, url: 'https://ticketvendor.example.com/42' })];
    const jsonLd = buildExploreItemListJsonLd(events, 'en');
    const [entry] = jsonLd.itemListElement as unknown as { item: { url: string; offers?: { url?: string } } }[];

    expect(entry.item.url).toBe(`${PRODUCTION_ORIGIN}/en/events/42`);
    expect(entry.item.offers?.url).toBe('https://ticketvendor.example.com/42');
  });

  it('resolves the bare Estonian detail URL for locale "et"', () => {
    const jsonLd = buildExploreItemListJsonLd([makeEvent({ id: 7 })], 'et');
    const [entry] = jsonLd.itemListElement as unknown as { item: { url: string } }[];
    expect(entry.item.url).toBe(`${PRODUCTION_ORIGIN}/events/7`);
  });

  it('emits the full buildEventJsonLd payload per item, not a hand-picked subset (issue #224 governs over #232)', () => {
    const event = makeEvent({ price_min: 10, price_max: 15, currency: 'EUR', venue_name: 'Venue' });
    const jsonLd = buildExploreItemListJsonLd([event], 'et');
    const [entry] = jsonLd.itemListElement as unknown as { item: Record<string, unknown> }[];

    expect(entry.item).toMatchObject({
      '@type': 'Event',
      name: event.title,
      location: { '@type': 'Place', name: 'Venue' },
      offers: { '@type': 'AggregateOffer', lowPrice: 10, highPrice: 15, priceCurrency: 'EUR' },
    });
  });

  it('builds an empty ItemList for zero events — a legitimate, crawlable state', () => {
    const jsonLd = buildExploreItemListJsonLd([], 'et');
    expect(jsonLd.itemListElement).toEqual([]);
  });

  it('never emits numberOfItems or itemListOrder', () => {
    const jsonLd = buildExploreItemListJsonLd([makeEvent()], 'et');
    expect(jsonLd).not.toHaveProperty('numberOfItems');
    expect(jsonLd).not.toHaveProperty('itemListOrder');
  });
});

describe('buildWebsiteJsonLd', () => {
  it('emits name/url/inLanguage only, for the bare Estonian URL', () => {
    const jsonLd = buildWebsiteJsonLd('et');
    expect(jsonLd).toEqual({
      '@context': 'https://schema.org',
      '@type': 'WebSite',
      name: 'Event Radar',
      url: `${PRODUCTION_ORIGIN}/`,
      inLanguage: 'et',
    });
  });

  it('resolves the locale-prefixed canonical URL for en/ru', () => {
    const jsonLd = buildWebsiteJsonLd('en');
    expect(jsonLd.url).toBe(`${PRODUCTION_ORIGIN}/en`);
    expect(jsonLd.inLanguage).toBe('en');
  });
});
