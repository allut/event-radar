import { PERSONAS_EN, type PersonaData } from './_generated/i18nData';
import {
  LOCALE_CODE_MAP as _LOCALE_CODE_MAP,
  DEFAULT_LOCALE_CODE as _DEFAULT_LOCALE_CODE,
  LOCALES,
  APP_VERSION,
  MAGIC_LINK_EXPIRY_MINUTES,
  PERSONA_MAX_SELECTABLE,
  DEFAULT_CURRENCY,
  SAFE_URL_SCHEMES,
  SANITIZE_ALLOWED_TAGS,
  SANITIZE_ALLOWED_ATTR,
  CATEGORIES,
  VIBES,
  BROWSE_PAGE_SIZE,
} from './_generated/sharedConstants';

export { LOCALES, APP_VERSION, MAGIC_LINK_EXPIRY_MINUTES, PERSONA_MAX_SELECTABLE, DEFAULT_CURRENCY, SAFE_URL_SCHEMES, SANITIZE_ALLOWED_TAGS, SANITIZE_ALLOWED_ATTR, CATEGORIES, VIBES, BROWSE_PAGE_SIZE };
export type { PersonaData };

// Re-export PERSONAS under the original name so all import sites are unchanged.
export const PERSONAS: PersonaData[] = PERSONAS_EN;

// ─── React Query ─────────────────────────────────────────────────────────────
export const QUERY_RETRY = 1;
export const QUERY_STALE_TIME = 30_000;

// ─── Local storage keys ──────────────────────────────────────────────────────
export const TOKEN_KEY = 'session_token';
export const LOCALE_KEY = 'locale';

// ─── Auth / magic link ───────────────────────────────────────────────────────
export const AUTH_REDIRECT_DELAY_MS = 600;
// Upper bound on the post-logout 401-redirect suppression window (lib/auth.ts
// isLoggingOut) — comfortably covers the cache-clear race plus Settings'
// AUTH_REDIRECT_DELAY_MS-delayed logout-all flow, without masking a genuine
// session expiry indefinitely if the user never signs back in on this tab.
export const LOGOUT_FLAG_TTL_MS = 10_000;

// ─── Animation ───────────────────────────────────────────────────────────────
export const CARD_ANIMATION_DELAY_STEP_MS = 80;

// ─── Layout ──────────────────────────────────────────────────────────────────
// Matches the `max-width: 640px` breakpoint used across component CSS modules.
export const MOBILE_BREAKPOINT_PX = 640;

// ─── Settings ────────────────────────────────────────────────────────────────
export const SAVE_MSG_CLEAR_DELAY_MS = 2000;

// ─── External links ──────────────────────────────────────────────────────────
export const GOOGLE_MAPS_SEARCH_URL = 'https://www.google.com/maps/search/?api=1&query=';

// ─── Analytics ───────────────────────────────────────────────────────────────
// Matches `/events/:id` so Vercel Analytics groups all event detail views
// under one route instead of one row per event id. Applied to a pathname
// with query/hash already stripped (see maskAnalyticsUrl in utils.ts).
export const ANALYTICS_EVENT_PATH_RE = /^\/events\/\d+$/;

// ─── Locale ──────────────────────────────────────────────────────────────────
export function toLocaleCode(locale: string): string {
  return _LOCALE_CODE_MAP[locale] ?? _DEFAULT_LOCALE_CODE;
}

// ─── Events / feedback ───────────────────────────────────────────────────────
export type Signal = 'like' | 'dislike' | 'bookmark';

export const SIGNAL_CONFIG: Record<Signal, { icon: string; label: string }> = {
  like:     { icon: '👍', label: 'Like' },
  dislike:  { icon: '👎', label: 'Dislike' },
  bookmark: { icon: '🔖', label: 'Bookmark' },
};

export const SIGNAL_TO_CLASS: Record<Signal, string> = {
  like: 'activeLike',
  dislike: 'activeDislike',
  bookmark: 'activeBookmark',
};

export const EUR_SYMBOL = '€';

// Keys must match the 12-category taxonomy in shared/app-config.json (VALID_CATEGORIES)
export const CATEGORY_GRADIENTS: Record<string, string> = {
  nightlife:    'linear-gradient(135deg, #1a0a1f 0%, #2d1040 100%)',
  music:        'linear-gradient(135deg, #0a1020 0%, #1a2060 100%)',
  theater:      'linear-gradient(135deg, #1a100a 0%, #3d2010 100%)',
  exhibitions:  'linear-gradient(135deg, #100a15 0%, #1a0a2a 100%)',
  workshops:    'linear-gradient(135deg, #0a100f 0%, #102020 100%)',
  food_drink:   'linear-gradient(135deg, #0f1a0a 0%, #1a3010 100%)',
  sports:       'linear-gradient(135deg, #0a1a0f 0%, #102030 100%)',
  networking:   'linear-gradient(135deg, #0a0f1a 0%, #0a2030 100%)',
  literature:   'linear-gradient(135deg, #0f100a 0%, #1f2010 100%)',
  family:       'linear-gradient(135deg, #1a0a10 0%, #2a1020 100%)',
  cinema:       'linear-gradient(135deg, #0a1510 0%, #103020 100%)',
  alternative:  'linear-gradient(135deg, #100f0a 0%, #201a0a 100%)',
};
export const FALLBACK_GRADIENT = 'linear-gradient(135deg, #1a1f2e 0%, #13161e 100%)';

// ─── React Query keys ──────────────────────────────────────────────────────────
// Query-key root strings shared across routes and useFeedback's invalidation
// fan-out — a typo in one spot would silently break refresh, so it's centralized.
export const QUERY_KEYS = {
  feed: 'feed',
  explore: 'explore',
  saved: 'saved',
  event: 'event',
  settings: 'settings',
  showcase: 'showcase',
} as const;

// ─── UI state types ───────────────────────────────────────────────────────────
export type LoginState = 'idle' | 'loading' | 'success' | 'error';
export type VerifyState = 'verifying' | 'success' | 'error';

// ─── Explore ─────────────────────────────────────────────────────────────────
// BROWSE_PAGE_SIZE itself is cross-stack (shared/app-config.json), imported above.
export const EXPLORE_SEARCH_DEBOUNCE_MS = 400;

export type SortOption = 'relevance' | 'date' | 'price' | 'quality';

export const SORT_OPTIONS: { value: SortOption; labelKey: string }[] = [
  { value: 'relevance', labelKey: 'sort_relevance' },
  { value: 'date', labelKey: 'sort_date' },
  { value: 'price', labelKey: 'sort_price' },
  { value: 'quality', labelKey: 'sort_quality' },
];

export type DatePreset = 'any' | 'today' | 'weekend' | '7d' | '30d';

export const DATE_PRESETS: { value: DatePreset; labelKey: string }[] = [
  { value: 'any', labelKey: 'date_any' },
  { value: 'today', labelKey: 'date_today' },
  { value: 'weekend', labelKey: 'date_weekend' },
  { value: '7d', labelKey: 'date_7d' },
  { value: '30d', labelKey: 'date_30d' },
];

// ─── Saved Events ────────────────────────────────────────────────────────────
export const SAVED_EVENTS_PAGE_SIZE = 24;
