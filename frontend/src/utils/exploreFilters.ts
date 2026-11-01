import { BROWSE_PAGE_SIZE, CATEGORIES, VIBES } from '../_generated/sharedConstants';
import { ISO_DATE_RE } from '../constants/core';
import {
  type DatePreset,
  type SortOption,
  DATE_PRESET_DAYS,
  DATE_PRESET_DAYS_FALLBACK,
  DATE_PRESET_CUSTOM,
  DATE_PRESET_DEFAULT,
  DATE_PRESET_TODAY,
  DATE_PRESET_WEEKEND,
  EXPLORE_PARAM,
  EXPLORE_URL_FLAG_TRUE,
  EXPLORE_API_FLAG_TRUE,
  SORT_DEFAULT,
} from '../constants/explore';
import { tallinnToday, toDateStr } from './calendar';

export interface ExploreFilters {
  q: string;
  category: string[];
  vibe: string[];
  datePreset: DatePreset;
  customFrom: string | null;
  customTo: string | null;
  free: boolean;
  forYou: boolean;
  sort: SortOption;
}

export const DEFAULT_EXPLORE_FILTERS: ExploreFilters = {
  q: '',
  category: [...CATEGORIES],
  vibe: [...VIBES],
  datePreset: DATE_PRESET_DEFAULT,
  customFrom: null,
  customTo: null,
  free: false,
  forYou: false,
  sort: SORT_DEFAULT,
};

/** True when `sel` holds every slug in `all` — selections only ever contain
 * valid slugs, so a length match is sufficient (no need to compare content).
 * Exported only so exploreFilters.test.ts can exercise it directly; every production
 * call site is within this module. */
export function isFullSet(sel: string[], all: readonly string[]): boolean {
  return sel.length === all.length;
}

/** Resolve a date preset against the current Tallinn day (backend stays
 * stateless). Uses local date components of the Tallinn day, not toISOString(),
 * so the resolved day never shifts across a UTC boundary. */
export function datePresetRange(preset: DatePreset): { from: string | null; to: string | null } {
  if (preset === DATE_PRESET_DEFAULT) return { from: null, to: null };
  // Custom ranges resolve from ExploreFilters.customFrom/customTo directly
  // (see buildExploreApiQuery), not from this function — this guard just
  // keeps datePresetRange total/correct so 'custom' can never fall through
  // to the DATE_PRESET_DAYS fallback below and get silently misread as a
  // 30-day window.
  if (preset === DATE_PRESET_CUSTOM) return { from: null, to: null };
  const today = tallinnToday();

  if (preset === DATE_PRESET_TODAY) {
    const s = toDateStr(today);
    return { from: s, to: s };
  }
  if (preset === DATE_PRESET_WEEKEND) {
    const day = today.getDay(); // 0 = Sunday .. 6 = Saturday
    const satOffset = day === 6 ? 0 : day === 0 ? -1 : 6 - day;
    const sat = new Date(today);
    sat.setDate(today.getDate() + satOffset);
    const sun = new Date(sat);
    sun.setDate(sat.getDate() + 1);
    return { from: toDateStr(sat), to: toDateStr(sun) };
  }
  const days = DATE_PRESET_DAYS[preset] ?? DATE_PRESET_DAYS_FALLBACK;
  const end = new Date(today);
  end.setDate(today.getDate() + days);
  return { from: toDateStr(today), to: toDateStr(end) };
}

/** Comma-split, dedupe, silently drop anything outside `valid` — mirrors the
 * backend's `_parse_slug_list` (browse.py). Applied to URL-sourced category/
 * vibe values so a hand-edited or corrupted deep link (duplicate or invalid
 * slugs padding the list to the full taxonomy length) can't fool isFullSet's
 * length-only comparison into treating a narrow selection as "select all". */
function parseSlugList(raw: string, valid: readonly string[]): string[] {
  const validSet = new Set(valid);
  const seen = new Set<string>();
  const result: string[] = [];
  for (const slug of raw.split(',')) {
    const trimmed = slug.trim();
    if (trimmed && validSet.has(trimmed) && !seen.has(trimmed)) {
      seen.add(trimmed);
      result.push(trimmed);
    }
  }
  return result;
}

/** Validates a `YYYY-MM-DD` string against both the wire format and the
 * calendar (rejects e.g. `2026-02-30`), returning it unchanged or null.
 * Guards parseExploreFilters' URL-sourced customFrom/customTo — a
 * hand-edited or corrupted deep link must not reach parseISODateLocal /
 * Intl.DateTimeFormat with a value that throws `RangeError: Invalid time
 * value` and crashes the route (mirrors parseSlugList's defensive parse of
 * category/vibe). */
function parseIsoDateOrNull(raw: string | null): string | null {
  if (raw === null) return null;
  const m = ISO_DATE_RE.exec(raw);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
  return raw;
}

/** Filters ⇄ URL query params — the single source of truth for /explore state
 * (useSearchParams). Only non-default values are written, so a fresh visit
 * (no params) round-trips to DEFAULT_EXPLORE_FILTERS. */
export function parseExploreFilters(params: URLSearchParams): ExploreFilters {
  const rawCategory = params.get(EXPLORE_PARAM.category);
  const rawVibe = params.get(EXPLORE_PARAM.vibe);
  return {
    q: params.get(EXPLORE_PARAM.q) ?? '',
    category: rawCategory === null ? [...CATEGORIES] : parseSlugList(rawCategory, CATEGORIES),
    vibe: rawVibe === null ? [...VIBES] : parseSlugList(rawVibe, VIBES),
    datePreset: (params.get(EXPLORE_PARAM.date) as DatePreset | null) ?? DATE_PRESET_DEFAULT,
    // Only meaningful when datePreset === 'custom', but harmless to always
    // read — null when absent or malformed.
    customFrom: parseIsoDateOrNull(params.get(EXPLORE_PARAM.dateFrom)),
    customTo: parseIsoDateOrNull(params.get(EXPLORE_PARAM.dateTo)),
    free: params.get(EXPLORE_PARAM.free) === EXPLORE_URL_FLAG_TRUE,
    forYou: params.get(EXPLORE_PARAM.forYou) === EXPLORE_URL_FLAG_TRUE,
    sort: (params.get(EXPLORE_PARAM.sort) as SortOption | null) ?? SORT_DEFAULT,
  };
}

export function exploreFiltersToSearchParams(filters: ExploreFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.q) params.set(EXPLORE_PARAM.q, filters.q);
  if (!isFullSet(filters.category, CATEGORIES)) params.set(EXPLORE_PARAM.category, filters.category.join(','));
  if (!isFullSet(filters.vibe, VIBES)) params.set(EXPLORE_PARAM.vibe, filters.vibe.join(','));
  if (filters.datePreset !== DATE_PRESET_DEFAULT) params.set(EXPLORE_PARAM.date, filters.datePreset);
  if (filters.datePreset === DATE_PRESET_CUSTOM && filters.customFrom && filters.customTo) {
    params.set(EXPLORE_PARAM.dateFrom, filters.customFrom);
    params.set(EXPLORE_PARAM.dateTo, filters.customTo);
  }
  if (filters.free) params.set(EXPLORE_PARAM.free, EXPLORE_URL_FLAG_TRUE);
  if (filters.forYou) params.set(EXPLORE_PARAM.forYou, EXPLORE_URL_FLAG_TRUE);
  if (filters.sort !== SORT_DEFAULT) params.set(EXPLORE_PARAM.sort, filters.sort);
  return params;
}

/** Build the GET /explore query string for a given filter set + page offset. */
export function buildExploreApiQuery(filters: ExploreFilters, offset: number): string {
  const params = new URLSearchParams();
  if (filters.q) params.set(EXPLORE_PARAM.q, filters.q);
  if (filters.category.length && !isFullSet(filters.category, CATEGORIES)) {
    params.set(EXPLORE_PARAM.category, filters.category.join(','));
  }
  if (filters.vibe.length && !isFullSet(filters.vibe, VIBES)) {
    params.set(EXPLORE_PARAM.vibe, filters.vibe.join(','));
  }
  if (filters.datePreset === DATE_PRESET_CUSTOM) {
    if (filters.customFrom) params.set(EXPLORE_PARAM.dateFrom, filters.customFrom);
    if (filters.customTo) params.set(EXPLORE_PARAM.dateTo, filters.customTo);
  } else {
    const { from, to } = datePresetRange(filters.datePreset);
    if (from) params.set(EXPLORE_PARAM.dateFrom, from);
    if (to) params.set(EXPLORE_PARAM.dateTo, to);
  }
  if (filters.free) params.set(EXPLORE_PARAM.free, EXPLORE_API_FLAG_TRUE);
  params.set(EXPLORE_PARAM.forYou, String(filters.forYou));
  params.set(EXPLORE_PARAM.sort, filters.sort);
  params.set(EXPLORE_PARAM.limit, String(BROWSE_PAGE_SIZE));
  params.set(EXPLORE_PARAM.offset, String(offset));
  return params.toString();
}

/** Number of narrowed facets — drives the mobile "Filters (n)" badge. Counts
 * category/vibe only when not the full set (the all-selected default isn't a
 * narrowing filter), plus date preset and free. Search text and sort are not
 * facets for this count. */
export function activeFacetCount(filters: ExploreFilters): number {
  let count = 0;
  if (!isFullSet(filters.category, CATEGORIES)) count += 1;
  if (!isFullSet(filters.vibe, VIBES)) count += 1;
  if (filters.datePreset !== DATE_PRESET_DEFAULT) count += 1;
  if (filters.free) count += 1;
  return count;
}
