import { describe, it, expect } from 'vitest';
import { buildEventJsonLd, buildWebsiteJsonLd } from './structuredData';
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
});

describe('buildWebsiteJsonLd', () => {
  it('emits name/url/inLanguage only, for the bare Estonian URL', () => {
    const jsonLd = buildWebsiteJsonLd('et');
    expect(jsonLd).toEqual({
      '@context': 'https://schema.org',
      '@type': 'WebSite',
      name: "What's on Radar",
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
