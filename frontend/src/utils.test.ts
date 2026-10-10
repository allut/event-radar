import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { cx, safeUrl, sanitizeHtml, formatPrice, categoryGradient, formatHourMinute, formatEventTime, tallinnToday, formatEventShortDate, makeActiveClassMap, trackExternalClick, datePresetRange, parseExploreFilters, exploreFiltersToSearchParams, buildExploreApiQuery, nextKeysetParam, activeFacetCount, isFullSet, shouldFlipPopover, maskAnalyticsUrl, DEFAULT_EXPLORE_FILTERS, type ExploreFilters, monthGridDays, weekdayHeaders, splitDateTimeValue, joinDateTimeValue, parseTypedDate, formatPickerValue, formatMonthYearLabel, toDisplayDateTime, fromDisplayDateTime, buildMapsUrl, isValidLocale, stripLocalePrefix, localizedPath, localeFromPath, localizedTo, truncateForMeta, cardAnimationDelayMs, parseISODateLocal, formatDateRangeShort, localeLabel, localizedFieldLabel, localizedTriplet, weekdayOffset, toggleCapped } from './utils';
import { t } from './i18n';
import { FALLBACK_GRADIENT, CATEGORIES, GOOGLE_MAPS_SEARCH_URL } from './constants';

vi.mock('./api/client', () => ({
  api: {
    post: vi.fn().mockResolvedValue(undefined),
  },
}));

import { api } from './api/client';

describe('cx', () => {
  it('joins truthy classes', () => {
    expect(cx('a', 'b', 'c')).toBe('a b c');
  });

  it('filters falsy values', () => {
    expect(cx('a', false, null, undefined, 'b')).toBe('a b');
  });

  it('returns empty string when all falsy', () => {
    expect(cx(false, null, undefined)).toBe('');
  });
});

describe('maskAnalyticsUrl', () => {
  it('masks a numeric event id', () => {
    expect(maskAnalyticsUrl('/events/42')).toBe('/events/[id]');
  });

  it('strips the query string (may carry the /auth/verify magic-link token)', () => {
    expect(maskAnalyticsUrl('/auth/verify?token=secret')).toBe('/auth/verify');
  });

  it('strips the query string on a masked event path', () => {
    expect(maskAnalyticsUrl('/events/42?x=1')).toBe('/events/[id]');
  });

  it('strips the hash', () => {
    expect(maskAnalyticsUrl('/events/42#section')).toBe('/events/[id]');
  });

  it('strips a free-text search query', () => {
    expect(maskAnalyticsUrl('/explore?q=jazz+night')).toBe('/explore');
  });

  it('leaves non-event paths unchanged', () => {
    expect(maskAnalyticsUrl('/explore')).toBe('/explore');
  });

  it('does not mask a non-numeric id segment', () => {
    expect(maskAnalyticsUrl('/events/abc')).toBe('/events/abc');
  });

  it('masks an organizer edit-form event id', () => {
    expect(maskAnalyticsUrl('/organizer/events/7/edit')).toBe('/organizer/events/[id]/edit');
  });

  it('masks a locale-prefixed event id, keeping the prefix so locales still group separately', () => {
    expect(maskAnalyticsUrl('/en/events/42')).toBe('/en/events/[id]');
    expect(maskAnalyticsUrl('/ru/events/42?x=1')).toBe('/ru/events/[id]');
  });

  it('masks a locale-prefixed organizer edit-form event id', () => {
    expect(maskAnalyticsUrl('/en/organizer/events/7/edit')).toBe('/en/organizer/events/[id]/edit');
  });
});

describe('isValidLocale', () => {
  it('accepts every configured locale code', () => {
    expect(isValidLocale('en')).toBe(true);
    expect(isValidLocale('et')).toBe(true);
    expect(isValidLocale('ru')).toBe(true);
  });

  it('rejects an unrecognized or missing code', () => {
    expect(isValidLocale('xx')).toBe(false);
    expect(isValidLocale(undefined)).toBe(false);
  });
});

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

describe('safeUrl', () => {
  it('passes http URLs', () => {
    expect(safeUrl('http://example.com')).toBe('http://example.com');
  });

  it('passes https URLs', () => {
    expect(safeUrl('https://example.com/path?q=1')).toBe('https://example.com/path?q=1');
  });

  it('rejects javascript: scheme', () => {
    expect(safeUrl('javascript:alert(1)')).toBeNull();
  });

  it('rejects data: scheme', () => {
    expect(safeUrl('data:text/html,<h1>x</h1>')).toBeNull();
  });

  it('returns null for malformed URL', () => {
    expect(safeUrl('not a url')).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(safeUrl('')).toBeNull();
  });

  it('returns null for null input', () => {
    expect(safeUrl(null)).toBeNull();
  });

  it('returns null for undefined input', () => {
    expect(safeUrl(undefined)).toBeNull();
  });
});

describe('sanitizeHtml', () => {
  it('allows safe tags', () => {
    const result = sanitizeHtml('<p>Hello <strong>world</strong></p>');
    expect(result).toContain('<p>');
    expect(result).toContain('<strong>');
  });

  it('strips script tags', () => {
    const result = sanitizeHtml('<p>ok</p><script>alert(1)</script>');
    expect(result).not.toContain('<script>');
    expect(result).toContain('<p>ok</p>');
  });

  it('strips onerror attributes', () => {
    const result = sanitizeHtml('<img src="x" onerror="alert(1)">');
    expect(result).not.toContain('onerror');
  });

  it('allows href on anchor tags', () => {
    const result = sanitizeHtml('<a href="https://example.com">link</a>');
    expect(result).toContain('href');
  });

  it('strips disallowed attributes', () => {
    const result = sanitizeHtml('<p class="foo" style="color:red">text</p>');
    expect(result).not.toContain('class=');
    expect(result).not.toContain('style=');
  });

  it('forces rel="noopener noreferrer" and target="_blank" on anchors', () => {
    const result = sanitizeHtml('<a href="https://example.com">link</a>');
    expect(result).toContain('rel="noopener noreferrer"');
    expect(result).toContain('target="_blank"');
  });

  it('overrides an attacker-supplied rel/target on anchors', () => {
    const result = sanitizeHtml(
      '<a href="https://evil.com" rel="opener" target="_self">link</a>'
    );
    expect(result).toContain('rel="noopener noreferrer"');
    expect(result).toContain('target="_blank"');
    expect(result).not.toContain('rel="opener"');
  });
});

describe('formatPrice', () => {
  it('returns null when both null', () => {
    expect(formatPrice(null, null, null, 'en')).toBeNull();
  });

  it('returns free label when min === 0', () => {
    const result = formatPrice(0, null, 'EUR', 'en');
    expect(result).toBe('Free');
  });

  it('shows range when min !== max', () => {
    const result = formatPrice(10, 20, 'EUR', 'en');
    expect(result).toContain('10');
    expect(result).toContain('20');
    expect(result).toContain('€');
  });

  it('shows single price when min only', () => {
    const result = formatPrice(15, null, 'EUR', 'en');
    expect(result).toBe('€15');
  });

  it('uses EUR symbol for EUR currency', () => {
    const result = formatPrice(10, 10, 'EUR', 'en');
    expect(result).toContain('€');
  });

  it('uses raw code for non-EUR currency', () => {
    const result = formatPrice(10, null, 'USD', 'en');
    expect(result).toContain('USD');
  });

  it('shows free-with-paid note when min is 0 and max is positive', () => {
    const result = formatPrice(0, 10, 'EUR', 'en');
    expect(result).toContain('Free');
    expect(result).toContain('10');
  });

  it('returns plain free label when min is 0 and max is also 0', () => {
    const result = formatPrice(0, 0, 'EUR', 'en');
    expect(result).toBe('Free');
  });

  it('appends free-options note when hasFreeTier is true', () => {
    const result = formatPrice(14, 17, 'EUR', 'en', true);
    expect(result).toContain('14');
    expect(result).toContain('17');
    expect(result?.toLowerCase()).toContain('free');
  });

  it('does not append free-options note when hasFreeTier is false', () => {
    const result = formatPrice(14, 17, 'EUR', 'en', false);
    expect(result).toBe('€14–€17');
  });
});

describe('categoryGradient', () => {
  it('returns gradient for known category', () => {
    const result = categoryGradient(['music']);
    expect(result).toContain('gradient');
    expect(result).not.toBe(FALLBACK_GRADIENT);
  });

  it('returns fallback for unknown category', () => {
    expect(categoryGradient(['unknown_category_xyz'])).toBe(FALLBACK_GRADIENT);
  });

  it('returns fallback for empty array', () => {
    expect(categoryGradient([])).toBe(FALLBACK_GRADIENT);
  });

  it('normalizes case and spaces', () => {
    const result = categoryGradient(['Food Drink']);
    expect(result).toContain('gradient');
    expect(result).not.toBe(FALLBACK_GRADIENT);
  });
});

describe('formatHourMinute', () => {
  it('formats time as HH:MM', () => {
    const result = formatHourMinute('2024-07-15T18:30:00Z', 'en');
    expect(result).toMatch(/\d{2}:\d{2}/);
  });
});

describe('formatEventShortDate', () => {
  it('formats a short day-month date', () => {
    const result = formatEventShortDate('2024-07-15T18:30:00Z', 'en');
    expect(result).toMatch(/\d{1,2}/);
    expect(result).not.toMatch(/\d{4}/); // no year in the short form
  });
});

describe('truncateForMeta', () => {
  it('returns text unchanged when already within the limit', () => {
    expect(truncateForMeta('Short text.', 155)).toBe('Short text.');
  });

  it('truncates at a word boundary and appends an ellipsis when over the limit', () => {
    const text = 'This is a fairly long sentence that will definitely exceed a very short limit.';
    const result = truncateForMeta(text, 20);
    expect(result.length).toBeLessThanOrEqual(21); // 20 + ellipsis char
    expect(result.endsWith('…')).toBe(true);
    expect(result).not.toMatch(/\s…$/); // no dangling space before the ellipsis
    expect(text.startsWith(result.slice(0, -1))).toBe(true); // never cuts mid-word into a new word
  });

  it('never cuts a word in half', () => {
    const result = truncateForMeta('alpha beta gamma delta epsilon', 12);
    const withoutEllipsis = result.replace(/…$/, '');
    expect(['alpha', 'alpha beta']).toContain(withoutEllipsis);
  });

  it('never splits a surrogate pair (emoji) at the cut boundary', () => {
    const text = '🎉'.repeat(20); // each emoji is a 2-code-unit surrogate pair
    const result = truncateForMeta(text, 15); // odd limit — would split mid-pair on a raw slice()
    const withoutEllipsis = result.replace(/…$/, '');
    expect([...withoutEllipsis].every((ch) => ch === '🎉')).toBe(true);
    expect(withoutEllipsis).not.toMatch(/�/); // no replacement/mojibake character
  });
});

describe('makeActiveClassMap', () => {
  it('maps signals to class names from styles', () => {
    const styles = { activeLike: 'like-cls', activeDislike: 'dislike-cls', activeBookmark: 'bookmark-cls' };
    const map = makeActiveClassMap(styles);
    expect(map.like).toBe('like-cls');
    expect(map.dislike).toBe('dislike-cls');
    expect(map.bookmark).toBe('bookmark-cls');
  });

  it('throws when a required CSS class is missing', () => {
    const styles = { activeLike: 'like-cls' };
    expect(() => makeActiveClassMap(styles)).toThrow('makeActiveClassMap');
  });
});

describe('trackExternalClick', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls api.post with correct path and body', async () => {
    const mockPost = vi.mocked(api.post);
    trackExternalClick(42);
    expect(mockPost).toHaveBeenCalledWith('/feedback', { event_id: 42, signal: 'click_external' });
  });

  it('swallows API errors', async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error('network error'));
    await expect(async () => {
      trackExternalClick(1);
      await new Promise((r) => setTimeout(r, 10));
    }).not.toThrow();
  });
});

describe('datePresetRange', () => {
  function mockToday(iso: string) {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(iso));
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns null bounds for "any"', () => {
    expect(datePresetRange('any')).toEqual({ from: null, to: null });
  });

  it('returns null bounds for "custom" (resolved from customFrom/customTo instead)', () => {
    expect(datePresetRange('custom')).toEqual({ from: null, to: null });
  });

  it('"today" returns the same date for from and to', () => {
    mockToday('2026-07-15T10:00:00');
    expect(datePresetRange('today')).toEqual({ from: '2026-07-15', to: '2026-07-15' });
  });

  it('"7d" spans today through +7 days', () => {
    mockToday('2026-07-15T10:00:00');
    expect(datePresetRange('7d')).toEqual({ from: '2026-07-15', to: '2026-07-22' });
  });

  it('"weekend" resolves to the upcoming Saturday/Sunday from a weekday', () => {
    mockToday('2026-07-15T10:00:00'); // Wednesday
    expect(datePresetRange('weekend')).toEqual({ from: '2026-07-18', to: '2026-07-19' });
  });

  it('"weekend" on a Saturday starts today', () => {
    mockToday('2026-07-18T10:00:00'); // Saturday
    expect(datePresetRange('weekend')).toEqual({ from: '2026-07-18', to: '2026-07-19' });
  });
});

describe('isFullSet', () => {
  it('is true when selection length matches the full list', () => {
    expect(isFullSet(['a', 'b'], ['x', 'y'])).toBe(true);
  });

  it('is false for a proper subset or empty selection', () => {
    expect(isFullSet(['a'], ['x', 'y'])).toBe(false);
    expect(isFullSet([], ['x', 'y'])).toBe(false);
  });
});

describe('explore filters <-> URL params', () => {
  it('parses defaults from an empty URLSearchParams (all categories/vibes, forYou off)', () => {
    expect(parseExploreFilters(new URLSearchParams())).toEqual(DEFAULT_EXPLORE_FILTERS);
  });

  it('round-trips a non-default filter set through the URL', () => {
    const filters: ExploreFilters = {
      q: 'jazz',
      category: ['music', 'nightlife'],
      vibe: ['trendy'],
      datePreset: '7d',
      customFrom: null,
      customTo: null,
      free: true,
      forYou: true,
      sort: 'date',
    };
    const params = exploreFiltersToSearchParams(filters);
    expect(parseExploreFilters(params)).toEqual(filters);
  });

  it('round-trips a custom date range through the URL', () => {
    const filters: ExploreFilters = {
      ...DEFAULT_EXPLORE_FILTERS,
      datePreset: 'custom',
      customFrom: '2026-09-01',
      customTo: '2026-09-15',
    };
    const params = exploreFiltersToSearchParams(filters);
    expect(params.get('date')).toBe('custom');
    expect(params.get('date_from')).toBe('2026-09-01');
    expect(params.get('date_to')).toBe('2026-09-15');
    expect(parseExploreFilters(params)).toEqual(filters);
  });

  it('omits date_from/date_to when datePreset is custom but no range is set yet', () => {
    const filters: ExploreFilters = { ...DEFAULT_EXPLORE_FILTERS, datePreset: 'custom' };
    const params = exploreFiltersToSearchParams(filters);
    expect(params.has('date_from')).toBe(false);
    expect(params.has('date_to')).toBe(false);
  });

  it('drops a malformed date_from/date_to (hand-edited deep link) instead of passing it through', () => {
    const malformed = new URLSearchParams('date=custom&date_from=garbage&date_to=2026-13-40');
    const parsed = parseExploreFilters(malformed);
    expect(parsed.customFrom).toBeNull();
    expect(parsed.customTo).toBeNull();
  });

  it('accepts a well-formed date_from/date_to', () => {
    const params = new URLSearchParams('date=custom&date_from=2026-09-01&date_to=2026-09-15');
    const parsed = parseExploreFilters(params);
    expect(parsed.customFrom).toBe('2026-09-01');
    expect(parsed.customTo).toBe('2026-09-15');
  });

  it('an absent category/vibe param means "all"; an empty one means "none"', () => {
    expect(parseExploreFilters(new URLSearchParams('q=x')).category).toEqual([...CATEGORIES]);
    expect(parseExploreFilters(new URLSearchParams('category=')).category).toEqual([]);
    expect(parseExploreFilters(new URLSearchParams('vibe=')).vibe).toEqual([]);
  });

  it('drops invalid slugs and dedupes, so a padded/corrupted deep link cannot fake a full selection', () => {
    // 12 comma-separated entries (matching CATEGORIES.length) but only one real slug —
    // must not be mistaken for "all categories" by isFullSet's length check.
    const padded = Array(12).fill('music').join(',');
    expect(parseExploreFilters(new URLSearchParams(`category=${padded}`)).category).toEqual(['music']);

    const withJunk = new URLSearchParams('category=music,not-a-real-category,music');
    expect(parseExploreFilters(withJunk).category).toEqual(['music']);
  });

  it('for_you defaults to false when the param is absent', () => {
    const params = new URLSearchParams('category=music');
    expect(parseExploreFilters(params).forYou).toBe(false);
  });

  it('a full category/vibe selection omits the URL param (round-trips to "all")', () => {
    const filters: ExploreFilters = { ...DEFAULT_EXPLORE_FILTERS };
    const params = exploreFiltersToSearchParams(filters);
    expect(params.has('category')).toBe(false);
    expect(params.has('vibe')).toBe(false);
  });
});

describe('buildExploreApiQuery', () => {
  it('always includes for_you, sort, limit, offset', () => {
    const qs = buildExploreApiQuery(DEFAULT_EXPLORE_FILTERS, 0);
    const params = new URLSearchParams(qs);
    expect(params.get('for_you')).toBe('false');
    expect(params.get('sort')).toBe('relevance');
    expect(params.get('offset')).toBe('0');
    expect(params.get('limit')).toBeTruthy();
  });

  it('omits q/free when unset, includes them when set', () => {
    const withFilters: ExploreFilters = {
      ...DEFAULT_EXPLORE_FILTERS,
      q: 'jazz',
      category: ['music'],
      free: true,
    };
    const params = new URLSearchParams(buildExploreApiQuery(withFilters, 24));
    expect(params.get('q')).toBe('jazz');
    expect(params.get('category')).toBe('music');
    expect(params.get('free')).toBe('true');
    expect(params.get('offset')).toBe('24');

    const emptyParams = new URLSearchParams(buildExploreApiQuery(DEFAULT_EXPLORE_FILTERS, 0));
    expect(emptyParams.has('q')).toBe(false);
    expect(emptyParams.has('free')).toBe(false);
  });

  it('omits category/vibe when the full set is selected (backend treats absent as "all")', () => {
    const params = new URLSearchParams(buildExploreApiQuery(DEFAULT_EXPLORE_FILTERS, 0));
    expect(params.has('category')).toBe(false);
    expect(params.has('vibe')).toBe(false);
  });

  it('omits category/vibe when the selection is empty (client-side disables the request instead)', () => {
    const filters: ExploreFilters = { ...DEFAULT_EXPLORE_FILTERS, category: [], vibe: [] };
    const params = new URLSearchParams(buildExploreApiQuery(filters, 0));
    expect(params.has('category')).toBe(false);
    expect(params.has('vibe')).toBe(false);
  });

  it('uses customFrom/customTo directly for a custom range, not datePresetRange', () => {
    const filters: ExploreFilters = {
      ...DEFAULT_EXPLORE_FILTERS,
      datePreset: 'custom',
      customFrom: '2026-09-01',
      customTo: '2026-09-15',
    };
    const params = new URLSearchParams(buildExploreApiQuery(filters, 0));
    expect(params.get('date_from')).toBe('2026-09-01');
    expect(params.get('date_to')).toBe('2026-09-15');
  });
});

describe('parseISODateLocal / formatDateRangeShort', () => {
  it('parses a YYYY-MM-DD string as a local-midnight Date', () => {
    const d = parseISODateLocal('2026-09-15');
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(8);
    expect(d.getDate()).toBe(15);
  });

  it('formats a short range label', () => {
    const result = formatDateRangeShort('2026-09-01', '2026-09-15', 'en');
    expect(result).toContain('–');
    expect(result).toMatch(/^1 Sep\w* – 15 Sep\w*$/);
  });
});

describe('activeFacetCount', () => {
  it('counts narrowed category/vibe selections, date preset, and free', () => {
    const filters: ExploreFilters = {
      ...DEFAULT_EXPLORE_FILTERS,
      category: ['music', 'nightlife'],
      vibe: ['trendy'],
      datePreset: 'today',
      free: true,
    };
    expect(activeFacetCount(filters)).toBe(4);
  });

  it('is zero for the default filter set (all categories/vibes selected)', () => {
    expect(activeFacetCount(DEFAULT_EXPLORE_FILTERS)).toBe(0);
  });

  it('counts an emptied facet as narrowed', () => {
    expect(activeFacetCount({ ...DEFAULT_EXPLORE_FILTERS, category: [] })).toBe(1);
  });
});

describe('shouldFlipPopover', () => {
  it('flips when a wide popover near the right edge would overflow', () => {
    expect(shouldFlipPopover(700, 330, 800, 24)).toBe(true);
  });

  it('does not flip when the trigger is near the left edge', () => {
    expect(shouldFlipPopover(20, 330, 800, 24)).toBe(false);
  });

  it('does not flip exactly at the boundary (viewportWidth - margin)', () => {
    expect(shouldFlipPopover(446, 330, 800, 24)).toBe(false);
  });

  it('flips one pixel past the boundary', () => {
    expect(shouldFlipPopover(447, 330, 800, 24)).toBe(true);
  });
});

describe('monthGridDays', () => {
  it('produces a 6x7 grid starting on the configured week start', () => {
    // July 2024 starts on a Monday — with weekStart=1 the grid should start
    // exactly on 1 Jul with no leading spill.
    const cells = monthGridDays(2024, 6, 1);
    expect(cells).toHaveLength(42);
    expect(cells[0].date.getDate()).toBe(1);
    expect(cells[0].spill).toBe(false);
  });

  it('spills leading days from the previous month when the 1st is not the week start', () => {
    // February 2024 (leap year) starts on a Thursday.
    const cells = monthGridDays(2024, 1, 1);
    expect(cells[0].spill).toBe(true);
    expect(cells[0].date.getMonth()).toBe(0);
    // 29 Feb 2024 exists (leap year) and is not spill.
    const leapDay = cells.find((c) => c.date.getMonth() === 1 && c.day === 29);
    expect(leapDay?.spill).toBe(false);
  });

  it('spills trailing days into the next month to fill the fixed 42-cell grid', () => {
    const cells = monthGridDays(2024, 6, 1);
    const last = cells[cells.length - 1];
    expect(last.spill).toBe(true);
  });
});

describe('weekdayHeaders', () => {
  it('returns 7 labels starting on Monday', () => {
    const labels = weekdayHeaders('en');
    expect(labels).toHaveLength(7);
  });
});

describe('splitDateTimeValue / joinDateTimeValue', () => {
  it('round-trips a canonical value', () => {
    const parts = splitDateTimeValue('2026-08-01T18:00');
    expect(parts).toEqual({ year: 2026, month: 7, day: 1, hour: 18, minute: 0 });
    expect(joinDateTimeValue(new Date(2026, 7, 1), 18, 0)).toBe('2026-08-01T18:00');
  });

  it('rejects an impossible calendar date', () => {
    expect(splitDateTimeValue('2026-02-30T10:00')).toBeNull();
  });

  it('rejects malformed text', () => {
    expect(splitDateTimeValue('not a date')).toBeNull();
    expect(splitDateTimeValue('')).toBeNull();
  });
});

describe('parseTypedDate', () => {
  it('accepts a valid canonical value', () => {
    expect(parseTypedDate('2026-08-01T18:00')).toBe('2026-08-01T18:00');
  });

  it('rejects a partial or invalid value', () => {
    expect(parseTypedDate('2026-08-01')).toBeNull();
    expect(parseTypedDate('2026-08-01T18')).toBeNull();
  });
});

describe('formatPickerValue', () => {
  it('formats a valid value', () => {
    expect(formatPickerValue('2026-08-01T18:00', 'en')).toBe('1 Aug, 18:00');
  });

  it('returns an empty string for an empty/invalid value', () => {
    expect(formatPickerValue('', 'en')).toBe('');
    expect(formatPickerValue('garbage', 'en')).toBe('');
  });
});

describe('formatMonthYearLabel', () => {
  it('formats a month and year', () => {
    expect(formatMonthYearLabel(2026, 6, 'en')).toBe('July 2026');
  });
});

describe('toDisplayDateTime / fromDisplayDateTime', () => {
  it('replaces the T separator with a space for display', () => {
    expect(toDisplayDateTime('2026-08-01T18:00')).toBe('2026-08-01 18:00');
  });

  it('leaves an empty string unchanged', () => {
    expect(toDisplayDateTime('')).toBe('');
  });

  it('round-trips back to the canonical T-joined format', () => {
    expect(fromDisplayDateTime('2026-08-01 18:00')).toBe('2026-08-01T18:00');
    expect(fromDisplayDateTime(toDisplayDateTime('2026-08-01T18:00'))).toBe('2026-08-01T18:00');
  });

  it('leaves malformed text without a space unchanged', () => {
    expect(fromDisplayDateTime('garbage')).toBe('garbage');
  });
});

describe('buildMapsUrl', () => {
  it('prefers coordinates over address', () => {
    expect(buildMapsUrl(59.437, 24.7536, 'Vabaduse väljak')).toBe(`${GOOGLE_MAPS_SEARCH_URL}59.437,24.7536`);
  });

  it('handles equator/meridian coordinates (0,0) instead of falling through to address', () => {
    expect(buildMapsUrl(0, 0, 'Null Island')).toBe(`${GOOGLE_MAPS_SEARCH_URL}0,0`);
  });

  it('falls back to the address when coordinates are missing', () => {
    expect(buildMapsUrl(null, null, 'Vabaduse väljak')).toBe(`${GOOGLE_MAPS_SEARCH_URL}${encodeURIComponent('Vabaduse väljak')}`);
  });

  it('returns null when neither coordinates nor address are available', () => {
    expect(buildMapsUrl(null, null, null)).toBeNull();
  });
});

describe('localeLabel', () => {
  it('returns the configured label for a known code', () => {
    expect(localeLabel('et')).toBe('ET');
  });
  it('falls back to the upper-cased code for an unknown one', () => {
    expect(localeLabel('xx')).toBe('XX');
  });
});

describe('localizedFieldLabel', () => {
  it('suffixes the translated field name with the language label', () => {
    expect(localizedFieldLabel('claim_edit_field_title', 'en', 'ru')).toBe(`${t('claim_edit_field_title', 'en')} (${localeLabel('ru')})`);
  });
});

describe('localizedTriplet', () => {
  it('reads et/en/ru slots from the record', () => {
    expect(localizedTriplet({ et: 'a', en: 'b', ru: 'c' }, 'base')).toEqual(['a', 'b', 'c']);
  });
  it('falls back to base for ET and blanks for EN/RU', () => {
    expect(localizedTriplet(null, 'base')).toEqual(['base', '', '']);
    expect(localizedTriplet(undefined, undefined)).toEqual(['', '', '']);
  });
});

describe('weekdayOffset', () => {
  it('counts days since the week start', () => {
    const wednesday = new Date(2024, 6, 3);
    expect(weekdayOffset(wednesday, 1)).toBe(2);
    expect(weekdayOffset(wednesday, 0)).toBe(3);
    expect(weekdayOffset(new Date(2024, 6, 7), 1)).toBe(6);
  });
});

describe('cardAnimationDelayMs', () => {
  it('staggers within a page and plateaus after the cap', () => {
    expect(cardAnimationDelayMs(0)).toBe(0);
    expect(cardAnimationDelayMs(3)).toBe(240);
    expect(cardAnimationDelayMs(23)).toBe(640);
  });

  it('restarts on every page so later cards are not held invisible', () => {
    expect(cardAnimationDelayMs(24)).toBe(0);
    expect(cardAnimationDelayMs(24 * 5 + 2)).toBe(160);
  });
});

describe('buildExploreApiQuery cursor', () => {
  it('sends cursor only when given', () => {
    expect(new URLSearchParams(buildExploreApiQuery(DEFAULT_EXPLORE_FILTERS, 0)).has('cursor')).toBe(false);
    const params = new URLSearchParams(buildExploreApiQuery(DEFAULT_EXPLORE_FILTERS, 24, 'abc'));
    expect(params.get('cursor')).toBe('abc');
  });
});

describe('nextKeysetParam', () => {
  it('stops when there is no more', () => {
    expect(nextKeysetParam({ has_more: false, offset: 0, next_cursor: 'x' }, 24)).toBeUndefined();
  });

  it('carries the server cursor when present', () => {
    expect(nextKeysetParam({ has_more: true, offset: 0, next_cursor: 'x' }, 24)).toEqual({ offset: 24, cursor: 'x' });
  });

  it('falls back to offset arithmetic without a cursor', () => {
    expect(nextKeysetParam({ has_more: true, offset: 24 }, 24)).toEqual({ offset: 48, cursor: undefined });
    expect(nextKeysetParam({ has_more: true, offset: 24, next_cursor: null }, 24)).toEqual({ offset: 48, cursor: undefined });
  });
});

describe('toggleCapped', () => {
  it('appends a new value while there is room', () => {
    expect(toggleCapped(['a'], 'b', 3)).toEqual(['a', 'b']);
  });

  it('removes a value that is already present', () => {
    expect(toggleCapped(['a', 'b'], 'a', 3)).toEqual(['b']);
  });

  it('returns the list unchanged once the cap is reached', () => {
    const list = ['a', 'b', 'c'];
    expect(toggleCapped(list, 'd', 3)).toBe(list);
  });

  it('still removes at the cap, and adds nothing when the cap is zero', () => {
    expect(toggleCapped(['a', 'b', 'c'], 'c', 3)).toEqual(['a', 'b']);
    expect(toggleCapped([], 'a', 0)).toEqual([]);
  });
});

describe('Europe/Tallinn pinning', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('formats event instants as Tallinn wall-clock time (winter, UTC+2)', () => {
    expect(formatHourMinute('2026-01-15T17:00:00Z', 'en')).toBe('19:00');
  });

  it('formats event instants as Tallinn wall-clock time (summer, UTC+3)', () => {
    expect(formatHourMinute('2026-07-15T17:00:00Z', 'en')).toBe('20:00');
  });

  it('rolls the date over when Tallinn is already on the next day', () => {
    expect(formatEventTime('2026-07-15T22:30:00Z', 'en')).toContain('16 Jul');
    expect(formatEventTime('2026-07-15T22:30:00Z', 'en')).toContain('01:30');
  });

  it('tallinnToday follows the Tallinn calendar day, not the host zone', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-15T22:30:00Z')); // 01:30 on 16 Jul in Tallinn
    const today = tallinnToday();
    expect([today.getFullYear(), today.getMonth(), today.getDate()]).toEqual([2026, 6, 16]);
    expect(datePresetRange('today')).toEqual({ from: '2026-07-16', to: '2026-07-16' });
  });
});
