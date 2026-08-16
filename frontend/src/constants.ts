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
  ORGANIZER_IMAGE_ALLOWED_MIME,
} from './_generated/sharedConstants';

export { LOCALES, APP_VERSION, MAGIC_LINK_EXPIRY_MINUTES, PERSONA_MAX_SELECTABLE, DEFAULT_CURRENCY, SAFE_URL_SCHEMES, SANITIZE_ALLOWED_TAGS, SANITIZE_ALLOWED_ATTR, CATEGORIES, VIBES, BROWSE_PAGE_SIZE, ORGANIZER_IMAGE_ALLOWED_MIME };
export type { PersonaData };

// Re-export PERSONAS under the original name so all import sites are unchanged.
export const PERSONAS: PersonaData[] = PERSONAS_EN;

// Built once at module load — mirrors i18n.ts's PERSONAS_EN_BY_SLUG: avoids a
// linear PERSONAS.find() scan on every persona rendered per component render.
export const PERSONAS_BY_SLUG: Map<string, PersonaData> = new Map(PERSONAS.map((p) => [p.slug, p]));

// ─── React Query ─────────────────────────────────────────────────────────────
export const QUERY_RETRY = 1;
export const QUERY_STALE_TIME = 30_000;

// ─── Local storage keys ──────────────────────────────────────────────────────
// These hold a boolean "signed-in hint", not a credential — the real session
// token lives only in an httpOnly cookie, unreadable by page JS. The hint
// exists purely so isAuthenticated()/isAuthenticatedOrganizer() can answer
// synchronously at first paint. Key names are unchanged from the pre-cookie
// token-storage era so existing localStorage entries/cross-tab listeners
// keep working.
export const SIGNED_IN_HINT_KEY = 'session_token';
export const LOCALE_KEY = 'locale';
// Separate key from SIGNED_IN_HINT_KEY — organizer and consumer sessions are
// two independent auth tracks (own account table, own token salts on the
// backend) that must never be confused for one another. See lib/organizerAuth.ts.
export const ORGANIZER_SIGNED_IN_HINT_KEY = 'organizer_session_token';

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

// ─── Dropdown ────────────────────────────────────────────────────────────────
// useDropdown's default initial-focus target: the popover's first button
// (FacetMenu/SelectMenu). DatePicker overrides this with a selected-day selector.
export const DROPDOWN_DEFAULT_FOCUS_SELECTOR = 'button';

// ─── Settings ────────────────────────────────────────────────────────────────
export const SAVE_MSG_CLEAR_DELAY_MS = 2000;

// ─── External links ──────────────────────────────────────────────────────────
export const GOOGLE_MAPS_SEARCH_URL = 'https://www.google.com/maps/search/?api=1&query=';

// Published contact / privacy (DSAR) address. Single source for the address used
// by the Contact page copy and the legal documents.
export const CONTACT_EMAIL = 'contact@whatsonradar.com';

// Footer social links. Placeholder https URLs (valid so safeUrl() passes) — swap
// for the real handles later. Frontend-only presentation constant, not cross-stack.
export type SocialIcon = 'instagram' | 'facebook' | 'twitter';
export const SOCIAL_LINKS: { label: string; url: string; icon: SocialIcon }[] = [
  { label: 'Instagram', url: 'https://instagram.com/', icon: 'instagram' },
  { label: 'Facebook', url: 'https://facebook.com/', icon: 'facebook' },
  { label: 'X', url: 'https://x.com/', icon: 'twitter' },
];

// ─── Locale ──────────────────────────────────────────────────────────────────
export type LocaleCode = (typeof LOCALES)[number]['code'];
export const LOCALE_EN = 'en' as const;
export const LOCALE_ET = 'et' as const;
export const LOCALE_RU = 'ru' as const;

export function toLocaleCode(locale: string): string {
  return _LOCALE_CODE_MAP[locale] ?? _DEFAULT_LOCALE_CODE;
}

// Estonian is the bare (unprefixed) URL locale; every other locale gets an
// `/en`/`/ru`-style path prefix — see docs/frontend.md's locale-routing
// section (App.tsx's route wrapper, utils.ts's localizedPath/stripLocalePrefix).
export const LOCALE_URL_PREFIX_CODES: string[] = LOCALES
  .map((l) => l.code)
  .filter((code) => code !== LOCALE_ET);

// ─── SEO ─────────────────────────────────────────────────────────────────────
// Absolute production origin — canonical/hreflang/og:url/og:image values are
// meaningless as relative URLs (crawlers and link-unfurlers read them with no
// browser location context), so useSeoMeta always resolves against this.
export const PRODUCTION_ORIGIN = 'https://whatsonradar.com';
// Branded 1200×630 fallback OG image (frontend/public/og-fallback.png),
// served whenever an event has no image_url — same asset for all locales.
export const OG_FALLBACK_IMAGE_PATH = '/og-fallback.png';
// og:description/meta description target length — Google truncates around
// ~155–160 chars; truncateForMeta (utils.ts) cuts at a word boundary under this.
export const SEO_DESCRIPTION_MAX_LENGTH = 157;
// Every LOCALES code plus 'x-default', in the order useSeoMeta emits hreflang
// <link> alternates.
export const SEO_HREFLANG_CODES: string[] = [...LOCALES.map((l) => l.code), 'x-default'];
// Live-audit (issue #54, api/seo-audit.ts + src/lib/seoAudit.ts): sitemap.xml's
// <lastmod> (uniformly the prerender build timestamp — see prerender.ts's
// buildSitemapXml) older than this is treated as a dead prerender cadence.
// 6h backend publish/geocode cadence (LLM_PASS_INTERVAL_HOURS, backend
// app/constants.py) + a 2h buffer.
export const SEO_AUDIT_STALE_THRESHOLD_HOURS = 8;
// GitHub repo the live audit files/updates/closes its failure issue against
// (CLAUDE.md's issue tracker) and the fixed label it searches/tags by.
export const SEO_AUDIT_GITHUB_REPO = 'allut/event-radar';
export const SEO_AUDIT_ISSUE_LABEL = 'seo-audit-failure';
export const GITHUB_API_BASE_URL = 'https://api.github.com';
// Shared-secret header cron-job.org sends on its seo-audit ping, mirroring
// the backend's /internal/tick pattern (docs/backend-ops.md).
export const SEO_AUDIT_TOKEN_HEADER = 'x-internal-token';

// ─── Prerender chaining (issue #79/#81) ────────────────────────────────────
// Round-state marker embedded in the git commit message (VERCEL_GIT_COMMIT_MESSAGE
// has a 2048-byte cap) a chained round reads back on the next round/cron tick —
// see src/lib/prerenderChain.ts.
export const CHAIN_MARKER_PREFIX = 'prerender-chain:';
// Worst-case ~100 minutes wall-clock at the 10-minute render budget per round,
// sized with margin against the throughput research's 5–7-round cold-catch-up
// estimate. Fixed, not dynamic — a pathological catalog can't chain forever.
export const CHAIN_MAX_ROUNDS = 10;
// A `continuing` marker older than this is treated as a crashed/abandoned
// chain rather than an active one, so cron resumes instead of skipping
// forever and a genuinely active chain isn't mistaken for a stale one.
export const CHAIN_STALENESS_TIMEOUT_MINUTES = 30;
// Repo the round-state marker is committed to (issue #83) via the GitHub Git
// Data API — the branch the Vercel Deploy Hook targets lives here. Same repo
// as SEO_AUDIT_GITHUB_REPO (both point at this codebase); kept as a separate
// constant since the two features are unrelated and may diverge.
export const PRERENDER_CHAIN_GITHUB_REPO = 'allut/event-radar';

// ─── Analytics ───────────────────────────────────────────────────────────────
// Matches `/events/:id` (bare or locale-prefixed, e.g. `/en/events/:id`) so
// Vercel Analytics groups all event detail views under one route instead of
// one row per event id — the locale prefix itself is captured (group 1) and
// kept by maskAnalyticsUrl's replacement, so en/et/ru still group separately.
// Applied to a pathname with query/hash already stripped (see
// maskAnalyticsUrl in utils.ts).
const _LOCALE_PREFIX_RE_SRC = `(/(?:${LOCALE_URL_PREFIX_CODES.join('|')}))?`;
export const ANALYTICS_EVENT_PATH_RE = new RegExp(`^${_LOCALE_PREFIX_RE_SRC}/events/\\d+$`);
// Groups every organizer edit-form URL under one analytics row, mirroring
// ANALYTICS_EVENT_PATH_RE above — same rationale, new dynamic route.
export const ANALYTICS_ORGANIZER_EDIT_PATH_RE = new RegExp(`^${_LOCALE_PREFIX_RE_SRC}/organizer/events/\\d+/edit$`);

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

// Keys must match the 14-category taxonomy in shared/app-config.json
// (VALID_CATEGORIES). Values reference --gradient-<slug> tokens in
// index.css's :root — the hex values live there, not here.
export const CATEGORY_GRADIENTS: Record<string, string> = {
  nightlife:    'var(--gradient-nightlife)',
  music:        'var(--gradient-music)',
  theater:      'var(--gradient-theater)',
  exhibitions:  'var(--gradient-exhibitions)',
  workshops:    'var(--gradient-workshops)',
  food_drink:   'var(--gradient-food_drink)',
  sports:       'var(--gradient-sports)',
  networking:   'var(--gradient-networking)',
  literature:   'var(--gradient-literature)',
  family:       'var(--gradient-family)',
  cinema:       'var(--gradient-cinema)',
  alternative:  'var(--gradient-alternative)',
  romantic:     'var(--gradient-romantic)',
};
export const FALLBACK_GRADIENT = 'var(--gradient-fallback)';

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
  organizerEvents: 'organizerEvents',
} as const;

// ─── UI state types ───────────────────────────────────────────────────────────
// Single source for every state-machine string value used across the auth /
// contact / unsubscribe flows and the shared Toast/PageState components — a
// typo in a raw string literal at a call site would silently miss its compare
// or set counterpart; referencing UI_STATE.<key> makes it a compile error instead.
export const UI_STATE = {
  idle: 'idle',
  loading: 'loading',
  success: 'success',
  error: 'error',
  verifying: 'verifying',
  working: 'working',
  resubscribed: 'resubscribed',
} as const;

export type LoginState = typeof UI_STATE.idle | typeof UI_STATE.loading | typeof UI_STATE.success | typeof UI_STATE.error;
export type VerifyState = typeof UI_STATE.verifying | typeof UI_STATE.success | typeof UI_STATE.error;
export type UnsubscribeState = typeof UI_STATE.working | typeof UI_STATE.success | typeof UI_STATE.resubscribed | typeof UI_STATE.error;

export type ToastState =
  | { status: typeof UI_STATE.idle }
  | { status: typeof UI_STATE.success | typeof UI_STATE.error; message: string };
export const TOAST_IDLE: ToastState = { status: UI_STATE.idle };

// Contact form (routes/Contact/Contact.tsx)
export const CONTACT_TEXTAREA_ROWS = 6;

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

// ─── Organizer submission ────────────────────────────────────────────────────
// ORGANIZER_IMAGE_ALLOWED_MIME (re-exported above) is sourced from
// shared/app-config.json, mirroring the backend's IMAGE_UPLOAD_ALLOWED_MIME.
// The server re-validates the MIME type itself and is the actual security
// boundary — this only lets the picker reject an obviously-wrong file before
// spending a network round trip on it.
export const ORGANIZER_IMAGE_ACCEPT = ORGANIZER_IMAGE_ALLOWED_MIME.join(',');
export const ORGANIZER_TEXTAREA_ROWS = 6;
export const ORGANIZER_EVENTS_PAGE_SIZE = 24;

// Organizer submission content-language tabs (EventSubmit.tsx). ET is always
// the base/required slot regardless of the app's default_locale ('en') — the
// platform's canonical language for event content is Estonian — so this is a
// dedicated constant, not derived from LOCALES' app-UI order (en, et, ru).
export type ContentLang = LocaleCode;
export const CONTENT_LANG_ORDER: ContentLang[] = [LOCALE_ET, LOCALE_EN, LOCALE_RU];
export const ORGANIZER_BASE_CONTENT_LANG: ContentLang = LOCALE_ET;

// Per-tab translation-progress marker (EventSubmit.tsx), measured field-by-field
// against the ET base slot — see SegmentedControl's `marker` option.
export type ContentMarkerState = 'empty' | 'partial' | 'matched';

// ─── DatePicker (components/DatePicker) ─────────────────────────────────────
export const CALENDAR_WEEK_START = 1; // Monday — Estonia
export const CALENDAR_WEEKS_SHOWN = 6;
export const CALENDAR_DAYS_PER_WEEK = 7;

// Fixed known-Monday reference date [year, month (0-indexed), day] used to
// derive localized weekday header labels. Held as numeric parts (not an ISO
// string) because `new Date('2024-01-01')` parses as UTC midnight, which lands
// on the previous day in timezones behind UTC.
export const CALENDAR_REFERENCE_MONDAY: readonly [number, number, number] = [2024, 0, 1];

// Time-of-day bounds for the picker's hour/minute fields. MAX_* are derived so
// the day/hour lengths stay the single source of truth.
export const HOURS_PER_DAY = 24;
export const MINUTES_PER_HOUR = 60;
export const MIN_HOUR = 0;
export const MAX_HOUR = HOURS_PER_DAY - 1;
export const MIN_MINUTE = 0;
export const MAX_MINUTE = MINUTES_PER_HOUR - 1;
// Milliseconds in a minute — divides a millisecond timestamp delta down to
// minutes, e.g. for CHAIN_STALENESS_TIMEOUT_MINUTES's staleness comparison.
export const MS_PER_MINUTE = 60 * 1000;
// Milliseconds in an hour — divides a millisecond timestamp delta down to
// hours, e.g. for SEO_AUDIT_STALE_THRESHOLD_HOURS's staleness comparison.
export const MS_PER_HOUR = MINUTES_PER_HOUR * MS_PER_MINUTE;

// Arrow-key increment/decrement step per time field.
export const TIME_STEP_HOURS = 1;
export const TIME_STEP_MINUTES = 5;

// Two digits — the hour/minute fields hold 'HH' / 'mm'.
export const TIME_FIELD_MAX_LENGTH = 2;

// Placeholder for the picker's typeable field. Mirrors the 'YYYY-MM-DDTHH:mm'
// wire format with a space in place of the literal 'T' — see toDisplayDateTime.
export const PICKER_VALUE_PLACEHOLDER = 'YYYY-MM-DD HH:mm';

// ─── Settings ────────────────────────────────────────────────────────────────
// Ordered to match a user's ranked persona picks (see PERSONA_RANK_WEIGHTS on
// the backend) — index i labels the i-th persona in data.personas.
export const RANK_LABEL_KEYS = ['persona_primary', 'persona_secondary', 'persona_tertiary'] as const;

// ─── Saved Events (route-local tab config, mirrors SORT_OPTIONS/DATE_PRESETS) ─
export const SAVED_TABS: { value: Signal; labelKey: string }[] = [
  { value: 'bookmark', labelKey: 'saved_tab_bookmark' },
  { value: 'like', labelKey: 'saved_tab_like' },
  { value: 'dislike', labelKey: 'saved_tab_dislike' },
];

// ─── Landing ─────────────────────────────────────────────────────────────────
export const STEP_KEYS = [
  { title: 'landing_step1_title', body: 'landing_step1_body' },
  { title: 'landing_step2_title', body: 'landing_step2_body' },
  { title: 'landing_step3_title', body: 'landing_step3_body' },
];

// ─── Brand ───────────────────────────────────────────────────────────────────
// Self-contained radar-mark glyph used across TopBar/OrganizerTopBar/Footer/
// Landing/auth cards — no external asset, matches the app's same-origin CSP.
export const BRAND_GLYPH = '◉';
// Organizer dashboard's empty-state icon.
export const ORGANIZER_EMPTY_ICON = '📅';
// Six taxonomy categories placed as radar blips on the Landing hero, positioned
// (top/left %) around the sweep. Labels come from the shared category_* i18n keys.
export const RADAR_BLIPS: { slug: string; top: number; left: number; delay: number }[] = [
  { slug: 'music', top: 20, left: 30, delay: 0 },
  { slug: 'theater', top: 32, left: 72, delay: 0.4 },
  { slug: 'exhibitions', top: 58, left: 80, delay: 0.8 },
  { slug: 'nightlife', top: 76, left: 52, delay: 1.2 },
  { slug: 'workshops', top: 66, left: 32, delay: 1.6 },
  { slug: 'family', top: 40, left: 18, delay: 2.0 },
];

// ─── Explore ─────────────────────────────────────────────────────────────────
export const EXPLORE_AUDIENCE_ALL = 'all';
export const EXPLORE_AUDIENCE_FOR_YOU = 'foryou';
export const SORT_DEFAULT: SortOption = 'relevance';
export const DATE_PRESET_DEFAULT: DatePreset = 'any';
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
// URL state uses a terse '1' flag; the /explore API query uses 'true'/'false'.
export const EXPLORE_URL_FLAG_TRUE = '1';
export const EXPLORE_API_FLAG_TRUE = 'true';

// ─── Organizer submission — price inputs ────────────────────────────────────
export const PRICE_INPUT_MIN = '0';
export const PRICE_INPUT_STEP = '0.01';

// ─── Legal content ───────────────────────────────────────────────────────────
// Extra URL scheme legal docs link out with (contact address), alongside
// SAFE_URL_SCHEMES's https:/mailto:-free defaults.
export const MAILTO_SCHEME = 'mailto';

// ─── Routes ──────────────────────────────────────────────────────────────────
// Every <Route> path, `navigate()` target and `<Link to>` in App.tsx / the
// consumer + organizer nav chrome resolves through this map so the two stay
// in sync. Dynamic segments are builder functions; `*Pattern` entries are the
// React Router path (with `:param` placeholders) used only in App.tsx's
// <Route path> table.
export const ROUTES = {
  login: '/login',
  authVerify: '/auth/verify',
  onboarding: '/onboarding',
  home: '/',
  explore: '/explore',
  saved: '/saved',
  eventDetail: (id: number | string) => `/events/${id}`,
  eventDetailPattern: '/events/:id',
  settings: '/settings',
  unsubscribe: '/unsubscribe',
  privacy: '/privacy',
  terms: '/terms',
  contact: '/contact',
  organizerLogin: '/organizer/login',
  organizerVerify: '/organizer/verify',
  organizerDashboard: '/organizer/dashboard',
  organizerSubmit: '/organizer/submit',
  organizerEventEdit: (id: number | string) => `/organizer/events/${id}/edit`,
  organizerEventEditPattern: '/organizer/events/:id/edit',
} as const;

// ─── API endpoints ───────────────────────────────────────────────────────────
// Every backend request path resolves through this map (or a builder function
// for a dynamic segment) so a typo can't silently desync a call site from the
// route it's meant to hit.
export const API = {
  me: '/users/me',
  authMe: '/auth/me',
  authVerify: '/auth/verify',
  authLogout: '/auth/logout',
  authLogoutAll: '/auth/logout-all',
  authRequestLink: '/auth/request-link',
  organizerAuthLogout: '/organizer/auth/logout',
  organizerAuthVerify: '/organizer/auth/verify',
  organizerAuthRequestLink: '/organizer/auth/request-link',
  onboardingPersona: '/onboarding/persona',
  contact: '/contact',
  feed: '/feed',
  feedback: '/feedback',
  feedbackEvent: (id: number) => `/feedback/${id}`,
  publicShowcase: '/public/showcase',
  emailUnsubscribe: '/email/unsubscribe',
  emailResubscribe: '/email/resubscribe',
  event: (id: number | string) => `/events/${id}`,
  organizerEvents: '/organizer/events',
  organizerEvent: (id: number | string) => `/organizer/events/${id}`,
  organizerEventImage: '/organizer/events/image',
} as const;
