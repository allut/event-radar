// Cross-cutting UI constants: locales, personas, time and calendar units, regexes, breakpoints, delays, site links.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { type PersonaData, PERSONAS_EN } from '../_generated/i18nData.js';
import {
  DEFAULT_LOCALE_CODE as _DEFAULT_LOCALE_CODE,
  LOCALE_CODE_MAP as _LOCALE_CODE_MAP,
  LOCALES,
  LOCALE_EN,
  LOCALE_RU,
} from '../_generated/sharedConstants.js';

// Re-export PERSONAS under the original name so all import sites are unchanged.
export const PERSONAS: PersonaData[] = PERSONAS_EN;

// Built once at module load — mirrors i18n.ts's PERSONAS_EN_BY_SLUG: avoids a
// linear PERSONAS.find() scan on every persona rendered per component render.
export const PERSONAS_BY_SLUG: Map<string, PersonaData> = new Map(PERSONAS.map((p) => [p.slug, p]));

export const LOCALE_KEY = 'locale';

// Magic-link verify token query param (AuthVerify/OrganizerVerify/Unsubscribe).
// Route params that become API path segments must be plain integers — a decoded
// `../..` or `x?y` would otherwise steer a cookie-bearing request at another
// same-origin /api path (OWASP audit L-7).
export const NUMERIC_ROUTE_ID_RE = /^\d+$/;

// ─── Animation ───────────────────────────────────────────────────────────────
export const CARD_ANIMATION_DELAY_STEP_MS = 80;
// Stagger stops growing after this many cards (and restarts every page) so a
// later page's cards are never held invisible for seconds (Big-O audit H6).
export const CARD_ANIMATION_MAX_STEPS = 8;

// ─── Layout ──────────────────────────────────────────────────────────────────
// Matches the `max-width: 640px` breakpoint used across component CSS modules.
export const MOBILE_BREAKPOINT_PX = 640;

// ─── Dropdown ────────────────────────────────────────────────────────────────
// useDropdown's default initial-focus target: the popover's first button
// (FacetMenu/SelectMenu). DatePicker overrides this with a selected-day selector.
export const DROPDOWN_DEFAULT_FOCUS_SELECTOR = 'button';

// ─── Settings ────────────────────────────────────────────────────────────────
export const SAVE_MSG_CLEAR_DELAY_MS = 2000;
// How long a "Copied" button label stays before reverting.
export const COPY_FEEDBACK_MS = 2000;

// ─── External links ──────────────────────────────────────────────────────────
export const GOOGLE_MAPS_SEARCH_URL = 'https://www.google.com/maps/search/?api=1&query=';

// Published contact / privacy (DSAR) address. Single source for the address used
// by the Contact page copy and the legal documents.
export const CONTACT_EMAIL = 'contact@eventradar.ee';

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

// Built once — avoids a linear LOCALES.find() per call at each of its
// duplicated call sites (Big-O audit #5, item 3.4), mirroring PERSONAS_BY_SLUG.
export const LOCALES_BY_CODE: Map<string, (typeof LOCALES)[number]> = new Map(
  LOCALES.map((l) => [l.code, l]),
);
export const COPYRIGHT_YEAR = String(new Date().getFullYear());

export const LOCALE_ET = 'et' as const;

export function toLocaleCode(locale: string): string {
  return _LOCALE_CODE_MAP[locale] ?? _DEFAULT_LOCALE_CODE;
}

// Estonian is the bare (unprefixed) URL locale; every other locale gets an
// `/en`/`/ru`-style path prefix
// (App.tsx's route wrapper; localizedPath/stripLocalePrefix live in lib/urlLocale.ts).
export const LOCALE_URL_PREFIX_CODES: string[] = LOCALES
  .map((l) => l.code)
  .filter((code) => code !== LOCALE_ET);

// Landing showcase plate body truncation (truncateForMeta cuts at a word boundary under this).
export const LANDING_PLATE_BODY_MAX_LENGTH = 140;
// Number of showcase events rendered as plates on Landing.
export const LANDING_SHOWCASE_PLATE_COUNT = 3;
// Landing hero stat-figure count always shown (upcoming count, venue count,
// category count) — furthestYear and cheapest_price add up to two more on top.
export const LANDING_BASE_FIG_COUNT = 3;

export const EUR_SYMBOL = '€';

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

export type ToastState =
  | { status: typeof UI_STATE.idle }
  | { status: typeof UI_STATE.success | typeof UI_STATE.error; message: string };
export const TOAST_IDLE: ToastState = { status: UI_STATE.idle };

// Contact form (routes/Contact/Contact.tsx)
export const CONTACT_TEXTAREA_ROWS = 6;

// Organizer submission content-language tabs (EventSubmit.tsx). ET is always
// the base/required slot regardless of the app's default_locale ('en') — the
// platform's canonical language for event content is Estonian — so this is a
// dedicated constant, not derived from LOCALES' app-UI order (en, et, ru).
export type ContentLang = LocaleCode;
export const CONTENT_LANG_ORDER: ContentLang[] = [LOCALE_ET, LOCALE_EN, LOCALE_RU];

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
// Milliseconds in a day — whole-day differences between two calendar dates.
export const MS_PER_DAY = HOURS_PER_DAY * MS_PER_HOUR;

// Arrow-key increment/decrement step per time field.
export const TIME_STEP_HOURS = 1;
export const TIME_STEP_MINUTES = 5;

// Two digits — the hour/minute fields hold 'HH' / 'mm'.
export const TIME_FIELD_MAX_LENGTH = 2;

// Placeholder for the picker's typeable field. Mirrors the 'YYYY-MM-DDTHH:mm'
// wire format with a space in place of the literal 'T' — see toDisplayDateTime.
export const PICKER_VALUE_PLACEHOLDER = 'YYYY-MM-DD HH:mm';
export const PICKER_DATE_ONLY_PLACEHOLDER = 'YYYY-MM-DD';
// Midnight suffix that lets a date-only value reuse the date-time parser.
export const PICKER_MIDNIGHT_SUFFIX = 'T00:00';
// Upper bound on a skip-disabled-days walk (a year of cells).
export const PICKER_SKIP_LIMIT = 366;

// ─── Settings ────────────────────────────────────────────────────────────────
// Ordered to match a user's ranked persona picks (see PERSONA_RANK_WEIGHTS on
// the backend) — index i labels the i-th persona in data.personas.
export const RANK_LABEL_KEYS = ['persona_primary', 'persona_secondary', 'persona_tertiary'] as const;

// ─── Landing ─────────────────────────────────────────────────────────────────
export const STEP_KEYS = [
  { title: 'landing_step1_title', body: 'landing_step1_body' },
  { title: 'landing_step2_title', body: 'landing_step2_body' },
  { title: 'landing_step3_title', body: 'landing_step3_body' },
];

// ─── Brand ───────────────────────────────────────────────────────────────────
// Plain-text radar glyph, kept for AdminShell and AdminLogin only: the admin
// console's sub-language gets no brand imagery. Everywhere else the brand mark is the
// Dial (components/DialMark).
export const BRAND_GLYPH = '◉';

// ─── Legal content ───────────────────────────────────────────────────────────
// Extra URL scheme legal docs link out with (contact address), alongside
// SAFE_URL_SCHEMES's https:/mailto:-free defaults.
export const MAILTO_SCHEME = 'mailto';
export const CONTACT_MAILTO = `${MAILTO_SCHEME}:${CONTACT_EMAIL}`;
// External regulator links the legal docs cite (identical in every locale).
export const AKI_URL = 'https://www.aki.ee';

// Scroll hysteresis: the bar condenses past 24px and expands back only under
// 4px, so its 18px height change can't oscillate around one threshold.
export const BAR_CONDENSE_SCROLL_PX = 24;
export const BAR_EXPAND_SCROLL_PX = 4;

// ─── Parsing patterns / editor config ────────────────────────────────────────
// datetime-local picker value, `YYYY-MM-DDTHH:mm`.
export const PICKER_VALUE_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;
// ISO calendar date, `YYYY-MM-DD`.
export const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
// `_accented_` word marker inside an i18n string (Landing hero copy).
export const ACCENT_MARKER_RE = /_(.+?)_/;
