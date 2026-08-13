import { describe, it, expect } from 'vitest';
import { buildSeoMeta } from './useSeoMeta';
import { PRODUCTION_ORIGIN } from '../constants';

describe('buildSeoMeta', () => {
  it('defaults to noindex with no OG/canonical/hreflang for a non-indexable route', () => {
    const meta = buildSeoMeta({ title: 'Settings | What\'s on Radar', locale: 'et', path: '/settings' });

    expect(meta.title).toBe('Settings | What\'s on Radar');
    expect(meta.htmlLang).toBe('et');
    expect(meta.metaTags).toEqual([{ name: 'robots', content: 'noindex' }]);
    expect(meta.links).toEqual([]);
  });

  it('resolves htmlLang per the resolved route locale, not the bare Estonian default', () => {
    const meta = buildSeoMeta({ title: 'Explore | What\'s on Radar', locale: 'ru', path: '/ru/explore' });
    expect(meta.htmlLang).toBe('ru');
    expect(meta.metaTags).toEqual([{ name: 'robots', content: 'noindex' }]);
  });

  it('emits index/follow, OG tags, a self-referential canonical, and en/et/ru + x-default hreflang for an indexable Estonian (bare) route', () => {
    const meta = buildSeoMeta({
      title: 'Landing title',
      locale: 'et',
      path: '/',
      indexable: true,
      description: 'Landing description',
      image: `${PRODUCTION_ORIGIN}/og-fallback.png`,
    });

    expect(meta.metaTags).toEqual(
      expect.arrayContaining([
        { name: 'robots', content: 'index, follow' },
        { property: 'og:type', content: 'website' },
        { property: 'og:title', content: 'Landing title' },
        { property: 'og:url', content: `${PRODUCTION_ORIGIN}/` },
        { name: 'description', content: 'Landing description' },
        { property: 'og:description', content: 'Landing description' },
        { property: 'og:image', content: `${PRODUCTION_ORIGIN}/og-fallback.png` },
      ]),
    );

    expect(meta.links).toContainEqual({ rel: 'canonical', href: `${PRODUCTION_ORIGIN}/` });
    // en/ru get a prefix, et/x-default resolve to the bare URL.
    expect(meta.links).toContainEqual({ rel: 'alternate', href: `${PRODUCTION_ORIGIN}/en`, hrefLang: 'en' });
    expect(meta.links).toContainEqual({ rel: 'alternate', href: `${PRODUCTION_ORIGIN}/`, hrefLang: 'et' });
    expect(meta.links).toContainEqual({ rel: 'alternate', href: `${PRODUCTION_ORIGIN}/ru`, hrefLang: 'ru' });
    expect(meta.links).toContainEqual({ rel: 'alternate', href: `${PRODUCTION_ORIGIN}/`, hrefLang: 'x-default' });
  });

  it('builds a self-referential canonical and hreflang set for a non-Estonian locale-prefixed indexable route', () => {
    const meta = buildSeoMeta({
      title: 'Event title',
      locale: 'en',
      path: '/en/events/42',
      indexable: true,
    });

    expect(meta.links).toContainEqual({ rel: 'canonical', href: `${PRODUCTION_ORIGIN}/en/events/42` });
    expect(meta.links).toContainEqual({ rel: 'alternate', href: `${PRODUCTION_ORIGIN}/events/42`, hrefLang: 'et' });
    expect(meta.links).toContainEqual({ rel: 'alternate', href: `${PRODUCTION_ORIGIN}/en/events/42`, hrefLang: 'en' });
    expect(meta.links).toContainEqual({ rel: 'alternate', href: `${PRODUCTION_ORIGIN}/ru/events/42`, hrefLang: 'ru' });
    expect(meta.links).toContainEqual({ rel: 'alternate', href: `${PRODUCTION_ORIGIN}/events/42`, hrefLang: 'x-default' });
  });

  it('omits description/og:image meta tags when neither is provided', () => {
    const meta = buildSeoMeta({ title: 'Event title', locale: 'et', path: '/events/1', indexable: true });
    const properties = meta.metaTags.map((tag) => tag.property ?? tag.name);
    expect(properties).not.toContain('og:description');
    expect(properties).not.toContain('og:image');
    expect(properties).not.toContain('description');
  });

  it('includes og:image pointing at the fallback asset when an event has no image_url', () => {
    const meta = buildSeoMeta({
      title: 'Event title',
      locale: 'et',
      path: '/events/1',
      indexable: true,
      image: `${PRODUCTION_ORIGIN}/og-fallback.png`,
    });
    expect(meta.metaTags).toContainEqual({ property: 'og:image', content: `${PRODUCTION_ORIGIN}/og-fallback.png` });
  });
});
