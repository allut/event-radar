import { describe, it, expect } from 'vitest';
import {
  parseSnapshotHtml,
  validateSnapshotStructure,
  compareEventStaleness,
  assertEventJsonLd,
  assertWebsiteJsonLd,
} from './seoValidation';
import { buildEventJsonLd, buildWebsiteJsonLd } from './structuredData';
import { buildSeoMeta } from '../hooks/useSeoMeta';
import { makeEvent } from '../test/utils';
import { PRODUCTION_ORIGIN } from '../constants';

/** Mirrors components/SeoTags/SeoTags.tsx's rendering (title/meta/link/
 * ld+json escaping) closely enough to exercise parseSnapshotHtml against a
 * realistic snapshot, without pulling react-helmet-async/jsdom-render into
 * this test file. */
function renderSnapshotHtml(
  meta: ReturnType<typeof buildSeoMeta>,
  jsonLd: object,
  extraBodyHtml = '',
): string {
  const metaTags = meta.metaTags
    .map((tag) => `<meta ${tag.name ? `name="${tag.name}"` : `property="${tag.property}"`} content="${tag.content}">`)
    .join('\n');
  const links = meta.links
    .map((link) => `<link rel="${link.rel}" href="${link.href}"${link.hrefLang ? ` hreflang="${link.hrefLang}"` : ''}>`)
    .join('\n');
  return `<!doctype html><html lang="${meta.htmlLang}"><head><title>${meta.title}</title>${metaTags}${links}<link rel="icon" href="/favicon.svg"><script type="application/ld+json">${JSON.stringify(jsonLd).replace(/</g, '\\u003c')}</script></head><body>${extraBodyHtml}</body></html>`;
}

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
      title: 'Jazz Night – Kultuurikatel | What\'s on Radar',
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

    expect(parsed.title).toBe('Jazz Night – Kultuurikatel | What\'s on Radar');
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
      title: 'Jazz Night – Kultuurikatel | What\'s on Radar',
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

  it('catches a default/missing title', () => {
    const parsed = parseSnapshotHtml('<html><head><title>What\'s on Radar</title></head><body></body></html>');
    const issues = validateSnapshotStructure(parsed, { kind: 'event', locale: 'et', originPrefix: PRODUCTION_ORIGIN });
    expect(issues.some((i) => i.includes('app-shell default'))).toBe(true);
  });

  it('catches a missing canonical', () => {
    const meta = buildSeoMeta({ title: 'Event | What\'s on Radar', locale: 'et', path: '/events/1' }); // indexable omitted -> noindex, no canonical
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
