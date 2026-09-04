// .js extensions required: this module is also imported (transitively) by
// api/prerender-cadence.ts and api/seo-audit.ts, which Vercel runs as
// unbundled Node ESM.
import { PERSONAS_EN, type PersonaData } from './_generated/i18nData.js';
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
} from './_generated/sharedConstants.js';

export { LOCALES, APP_VERSION, MAGIC_LINK_EXPIRY_MINUTES, PERSONA_MAX_SELECTABLE, DEFAULT_CURRENCY, SAFE_URL_SCHEMES, SANITIZE_ALLOWED_TAGS, SANITIZE_ALLOWED_ATTR, CATEGORIES, VIBES, BROWSE_PAGE_SIZE, ORGANIZER_IMAGE_ALLOWED_MIME };
export const DEFAULT_LOCALE_CODE = _DEFAULT_LOCALE_CODE;
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
// Tri-state theme override, shared across consumer/organizer/admin (one SPA
// bundle, one light palette) — see lib/theme.ts's resolveTheme(). Holds
// "system" | "light" | "dark"; "system"/unset falls through to matchMedia.
export const THEME_PREFERENCE_KEY = 'theme_preference';
// Client-only dismissal flag for the profile nudge banner (#175) — no backend
// field for this, so a stale/cleared browser just re-shows it once.
export const ORGANIZER_PROFILE_NUDGE_DISMISSED_KEY = 'organizer_profile_nudge_dismissed';
// Mirrors backend ORGANIZER_NAME_MAX_LEN (app/constants.py).
export const ORGANIZER_NAME_MAX_LEN = 255;
// Mirrors backend ORGANIZER_VENUE_NAME_MAX_LEN/ORGANIZER_VENUE_ADDRESS_MAX_LEN (app/constants.py).
export const ORGANIZER_VENUE_NAME_MAX_LEN = 255;
export const ORGANIZER_VENUE_ADDRESS_MAX_LEN = 500;

// ─── Auth / magic link ───────────────────────────────────────────────────────
export const AUTH_REDIRECT_DELAY_MS = 600;
// Upper bound on the post-logout 401-redirect suppression window (lib/auth.ts
// isLoggingOut) — comfortably covers the cache-clear race plus Settings'
// AUTH_REDIRECT_DELAY_MS-delayed logout-all flow, without masking a genuine
// session expiry indefinitely if the user never signs back in on this tab.
export const LOGOUT_FLAG_TTL_MS = 10_000;

// Defers pageview tracking to a macrotask so it reads the post-navigation
// location instead of racing react-router's own update (App.tsx GoogleAnalytics).
export const PAGEVIEW_TRACK_DELAY_MS = 0;

// ─── Animation ───────────────────────────────────────────────────────────────
export const CARD_ANIMATION_DELAY_STEP_MS = 80;

// ─── Layout ──────────────────────────────────────────────────────────────────
// Matches the `max-width: 640px` breakpoint used across component CSS modules.
export const MOBILE_BREAKPOINT_PX = 640;
// /admin/pipeline (issue #159) is desktop-only — below this it shows a
// "come back at a desk" gate instead of the trigger console.
export const ADMIN_DESKTOP_BREAKPOINT_PX = 1024;

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
// Vite's built JS/CSS output dir (must match vite.config.ts's `build.assetsDir`,
// which is unset there and so defaults to Vite's own 'assets') — robots.txt
// must explicitly Allow this or Googlebot can't fetch the SPA's own bundle
// when rendering a route (see buildRobotsTxt in scripts/prerender.ts).
export const CRAWLABLE_ASSETS_PATH = '/assets/';
// Site icon asset paths (Google Search Console site-icon requirement) — every
// path Googlebot-Image must be able to fetch, plus favicon.ico which needs
// its own live-audit content-type check (api/seo-audit.ts) since it's the
// one that silently 200s as the SPA shell when missing rather than 404ing.
export const FAVICON_ICO_PATH = '/favicon.ico';
export const CRAWLABLE_ICON_PATHS: string[] = [
  FAVICON_ICO_PATH,
  '/favicon.svg',
  '/icon-96.png',
  '/icon-192.png',
  '/icon-512.png',
  '/apple-touch-icon.png',
  '/site.webmanifest',
];
// <link rel> value index.html emits for the site icon, read back by
// seoValidation.ts's in-build gate as a CSS selector — same
// selector-from-shared-value pattern as CANONICAL_LINK_SELECTOR below.
export const ICON_REL = 'icon';
export const ICON_LINK_SELECTOR = `link[rel="${ICON_REL}"]`;
// og:description/meta description target length — Google truncates around
// ~155–160 chars; truncateForMeta (utils.ts) cuts at a word boundary under this.
export const SEO_DESCRIPTION_MAX_LENGTH = 157;
// Hreflang code for "no specific locale matches" — useSeoMeta (producer)
// and scripts/prerender.ts's buildSitemapXml (producer) both special-case
// this code to resolve to the bare Estonian URL rather than a localizedPath
// lookup; kept as one constant since both sites must agree.
export const SEO_XDEFAULT_CODE = 'x-default';
// Every LOCALES code plus SEO_XDEFAULT_CODE, in the order useSeoMeta emits
// hreflang <link> alternates.
export const SEO_HREFLANG_CODES: string[] = [...LOCALES.map((l) => l.code), SEO_XDEFAULT_CODE];
// robots meta content emitted by useSeoMeta and checked by seoValidation.ts's
// in-build validation gate (issue #53) — one pair of constants so the two
// can't silently drift.
export const ROBOTS_INDEX_FOLLOW = 'index, follow';
export const ROBOTS_NOINDEX = 'noindex';
// <link rel> value useSeoMeta emits for the canonical URL, read back by both
// seoValidation.ts (in-build gate) and scripts/prerender.ts (content-ready
// wait selector) as a CSS selector.
export const CANONICAL_REL = 'canonical';
export const CANONICAL_LINK_SELECTOR = `link[rel="${CANONICAL_REL}"]`;
// <script type> SeoTags renders its JSON-LD payload under, read back by
// seoValidation.ts and scripts/prerender.ts's embedChangeMarker as a CSS
// selector — one pair so a type-attribute typo can't silently break either.
export const JSONLD_SCRIPT_TYPE = 'application/ld+json';
export const JSONLD_SCRIPT_SELECTOR = `script[type="${JSONLD_SCRIPT_TYPE}"]`;
// Price marker EventDetail.tsx renders on the event-detail page, read back
// by seoValidation.ts's in-build staleness gate (issue #53) — price isn't
// part of the JSON-LD payload (issue #46 defers AggregateOffer), so it needs
// its own marker. One shared map so an attribute-name typo on either side
// can't silently break the gate.
export const EVENT_PRICE_TESTID = 'event-price';
export const EVENT_PRICE_SELECTOR = `[data-testid="${EVENT_PRICE_TESTID}"]`;
export const PRICE_DATA_ATTR = {
  min: 'data-price-min',
  max: 'data-price-max',
  currency: 'data-currency',
  hasFreeTier: 'data-has-free-tier',
} as const;
// Prerender readiness markers for /explore (issue #236) — same family as
// PRICE_DATA_ATTR above. `indexable` (useSeoMeta) only flips true on a
// successful query, which is what the canonical-link wait selector every
// other prerender target uses relies on — but /explore has a real error
// path (a query that fails outright), where Playwright must still stop
// waiting rather than time out. These two markers decouple "the page is
// done loading, snapshot it" (PRERENDER_READY) from "is it indexable"
// (still driven by useSeoMeta/indexable alone) and let the render script
// tell an error state apart from a genuine (possibly zero-row) success.
export const PRERENDER_READY_ATTR = 'data-prerender-ready';
export const PRERENDER_READY_SELECTOR = `[${PRERENDER_READY_ATTR}="true"]`;
export const PRERENDER_ERROR_ATTR = 'data-prerender-error';
export const PRERENDER_ERROR_SELECTOR = `[${PRERENDER_ERROR_ATTR}="true"]`;
// sitemap.xml's dist-relative filename (prerender.ts writes it, api/seo-audit.ts
// fetches it) and its absolute-origin-relative path (referenced from
// robots.txt's Sitemap directive and the live audit's production fetch).
export const SITEMAP_FILENAME = 'sitemap.xml';
export const SITEMAP_PATH = `/${SITEMAP_FILENAME}`;
// Live-audit (issue #54, api/seo-audit.ts + src/lib/seoAudit.ts): sitemap.xml's
// <lastmod> (target.updatedAt when available, else the build timestamp — see
// prerender.ts's buildSitemapXml) older than this is treated as a dead prerender cadence.
// 6h backend publish/geocode cadence (LLM_PASS_INTERVAL_HOURS, backend
// app/constants.py) + a 2h buffer.
export const SEO_AUDIT_STALE_THRESHOLD_HOURS = 8;
// GitHub repo the live audit files/updates/closes its failure issue against
// (CLAUDE.md's issue tracker) and the fixed label it searches/tags by.
export const SEO_AUDIT_GITHUB_REPO = 'allut/event-radar';
export const SEO_AUDIT_ISSUE_LABEL = 'seo-audit-failure';
export const GITHUB_API_BASE_URL = 'https://api.github.com';
// Shared-secret header cron-job.org sends on its seo-audit ping, mirroring
// the backend's /internal/tick pattern (docs/backend-ops.md). Distinct from
// PRERENDER_CADENCE_TOKEN_HEADER and the backend's own X-Internal-Token: the
// vercel.json rewrite excludes both of this function's path variants by
// exact-anchored negative lookahead, so any variant that doesn't match exactly
// gets proxied to Render carrying this header — a shared name with the
// backend's header would leak SEO_AUDIT_TOKEN into that proxied request.
export const SEO_AUDIT_TOKEN_HEADER = 'x-seo-audit-token';

// ─── Prerender chaining (issue #79/#81) ────────────────────────────────────
// Round-state marker embedded in the git commit message (VERCEL_GIT_COMMIT_MESSAGE
// has a 2048-byte cap) a chained round reads back on the next round/cron tick —
// see src/lib/prerenderChain.ts.
export const CHAIN_MARKER_PREFIX = 'prerender-chain:';
// RoundMarker.status values (src/lib/prerenderChain.ts's producer,
// scripts/prerender.ts's consumer) — mirrors UI_STATE's pattern so a typo on
// either side of the chaining state machine is a compile error, not a
// silently-missed compare.
export const ROUND_STATUS = {
  continuing: 'continuing',
  done: 'done',
} as const;
// Backend event/report status values compared against in the admin console —
// mirrors ROUND_STATUS/UI_STATE's pattern so a typo is a compile error.
export const EVENT_STATUS = {
  published: 'published',
} as const;
export const REPORT_STATUS = {
  open: 'open',
} as const;
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
// Production/Vercel-git-connected branch the round-state marker is pushed to
// and the cadence gate (issue #92, api/prerender-cadence.ts) reads its tip
// commit from.
export const PRERENDER_CADENCE_GIT_BRANCH = 'release';
// Shared-secret header cron-job.org sends on its prerender-cadence ping
// (issue #92). Distinct name from SEO_AUDIT_TOKEN_HEADER and the backend's own
// X-Internal-Token — see that constant's comment for why a shared name is a
// cross-service secret-disclosure risk via the vercel.json rewrite exclusion.
export const PRERENDER_CADENCE_TOKEN_HEADER = 'x-prerender-cadence-token';

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

// GA4 loader src — googletagmanager.com only, matching the CSP script-src
// widened for it (frontend/vercel.json, see docs/security.md).
export const GTAG_SCRIPT_SRC = 'https://www.googletagmanager.com/gtag/js';

// GA4 custom event names for the public-Explore + sign-in-upsell flow (issue
// #235). Event/param names are centralized here rather than inlined at call
// sites, per this file's Code Quality Rule.
export const ANALYTICS_EVENTS = {
  landingBrowseCtaClick: 'landing_browse_cta_click',
  landingEmailSubmit: 'landing_email_submit',
  exploreView: 'explore_view',
  exploreFilterChange: 'explore_filter_change',
  exploreCardClick: 'explore_card_click',
  exploreUpsellClick: 'explore_upsell_click',
  signinModalOpen: 'signin_modal_open',
  signinModalDismiss: 'signin_modal_dismiss',
  signinModalSubmit: 'signin_modal_submit',
} as const;

// ─── Reports (event_reports, issue #128) ────────────────────────────────────
// Mirrors the backend's VALID_REPORT_REASONS order (app/constants.py) — labels/
// descriptions come from the report_reason_<slug>(_description) i18n keys.
export const REPORT_REASON_OTHER = 'other';
export const REPORT_REASONS: { value: string; labelKey: string; descriptionKey: string }[] = [
  { value: 'spam_or_scam', labelKey: 'report_reason_spam_or_scam', descriptionKey: 'report_reason_spam_or_scam_description' },
  { value: 'sexual_or_explicit', labelKey: 'report_reason_sexual_or_explicit', descriptionKey: 'report_reason_sexual_or_explicit_description' },
  { value: 'not_an_event', labelKey: 'report_reason_not_an_event', descriptionKey: 'report_reason_not_an_event_description' },
  { value: 'hateful_or_violent', labelKey: 'report_reason_hateful_or_violent', descriptionKey: 'report_reason_hateful_or_violent_description' },
  { value: 'misleading_info', labelKey: 'report_reason_misleading_info', descriptionKey: 'report_reason_misleading_info_description' },
  { value: 'event_ended_or_cancelled', labelKey: 'report_reason_event_ended_or_cancelled', descriptionKey: 'report_reason_event_ended_or_cancelled_description' },
  { value: 'wrong_location', labelKey: 'report_reason_wrong_location', descriptionKey: 'report_reason_wrong_location_description' },
  { value: REPORT_REASON_OTHER, labelKey: 'report_reason_other', descriptionKey: 'report_reason_other_description' },
];
// Mirrors the backend's REPORT_DETAIL_MAX_CHARS (app/constants.py) — client-side
// validation only, the server re-validates and is the real boundary.
export const REPORT_DETAIL_MAX_CHARS = 500;
export const REPORT_DETAIL_TEXTAREA_ROWS = 4;

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
  counts: 'counts',
  organizerEvents: 'organizerEvents',
  organizerProfile: 'organizerProfile',
  organizerVenues: 'organizerVenues',
  adminCounts: 'adminCounts',
  adminReports: 'adminReports',
  adminSubmissions: 'adminSubmissions',
  adminDedupGroups: 'adminDedupGroups',
  adminEventDetail: 'adminEventDetail',
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

// AuthCard's three presentational kinds — shared by AuthVerify and
// OrganizerVerify, both magic-link verify flows that map the same
// three-state machine onto AuthCard's spinner/check/error rendering.
export type AuthCardKind = 'pending' | 'success' | 'error';
export const VERIFY_STATE_TO_KIND: Record<VerifyState, AuthCardKind> = {
  [UI_STATE.verifying]: 'pending',
  [UI_STATE.success]: 'success',
  [UI_STATE.error]: 'error',
};

// Contact form (routes/Contact/Contact.tsx)
export const CONTACT_TEXTAREA_ROWS = 6;

// Admin console (routes/AdminLogin, components/AdminQueueActionPanel)
export const TOTP_CODE_LENGTH = 6;
export const ADMIN_NOTE_TEXTAREA_ROWS = 3;

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

export type DatePreset = 'any' | 'today' | 'weekend' | '7d' | '30d' | 'custom';

export const DATE_PRESETS: { value: DatePreset; labelKey: string }[] = [
  { value: 'any', labelKey: 'date_any' },
  { value: 'today', labelKey: 'date_today' },
  { value: 'weekend', labelKey: 'date_weekend' },
  { value: '7d', labelKey: 'date_7d' },
  { value: '30d', labelKey: 'date_30d' },
  { value: 'custom', labelKey: 'date_custom' },
];

// ─── Saved Events ────────────────────────────────────────────────────────────
export const SAVED_EVENTS_PAGE_SIZE = 24;

// ─── Admin: dedup groups (mirrors backend's ADMIN_DEDUP_GROUPS_PAGE_SIZE) ───
export const ADMIN_DEDUP_GROUPS_PAGE_SIZE = 50;

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
export const SIGN_IN_TRIGGER_COPY: Record<SignInTrigger, { headingKey: string; bodyKey: string }> = {
  save: { headingKey: 'sign_in_modal_save_heading', bodyKey: 'sign_in_modal_save_body' },
  thumbs: { headingKey: 'sign_in_modal_save_heading', bodyKey: 'sign_in_modal_save_body' },
  for_you: { headingKey: 'sign_in_modal_foryou_heading', bodyKey: 'sign_in_modal_foryou_body' },
};
// Index in the (0-based) results array after which the persistent upsell
// card is inserted for anonymous visitors — tuned by eye against the
// responsive auto-fill grid (Page.module.css's .cardGrid), which has no
// fixed column count to compute an exact row boundary from.
export const EXPLORE_UPSELL_CARD_POSITION = 5;

// explore_filter_change's `filter_type` param (issue #235) is a fixed
// vocabulary — the facet name, or which other control changed — centralized
// here rather than inlined as string literals at each Explore.tsx call site.
export const EXPLORE_FILTER_TYPES = {
  category: 'category',
  vibe: 'vibe',
  date: 'date',
  free: 'free',
  sort: 'sort',
  forYou: 'for_you',
  q: 'q',
} as const;
export type ExploreFilterType = (typeof EXPLORE_FILTER_TYPES)[keyof typeof EXPLORE_FILTER_TYPES];
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

// Query-param name for the report-notification email's deep link into
// AdminReports — carries the reported event's id so the matching row's
// detail panel auto-opens on load.
export const ADMIN_REPORTS_PARAM = {
  report: 'report',
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
export const CONTACT_MAILTO = `${MAILTO_SCHEME}:${CONTACT_EMAIL}`;

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
  organizerSettings: '/organizer/settings',
  organizerEventEdit: (id: number | string) => `/organizer/events/${id}/edit`,
  organizerEventEditPattern: '/organizer/events/:id/edit',
  // Admin console (issue #154) — registered entirely outside App.tsx's
  // ROUTE_DEFS/locale-prefix loop (see AdminApp), so these are never
  // locale-prefixed and never appear in NAV_ITEMS.
  adminLogin: '/admin/login',
  adminBase: '/admin',
  adminSplat: '/admin/*',
  adminEventsSplat: '/admin/events/*',
  adminDashboard: '/admin',
  adminReports: '/admin/reports',
  adminSubmissions: '/admin/submissions',
  adminEventDetail: (id: number | string) => `/admin/events/${id}`,
  adminEventDetailPattern: '/admin/events/:id',
  // Path-prefix form of adminEventDetail, for AdminApp's manual pathname
  // dispatch (see that file's comment on why it can't use nested <Routes>).
  adminEventDetailPrefix: '/admin/events/',
  adminPipeline: '/admin/pipeline',
  adminDedup: '/admin/dedup',
} as const;

// The admin console's persistent nav — the 5 clickable screens of the
// ticket's 7 (the other 2, /admin/login and /admin/events/:id, are reached
// by URL/click-through, not nav links). Always lists all 5, even before
// later tickets build the still-stubbed ones (issue #154). No i18n: the
// console is an internal operator tool, not user-facing product surface.
export const ADMIN_NAV_ITEMS = [
  { route: ROUTES.adminDashboard, label: 'Dashboard' },
  { route: ROUTES.adminReports, label: 'Reports' },
  { route: ROUTES.adminSubmissions, label: 'Submissions' },
  { route: ROUTES.adminPipeline, label: 'Pipeline' },
  { route: ROUTES.adminDedup, label: 'Dedup groups' },
] as const;

// AdminEventDetail's tab strip — same no-i18n exemption as ADMIN_NAV_ITEMS.
export const ADMIN_EVENT_DETAIL_TABS = ['Overview', 'Classification', 'Dedup & reports', 'Raw payload'] as const;

// Parallel signed-in hint to SIGNED_IN_HINT_KEY/ORGANIZER_SIGNED_IN_HINT_KEY
// (see lib/adminAuth.ts) — a third, independent auth track's localStorage flag.
export const ADMIN_SIGNED_IN_HINT_KEY = 'admin_session_token';

// The signed-in primary nav — same four {route, labelKey} pairs rendered by
// both TopBar (desktop) and MobileMenu (mobile), kept in one place so they
// can't drift out of sync.
export const NAV_ITEMS = [
  { route: ROUTES.home, labelKey: 'nav_daily5' },
  { route: ROUTES.explore, labelKey: 'nav_explore' },
  { route: ROUTES.saved, labelKey: 'nav_saved' },
  { route: ROUTES.settings, labelKey: 'nav_settings' },
] as const;

// The three theme options rendered by both ThemeSelector (desktop) and
// MobileMenu (mobile), kept in one place so they can't drift out of sync —
// mirrors NAV_ITEMS' {value, labelKey} pattern above.
export const THEME_OPTIONS = [
  { value: 'system', labelKey: 'theme_system' },
  { value: 'light', labelKey: 'theme_light' },
  { value: 'dark', labelKey: 'theme_dark' },
] as const;

// Prefix every backend request is proxied under (see vercel.json's rewrite
// rule, which is keyed on this same string) — api/client.ts's fetch wrapper
// and NDJSON stream path both prepend it.
export const API_BASE = '/api';

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
  organizerAuthLogoutAll: '/organizer/auth/logout-all',
  organizerAuthVerify: '/organizer/auth/verify',
  organizerAuthRequestLink: '/organizer/auth/request-link',
  onboardingPersona: '/onboarding/persona',
  contact: '/contact',
  feed: '/feed',
  feedback: '/feedback',
  feedbackEvent: (id: number) => `/feedback/${id}`,
  feedbackEvents: '/feedback/events',
  publicShowcase: '/public/showcase',
  publicCounts: '/public/counts',
  emailUnsubscribe: '/email/unsubscribe',
  emailResubscribe: '/email/resubscribe',
  event: (id: number | string) => `/events/${id}`,
  organizerEvents: '/organizer/events',
  organizerEvent: (id: number | string) => `/organizer/events/${id}`,
  organizerEventImage: '/organizer/events/image',
  organizerProfile: '/organizer/profile',
  organizerVenues: '/organizer/venues',
  organizerVenue: (id: number | string) => `/organizer/venues/${id}`,
  reports: '/reports',
  adminAuthLogin: '/admin/auth/login',
  adminAuthLogout: '/admin/auth/logout',
  adminAuthMe: '/admin/auth/me',
  adminCounts: '/admin/counts',
  adminReports: '/admin/reports',
  adminReportResolve: (id: number) => `/admin/reports/${id}/resolve`,
  adminReportTakedown: (id: number) => `/admin/reports/${id}/takedown`,
  adminSubmissions: '/admin/submissions',
  adminDedupGroups: '/admin/dedup/groups',
  adminSubmissionApprove: (id: number) => `/admin/submissions/${id}/approve`,
  adminSubmissionRetract: (id: number) => `/admin/submissions/${id}/retract`,
  adminEventDetail: (id: number | string) => `/admin/events/${id}`,
  adminIngestAll: '/admin/ingest',
  adminIngestSource: (slug: string) => `/admin/ingest/${slug}`,
  adminDedupRun: '/admin/dedup',
  adminClassify: '/admin/classify',
  adminPublish: '/admin/publish',
  adminGeocode: '/admin/geocode',
  adminRefetch: '/admin/refetch',
  adminSyncOrganizers: '/admin/sync-organizers',
  adminCleanup: (dryRun: boolean) => `/admin/cleanup?dry_run=${dryRun}`,
  adminBuildFeeds: '/admin/build-feeds',
  adminSendDigests: (dryRun: boolean) => `/admin/send-digests?dry_run=${dryRun}`,
  adminPipelineRun: (dryRun: boolean) => `/admin/pipeline/run?dry_run=${dryRun}`,
} as const;

// /admin/pipeline (issue #159) — one row per job-trigger endpoint. The admin
// console is English-only/internal, so labels/hints are plain strings, not
// i18n keys (matches AdminReports/AdminSubmissions' own inline copy).
export type AdminTriggerId =
  | 'ingest_all'
  | 'ingest_source'
  | 'dedup'
  | 'classify'
  | 'publish'
  | 'geocode'
  | 'refetch'
  | 'sync_organizers'
  | 'cleanup'
  | 'build_feeds'
  | 'send_digests'
  | 'pipeline_run';

export interface AdminPipelineTrigger {
  id: AdminTriggerId;
  label: string;
  hint: string;
  dryRunCapable?: boolean;
  needsSlug?: boolean;
  /** pipeline_run only — the stage order PipelineRunBreakdown renders through. */
  stages?: string[];
  /** Set only on cleanup/send_digests/pipeline_run (issue #160) — a real
   * (dry_run=false) run of these requires the typed-confirmation modal,
   * naming this endpoint's specific consequence. */
  dangerCopy?: string;
}

export const ADMIN_PIPELINE_TRIGGERS: AdminPipelineTrigger[] = [
  { id: 'ingest_all', label: 'Ingest all sources', hint: 'Pull raw events from every enabled source' },
  { id: 'ingest_source', label: 'Ingest one source', hint: 'Pull raw events from a single source by slug', needsSlug: true },
  { id: 'dedup', label: 'Dedup pass', hint: 'Drain the dedup backlog' },
  { id: 'classify', label: 'Classify', hint: 'LLM classification of pending events' },
  { id: 'publish', label: 'Publish', hint: 'Promote qualifying events to published' },
  { id: 'geocode', label: 'Geocode', hint: 'Backfill lat/lng from venue addresses' },
  { id: 'refetch', label: 'Refetch details', hint: 'Re-fetch source detail pages' },
  { id: 'sync_organizers', label: 'Sync organizers', hint: 'Discover new organizers, flag stale ones' },
  {
    id: 'cleanup',
    label: 'Cleanup',
    hint: 'Prune satellite tables past retention',
    dryRunCapable: true,
    dangerCopy: 'This deletes rows from satellite tables (raw events, feedback, expired sessions, and more). Events themselves are never deleted, but this cannot be undone.',
  },
  { id: 'build_feeds', label: 'Build feeds', hint: 'Build Daily 5 for every active user' },
  {
    id: 'send_digests',
    label: 'Send digests',
    hint: 'Send the daily email digest',
    dryRunCapable: true,
    dangerCopy: 'This sends a real email to every opted-in user right now, not a test send.',
  },
  {
    id: 'pipeline_run',
    label: 'Run full pipeline',
    hint: 'All seven stages in order',
    dryRunCapable: true,
    stages: ['sync_organizers', 'ingest', 'dedup', 'classify', 'publish', 'build_feeds', 'send_digests'],
    dangerCopy: 'This runs the full pipeline end to end, including LLM classification (real spend) and a real digest send to every opted-in user.',
  },
];

// pipeline_run's bespoke stage-by-stage breakdown (PipelineRunBreakdown,
// issue #161) — display label per entry in ADMIN_PIPELINE_TRIGGERS'
// pipeline_run.stages, keyed by the same stage names admin.py streams.
export const ADMIN_PIPELINE_STAGE_LABELS: Record<string, string> = {
  sync_organizers: 'Sync organizers',
  ingest: 'Ingest',
  dedup: 'Dedup',
  classify: 'Classify',
  publish: 'Publish',
  build_feeds: 'Build feeds',
  send_digests: 'Send digests',
};
