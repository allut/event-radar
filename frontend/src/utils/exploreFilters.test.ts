import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  DEFAULT_EXPLORE_FILTERS,
  activeFacetCount,
  buildExploreApiQuery,
  datePresetRange,
  exploreFiltersToSearchParams,
  isFullSet,
  parseExploreFilters,
  type ExploreFilters,
} from './exploreFilters';
import { CATEGORIES } from '../_generated/sharedConstants';

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
