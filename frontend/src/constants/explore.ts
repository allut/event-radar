// Explore page: filters, sorts, date presets, query params, and sign-in upsell triggers.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { type Signal } from './feedback.js';

// ─── Explore ─────────────────────────────────────────────────────────────────
// BROWSE_PAGE_SIZE itself is cross-stack (shared/app-config.json → _generated/sharedConstants.ts).
export const EXPLORE_SEARCH_DEBOUNCE_MS = 400;

export type SortOption = 'relevance' | 'date' | 'price' | 'quality';

export const SORT_OPTIONS: { value: SortOption; labelKey: string }[] = [
  { value: 'relevance', labelKey: 'sort_relevance' },
  { value: 'date', labelKey: 'sort_date' },
  { value: 'price', labelKey: 'sort_price' },
  { value: 'quality', labelKey: 'sort_quality' },
];

export type DatePreset = 'any' | 'today' | 'weekend' | '7d' | '30d' | 'custom';

export const DATE_PRESETS: { value: DatePreset; labelKey: string }[] = [
  { value: 'any', labelKey: 'date_any' },
  { value: 'today', labelKey: 'date_today' },
  { value: 'weekend', labelKey: 'date_weekend' },
  { value: '7d', labelKey: 'date_7d' },
  { value: '30d', labelKey: 'date_30d' },
  { value: 'custom', labelKey: 'date_custom' },
];

// ─── Explore ─────────────────────────────────────────────────────────────────
export const EXPLORE_AUDIENCE_ALL = 'all';
export const EXPLORE_AUDIENCE_FOR_YOU = 'foryou';

// Anonymous-visitor sign-in upsell (issue #235). `SignInTrigger` names which
// control opened the modal — the modal's title stays static ("Sign in"), but
// the heading/body copy above MagicLinkForm and the `trigger`/`action`
// analytics params both key off this. Save and thumbs up/down share one copy
// variant; the persistent upsell card's CTA reuses the for_you variant too
// (same "personalize" framing), so only two variants exist for three triggers.
export type SignInTrigger = 'save' | 'thumbs' | 'for_you';
export const SIGN_IN_TRIGGER_FOR_YOU: SignInTrigger = 'for_you';
export const SIGN_IN_TRIGGER_COPY: Record<SignInTrigger, { headingKey: string; bodyKey: string }> = {
  save: { headingKey: 'sign_in_modal_save_heading', bodyKey: 'sign_in_modal_save_body' },
  thumbs: { headingKey: 'sign_in_modal_save_heading', bodyKey: 'sign_in_modal_save_body' },
  for_you: { headingKey: 'sign_in_modal_foryou_heading', bodyKey: 'sign_in_modal_foryou_body' },
};
// What an anonymous visitor's blocked feedback click maps to: the
// SignInTrigger copy variant.
export const SIGNAL_TO_SIGNIN_TRIGGER: Record<Signal, SignInTrigger> = {
  bookmark: 'save',
  like: 'thumbs',
  dislike: 'thumbs',
};

export const SORT_DEFAULT: SortOption = 'relevance';
export const DATE_PRESET_DEFAULT: DatePreset = 'any';
// The preset whose range comes from the user's own from/to dates.
export const DATE_PRESET_CUSTOM: DatePreset = 'custom';
export const DATE_PRESET_TODAY: DatePreset = 'today';
export const DATE_PRESET_WEEKEND: DatePreset = 'weekend';
// Day-window per short-range date preset — keys mirror DATE_PRESETS' values.
export const DATE_PRESET_DAYS: Partial<Record<DatePreset, number>> = {
  '7d': 7,
  '30d': 30,
};
// Fallback window (days) for a DatePreset with no DATE_PRESET_DAYS entry.
export const DATE_PRESET_DAYS_FALLBACK = 30;

// Query-param names shared by parseExploreFilters / exploreFiltersToSearchParams
// / buildExploreApiQuery — one map so the three can't drift out of sync.
export const EXPLORE_PARAM = {
  q: 'q',
  category: 'category',
  vibe: 'vibe',
  date: 'date',
  free: 'free',
  forYou: 'for_you',
  sort: 'sort',
  dateFrom: 'date_from',
  dateTo: 'date_to',
  limit: 'limit',
  offset: 'offset',
} as const;

// Query string of the top bar pulse chip's link — the Explore preset whose
// result set `today_count` (GET /public/counts) counts.
export const EXPLORE_TODAY_SEARCH = `?${EXPLORE_PARAM.date}=${DATE_PRESET_TODAY}`;

// URL state uses a terse '1' flag; the /explore API query uses 'true'/'false'.
export const EXPLORE_URL_FLAG_TRUE = '1';
export const EXPLORE_API_FLAG_TRUE = 'true';

// ─── Top bar ─────────────────────────────────────────────────────────────────
