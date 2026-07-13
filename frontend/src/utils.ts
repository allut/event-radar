import DOMPurify from 'dompurify';
import { api } from './api/client';
import { CATEGORY_GRADIENTS, FALLBACK_GRADIENT, EUR_SYMBOL, GOOGLE_MAPS_SEARCH_URL, type Signal, toLocaleCode, SAFE_URL_SCHEMES, SANITIZE_ALLOWED_TAGS, SANITIZE_ALLOWED_ATTR, SIGNAL_TO_CLASS, BROWSE_PAGE_SIZE, CATEGORIES, VIBES, type DatePreset, type SortOption } from './constants';
import { t, ti } from './i18n';

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}

/** Defense-in-depth render guard: only allow http(s) URLs into href/src attributes.
 * The backend already drops non-http(s) schemes at ingest time (safe_external_url),
 * but this protects against any other path that might surface a raw URL. */
export function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const proto = new URL(url).protocol.replace(/:$/, '');
    return SAFE_URL_SCHEMES.has(proto) ? url : null;
  } catch {
    return null;
  }
}

// Registered once at module scope (not per sanitizeHtml call) — DOMPurify hooks
// are global, so re-adding on every call would pile up duplicate listeners.
// Forces rel="noopener noreferrer" on every sanitized <a>, matching the trusted
// outbound links in EventCard/EventDetail: without it, an anchor from
// untrusted event HTML opened via target="_blank" could use
// window.opener to navigate the origin tab (reverse tabnabbing), and omitting
// rel="noreferrer" would leak the full referrer URL to the linked site.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('rel', 'noopener noreferrer');
    node.setAttribute('target', '_blank');
  }
});

/** Client-side sanitizer for HTML from event description/important_info fields.
 * Strictly matches the backend nh3 allowlist; defense-in-depth before dangerouslySetInnerHTML. */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: SANITIZE_ALLOWED_TAGS,
    ALLOWED_ATTR: SANITIZE_ALLOWED_ATTR,
  });
}

export function formatHourMinute(iso: string, locale: string): string {
  return new Date(iso).toLocaleTimeString(toLocaleCode(locale), {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

export function trackExternalClick(eventId: number): void {
  api.post('/feedback', { event_id: eventId, signal: 'click_external' }).catch(() => undefined);
}

export function categoryGradient(categories: string[]): string {
  const key = categories[0]?.toLowerCase().replace(/\s+/g, '_') ?? '';
  return CATEGORY_GRADIENTS[key] ?? FALLBACK_GRADIENT;
}

export function formatPrice(min: number | null, max: number | null, currency: string | null, locale: string, hasFreeTier = false): string | null {
  if (min === null && max === null) return null;
  const sym = currency === 'EUR' ? EUR_SYMBOL : currency ?? '';
  if (min === 0) {
    // Base admission is free; a positive max means an optional paid tier exists
    // (e.g. an open-mic's support ticket) — surface it rather than showing a
    // bare "Free" that hides the paid option entirely.
    if (max !== null && max > 0) {
      return ti('price_free_with_paid', locale, { amount: `${sym}${max}` });
    }
    return t('price_free', locale);
  }
  let priceStr: string | null;
  if (min !== null && max !== null && min !== max) {
    priceStr = `${sym}${min}–${sym}${max}`;
  } else if (min !== null) {
    priceStr = `${sym}${min}`;
  } else {
    priceStr = null;
  }
  if (priceStr && hasFreeTier) {
    return `${priceStr} · ${t('price_free_options', locale)}`;
  }
  return priceStr;
}

/** Google Maps search link: coords when present (most precise), else the
 * address, else null (no link rendered). */
export function buildMapsUrl(
  lat: number | null,
  lng: number | null,
  address: string | null,
): string | null {
  if (lat && lng) return `${GOOGLE_MAPS_SEARCH_URL}${lat},${lng}`;
  if (address) return `${GOOGLE_MAPS_SEARCH_URL}${encodeURIComponent(address)}`;
  return null;
}

export function formatEventTime(iso: string, locale: string): string {
  const localeCode = toLocaleCode(locale);
  const date = new Date(iso);
  const weekday = date.toLocaleDateString(localeCode, { weekday: 'short' });
  const day = date.toLocaleDateString(localeCode, { day: 'numeric', month: 'short' });
  const time = date.toLocaleTimeString(localeCode, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${weekday}, ${day} · ${time}`;
}

export function formatEventDateTime(iso: string, locale: string): string {
  const localeCode = toLocaleCode(locale);
  const date = new Date(iso);
  const weekday = date.toLocaleDateString(localeCode, { weekday: 'long' });
  const day = date.toLocaleDateString(localeCode, { day: 'numeric', month: 'long', year: 'numeric' });
  const time = date.toLocaleTimeString(localeCode, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${weekday}, ${day} · ${time}`;
}

export function formatTodayDate(locale: string): string {
  const localeCode = toLocaleCode(locale);
  return new Date().toLocaleDateString(localeCode, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

export function padIndex(n: number): string {
  return String(n).padStart(2, '0');
}

export function makeActiveClassMap(styles: Record<string, string>): Record<Signal, string> {
  const result = {} as Record<Signal, string>;
  for (const [signal, cssKey] of Object.entries(SIGNAL_TO_CLASS) as [Signal, string][]) {
    const cls = styles[cssKey];
    if (!cls) throw new Error(`makeActiveClassMap: CSS class "${cssKey}" is missing from styles module`);
    result[signal] = cls;
  }
  return result;
}

// ─── Explore ─────────────────────────────────────────────────────────────────

export interface ExploreFilters {
  q: string;
  category: string[];
  vibe: string[];
  datePreset: DatePreset;
  free: boolean;
  forYou: boolean;
  sort: SortOption;
}

export const DEFAULT_EXPLORE_FILTERS: ExploreFilters = {
  q: '',
  category: [...CATEGORIES],
  vibe: [...VIBES],
  datePreset: 'any',
  free: false,
  forYou: false,
  sort: 'relevance',
};

/** True when `sel` holds every slug in `all` — selections only ever contain
 * valid slugs, so a length match is sufficient (no need to compare content). */
export function isFullSet(sel: string[], all: readonly string[]): boolean {
  return sel.length === all.length;
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function toDateStr(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/** Resolve a date preset against the browser's local clock (backend stays
 * stateless — see plan.md). Uses local date components, not toISOString(),
 * so the resolved day never shifts across a UTC boundary. */
export function datePresetRange(preset: DatePreset): { from: string | null; to: string | null } {
  if (preset === 'any') return { from: null, to: null };
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  if (preset === 'today') {
    const s = toDateStr(today);
    return { from: s, to: s };
  }
  if (preset === 'weekend') {
    const day = today.getDay(); // 0 = Sunday .. 6 = Saturday
    const satOffset = day === 6 ? 0 : day === 0 ? -1 : 6 - day;
    const sat = new Date(today);
    sat.setDate(today.getDate() + satOffset);
    const sun = new Date(sat);
    sun.setDate(sat.getDate() + 1);
    return { from: toDateStr(sat), to: toDateStr(sun) };
  }
  const days = preset === '7d' ? 7 : 30;
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
  const seen: string[] = [];
  for (const slug of raw.split(',')) {
    const trimmed = slug.trim();
    if (trimmed && validSet.has(trimmed) && !seen.includes(trimmed)) seen.push(trimmed);
  }
  return seen;
}

/** Filters ⇄ URL query params — the single source of truth for /explore state
 * (useSearchParams). Only non-default values are written, so a fresh visit
 * (no params) round-trips to DEFAULT_EXPLORE_FILTERS. */
export function parseExploreFilters(params: URLSearchParams): ExploreFilters {
  const rawCategory = params.get('category');
  const rawVibe = params.get('vibe');
  return {
    q: params.get('q') ?? '',
    category: rawCategory === null ? [...CATEGORIES] : parseSlugList(rawCategory, CATEGORIES),
    vibe: rawVibe === null ? [...VIBES] : parseSlugList(rawVibe, VIBES),
    datePreset: (params.get('date') as DatePreset | null) ?? 'any',
    free: params.get('free') === '1',
    forYou: params.get('for_you') === '1',
    sort: (params.get('sort') as SortOption | null) ?? 'relevance',
  };
}

export function exploreFiltersToSearchParams(filters: ExploreFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.q) params.set('q', filters.q);
  if (!isFullSet(filters.category, CATEGORIES)) params.set('category', filters.category.join(','));
  if (!isFullSet(filters.vibe, VIBES)) params.set('vibe', filters.vibe.join(','));
  if (filters.datePreset !== 'any') params.set('date', filters.datePreset);
  if (filters.free) params.set('free', '1');
  if (filters.forYou) params.set('for_you', '1');
  if (filters.sort !== 'relevance') params.set('sort', filters.sort);
  return params;
}

/** Build the GET /explore query string for a given filter set + page offset. */
export function buildExploreApiQuery(filters: ExploreFilters, offset: number): string {
  const params = new URLSearchParams();
  if (filters.q) params.set('q', filters.q);
  if (filters.category.length && !isFullSet(filters.category, CATEGORIES)) {
    params.set('category', filters.category.join(','));
  }
  if (filters.vibe.length && !isFullSet(filters.vibe, VIBES)) {
    params.set('vibe', filters.vibe.join(','));
  }
  const { from, to } = datePresetRange(filters.datePreset);
  if (from) params.set('date_from', from);
  if (to) params.set('date_to', to);
  if (filters.free) params.set('free', 'true');
  params.set('for_you', String(filters.forYou));
  params.set('sort', filters.sort);
  params.set('limit', String(BROWSE_PAGE_SIZE));
  params.set('offset', String(offset));
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
  if (filters.datePreset !== 'any') count += 1;
  if (filters.free) count += 1;
  return count;
}
