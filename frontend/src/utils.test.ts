import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { cx, safeUrl, sanitizeHtml, formatPrice, categoryGradient, formatHourMinute, makeActiveClassMap, trackExternalClick, datePresetRange, parseExploreFilters, exploreFiltersToSearchParams, buildExploreApiQuery, activeFacetCount, isFullSet, shouldFlipPopover, DEFAULT_EXPLORE_FILTERS, type ExploreFilters } from './utils';
import { FALLBACK_GRADIENT, CATEGORIES } from './constants';

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
      free: true,
      forYou: true,
      sort: 'date',
    };
    const params = exploreFiltersToSearchParams(filters);
    expect(parseExploreFilters(params)).toEqual(filters);
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
