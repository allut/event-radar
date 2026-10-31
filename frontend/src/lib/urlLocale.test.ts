import { describe, it, expect } from 'vitest';
import { localeFromPath, localizedPath, localizedTo, stripLocalePrefix } from './urlLocale';

describe('stripLocalePrefix', () => {
  it('strips a recognized locale prefix', () => {
    expect(stripLocalePrefix('/en/settings')).toBe('/settings');
    expect(stripLocalePrefix('/ru/events/42')).toBe('/events/42');
  });

  it('strips a bare locale-prefixed root to "/"', () => {
    expect(stripLocalePrefix('/en')).toBe('/');
  });

  it('leaves a bare (Estonian) path unchanged', () => {
    expect(stripLocalePrefix('/settings')).toBe('/settings');
    expect(stripLocalePrefix('/')).toBe('/');
  });

  it('leaves an unrecognized segment unchanged (not a locale prefix)', () => {
    expect(stripLocalePrefix('/xx/settings')).toBe('/xx/settings');
  });
});

describe('localizedPath', () => {
  it('builds a prefixed path for a non-Estonian locale', () => {
    expect(localizedPath('/settings', 'en')).toBe('/en/settings');
    expect(localizedPath('/', 'ru')).toBe('/ru');
  });

  it('builds the bare path for Estonian', () => {
    expect(localizedPath('/settings', 'et')).toBe('/settings');
    expect(localizedPath('/en/settings', 'et')).toBe('/settings');
  });

  it('re-prefixes a path that already carries a different locale prefix', () => {
    expect(localizedPath('/en/settings', 'ru')).toBe('/ru/settings');
  });

  it('falls back to the bare path for an unrecognized target locale', () => {
    expect(localizedPath('/en/settings', 'xx')).toBe('/settings');
  });
});

describe('localeFromPath', () => {
  it('returns the leading locale segment when recognized', () => {
    expect(localeFromPath('/en/settings')).toBe('en');
    expect(localeFromPath('/ru')).toBe('ru');
  });

  it('returns null for a bare (Estonian) path', () => {
    expect(localeFromPath('/settings')).toBeNull();
    expect(localeFromPath('/')).toBeNull();
  });

  it('returns null for an unrecognized leading segment', () => {
    expect(localeFromPath('/xx/settings')).toBeNull();
  });
});

describe('localizedTo', () => {
  it('prefixes a bare target with no query/hash', () => {
    expect(localizedTo('/settings', 'ru')).toBe('/ru/settings');
  });

  it('preserves the query string', () => {
    expect(localizedTo('/explore?category=music', 'ru')).toBe('/ru/explore?category=music');
  });

  it('preserves the hash', () => {
    expect(localizedTo('/contact#form', 'en')).toBe('/en/contact#form');
  });

  it('preserves both query string and hash, in order', () => {
    expect(localizedTo('/explore?category=music#top', 'ru')).toBe('/ru/explore?category=music#top');
  });

  it('strips an existing prefix before re-prefixing', () => {
    expect(localizedTo('/en/settings?x=1', 'ru')).toBe('/ru/settings?x=1');
  });

  it('produces the bare path for Estonian, keeping query/hash', () => {
    expect(localizedTo('/en/explore?category=music', 'et')).toBe('/explore?category=music');
  });
});
