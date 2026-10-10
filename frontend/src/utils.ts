import DOMPurify from 'dompurify';
import { type InfiniteData, type QueryClient } from '@tanstack/react-query';
import { api, ApiError } from './api/client';
import { API, NUMERIC_ROUTE_ID_RE, QUERY_KEYS, CARD_ANIMATION_DELAY_STEP_MS, CARD_ANIMATION_MAX_STEPS, ISO_DATE_RE, PICKER_VALUE_RE, SIGNAL_CLICK_EXTERNAL, CATEGORY_GRADIENTS, CLAIM_JUSTIFICATION_REQUIRED_ERROR, FALLBACK_GRADIENT, EUR_SYMBOL, DEFAULT_CURRENCY, GOOGLE_MAPS_SEARCH_URL, type Signal, toLocaleCode, SAFE_URL_SCHEMES, SANITIZE_ALLOWED_TAGS, SANITIZE_ALLOWED_ATTR, SIGNAL_TO_CLASS, BROWSE_PAGE_SIZE, CATEGORIES, VIBES, type DatePreset, type SortOption, ANALYTICS_EVENT_PATH_RE, ANALYTICS_ORGANIZER_EDIT_PATH_RE, CALENDAR_WEEK_START, CALENDAR_WEEKS_SHOWN, CALENDAR_DAYS_PER_WEEK, CALENDAR_REFERENCE_MONDAY, MAX_HOUR, MAX_MINUTE, DATE_PRESET_DAYS, DATE_PRESET_DAYS_FALLBACK, DATE_PRESET_DEFAULT, DATE_PRESET_TODAY, DATE_PRESET_WEEKEND, EXPLORE_PARAM, EXPLORE_URL_FLAG_TRUE, EXPLORE_API_FLAG_TRUE, SORT_DEFAULT, TIME_FIELD_MAX_LENGTH, LOCALES, LOCALES_BY_CODE, LOCALE_EN, LOCALE_ET, LOCALE_RU, type LocaleCode, DEFAULT_LOCALE_CODE, MS_PER_HOUR, HOURS_PER_DAY, TALLINN_TZ } from './constants';
import { t, ti } from './i18n';
import { stripLocalePrefix, localizedPath, localeFromPath, localizedTo } from './lib/urlLocale';

export { stripLocalePrefix, localizedPath, localeFromPath, localizedTo };

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}

/** Display label for a locale/content-language code, falling back to the upper-cased code. */
/** A route param safe to interpolate into an API path: plain digits only, else
 * undefined (callers then leave their query disabled and render the error state). */
export function numericRouteId(raw: string | undefined): string | undefined {
  return raw !== undefined && NUMERIC_ROUTE_ID_RE.test(raw) ? raw : undefined;
}

export function localeLabel(code: string): string {
  return LOCALES_BY_CODE.get(code)?.label ?? code.toUpperCase();
}

/** "Field (LANG)" label for a translated form field. */
export function localizedFieldLabel(key: string, locale: string, lang: string): string {
  return ti('organizer_field_lang_suffix', locale, { field: t(key, locale), lang: localeLabel(lang) });
}

/** Title + description, one slot per content language — the shape shared by the
 * organizer-submit and claim-edit form states. */
export interface LocalizedTextFields {
  title: string;
  titleEn: string;
  titleRu: string;
  description: string;
  descriptionEn: string;
  descriptionRu: string;
}

/** Splits a `*_localized` record into its [et, en, ru] slots. The ET slot falls
 * back to `base` (the display-locale-resolved field) for events that predate
 * localized maps; EN/RU are blank when absent. */
export function localizedTriplet(
  record: Record<string, string> | null | undefined,
  base: string | null | undefined,
): [string, string, string] {
  const loc = record ?? {};
  return [loc[LOCALE_ET] ?? base ?? '', loc[LOCALE_EN] ?? '', loc[LOCALE_RU] ?? ''];
}

export function isValidLocale(code: string | undefined): code is LocaleCode {
  return !!code && LOCALES.some((l) => l.code === code);
}

/** `<page title> | <brand>`, the `<title>`/SEO-meta convention every route uses. */
export function titleWithBrand(pageTitle: string, locale: string): string {
  return `${pageTitle} | ${t('brand', locale)}`;
}

/** Appends `key=value` to a path/query string — `?` when `path` has no query
 * string yet, `&` otherwise. `withLocaleQuery` below is this same shape,
 * fixed to the `locale` key. */
export function withQueryParam(path: string, key: string, value: string): string {
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}${key}=${encodeURIComponent(value)}`;
}

/** Appends `locale=` to a path/query string every data-fetching route sends
 * to the API — `?` when `path` has no query string yet, `&` otherwise. */
export function withLocaleQuery(path: string, locale: string): string {
  return withQueryParam(path, 'locale', locale);
}

/** A caught error's server-provided message when it's an ApiError, else a
 * caller-supplied fallback — the `err instanceof ApiError ? err.message :
 * <fallback>` ternary repeated at every mutation's onError. */
export function apiErrorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** True when a claim-creation failure is specifically "needs a justification"
 * (#428's Series-claim gate) — the one claim-creation error ClaimEventPicker/
 * ClaimStrip react to structurally (reveal the reason field) rather than
 * just display, so both share this check instead of duplicating the
 * ApiError/message comparison. */
export function isClaimJustificationRequiredError(err: unknown): boolean {
  return err instanceof ApiError && err.message === CLAIM_JUSTIFICATION_REQUIRED_ERROR;
}

/** { value, label } options for every CATEGORIES slug, localized — callers
 * still wrap the call in their own useMemo(() => categoryOptions(locale),
 * [locale]) to avoid rebuilding the 14-option list (+14 t() lookups) on
 * every render. */
export function categoryOptions(locale: string): { value: string; label: string }[] {
  return CATEGORIES.map((slug) => ({ value: slug, label: t(`category_${slug}`, locale) }));
}

/** Toggle `value` in a capped pick list: removes it when present, appends it
 * when absent and there is room, otherwise returns the list unchanged. Shared
 * by the organizer submit form and the claim edit's category pickers. */
export function toggleCapped(list: string[], value: string, max: number): string[] {
  if (list.includes(value)) return list.filter((v) => v !== value);
  return list.length < max ? [...list, value] : list;
}

/** Same shape as categoryOptions, for VIBES. */
export function vibeOptions(locale: string): { value: string; label: string }[] {
  return VIBES.map((slug) => ({ value: slug, label: t(`vibe_${slug}`, locale) }));
}

/** useInfiniteQuery's getNextPageParam cursor for every offset-paginated
 * list (admin queues, claim events; Explore/Saved use nextKeysetParam): the next offset when the page
 * says there's more, else undefined to stop paging. `itemCount` is the
 * caller's page-array length (`events.length`/`groups.length` — the key
 * differs per response shape, so it's passed rather than read off `page`). */
export function nextOffsetParam(
  page: { has_more: boolean; offset: number },
  itemCount: number,
): number | undefined {
  return page.has_more ? page.offset + itemCount : undefined;
}

/** A useInfiniteQuery page param for lists the backend keyset-paginates
 * (Explore's date sort, Saved Events): `cursor` is the server's opaque
 * `next_cursor` and wins when present; `offset` is the fallback for the
 * sorts that stay on OFFSET (relevance/price/quality). */
export interface KeysetPageParam {
  offset: number;
  cursor?: string;
}

export const FIRST_KEYSET_PAGE: KeysetPageParam = { offset: 0 };

export function nextKeysetParam(
  page: { has_more: boolean; offset: number; next_cursor?: string | null },
  itemCount: number,
): KeysetPageParam | undefined {
  if (!page.has_more) return undefined;
  return { offset: page.offset + itemCount, cursor: page.next_cursor ?? undefined };
}

/** True for any organizer-portal route, with or without a `/:locale` prefix
 * (e.g. `/organizer/dashboard`, `/ru/organizer/settings`) — used to pick the
 * right chrome/links (e.g. Footer's Contact link) by current portal rather
 * than by auth state alone. */
export function isOrganizerPortalPath(pathname: string): boolean {
  return /\/organizer(\/|$)/.test(pathname);
}

/** Reshapes a URL before it's forwarded to Google Analytics: strips the query string and
 * hash (query params can carry sensitive values — the /auth/verify magic-link token, an
 * /explore free-text search — that must never reach a third-party analytics vendor) and
 * groups `/events/:id` under one row instead of one per event id. */
export function maskAnalyticsUrl(url: string): string {
  const pathname = url.split(/[?#]/)[0];
  return pathname
    .replace(ANALYTICS_EVENT_PATH_RE, '$1/events/[id]')
    .replace(ANALYTICS_ORGANIZER_EDIT_PATH_RE, '$1/organizer/events/[id]/edit');
}

/** Defense-in-depth render guard: only allow the given URL schemes (http(s) by
 * default) into href/src attributes. The backend already drops non-http(s)
 * schemes at ingest time (safe_external_url) for scraped event data, but this
 * protects against any other path that might surface a raw URL. Callers with
 * a legitimately wider scheme set (e.g. LegalPage's first-party `mailto:`
 * links) can pass their own allowlist rather than widening the default. */
export function safeUrl(url: string | null | undefined, allowedSchemes: ReadonlySet<string> = SAFE_URL_SCHEMES): string | null {
  if (!url) return null;
  try {
    const proto = new URL(url).protocol.replace(/:$/, '');
    return allowedSchemes.has(proto) ? url : null;
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

/** Strips all HTML tags from a sanitized-but-still-HTML description field,
 * for plain-text teaser contexts (card snippets, meta descriptions) that
 * must not render markup. */
export function stripHtmlToText(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
}

/** True if a RichTextEditor field has real text — Tiptap's "empty" state
 * serializes as `<p></p>`, not `''`, so a plain `.trim()` on the raw HTML
 * would treat that as non-empty. */
export function hasHtmlContent(html: string): boolean {
  return stripHtmlToText(html).trim().length > 0;
}

// Formatters below are built once per locale and cached at module scope —
// Intl constructors are comparatively expensive, and EventCard (rendered N-up
// in a grid) calls these per card per render.
const DTF_HOUR_MINUTE: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', hour12: false };

// Two flavours of every formatter: `tallinn` pins real instants (event ISO
// timestamps, "now") to Europe/Tallinn so a viewer in any timezone — and the
// prerender host — sees Tallinn wall-clock time; the default flavour formats
// wall-clock Dates built from local components (pickers, parseISODateLocal),
// which must NOT be shifted into another zone.
const HOUR_MINUTE_FORMATTERS = new Map<string, Intl.DateTimeFormat>();
function hourMinuteFormatter(locale: string, tallinn = false): Intl.DateTimeFormat {
  const localeCode = toLocaleCode(locale);
  const key = tallinn ? `${localeCode}|tallinn` : localeCode;
  let fmt = HOUR_MINUTE_FORMATTERS.get(key);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(localeCode, tallinn ? { ...DTF_HOUR_MINUTE, timeZone: TALLINN_TZ } : DTF_HOUR_MINUTE);
    HOUR_MINUTE_FORMATTERS.set(key, fmt);
  }
  return fmt;
}

export function formatHourMinute(iso: string, locale: string): string {
  return hourMinuteFormatter(locale, true).format(new Date(iso));
}

export function trackExternalClick(eventId: number): void {
  api.post(API.feedback, { event_id: eventId, signal: SIGNAL_CLICK_EXTERNAL }).catch(() => undefined);
}

/** Copy text to the clipboard. Returns true on success, false if the
 * clipboard API is unavailable or blocked (caller surfaces the failure). */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Shares a page (native share sheet, falling back to a clipboard copy) — the
 * logic behind EventDetail's and EventCard's Share menu item, factored out so
 * both call sites (issue #128) stay in sync. Returns 'shared' when the native
 * share sheet handled it (no further UI needed), 'copied'/'failed' for the
 * clipboard-fallback outcome the caller should surface as a toast, or
 * 'cancelled' when the user dismissed the native share sheet. */
export async function shareEvent(title: string | undefined, url: string): Promise<'shared' | 'copied' | 'failed' | 'cancelled'> {
  if (navigator.share) {
    try {
      await navigator.share({ title, url });
      return 'shared';
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return 'cancelled';
      // unsupported/blocked share — fall through to copy
    }
  }
  return (await copyToClipboard(url)) ? 'copied' : 'failed';
}

export function categoryGradient(categories: string[]): string {
  const key = categories[0]?.toLowerCase().replace(/\s+/g, '_') ?? '';
  return CATEGORY_GRADIENTS[key] ?? FALLBACK_GRADIENT;
}

/** Displayable currency symbol: the app's EUR glyph for the default currency,
 * else the raw currency code (or '' when absent). */
export function currencySymbol(currency: string | null): string {
  return currency === DEFAULT_CURRENCY ? EUR_SYMBOL : currency ?? '';
}

export function formatPrice(min: number | null, max: number | null, currency: string | null, locale: string, hasFreeTier = false): string | null {
  if (min === null && max === null) return null;
  const sym = currencySymbol(currency);
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
  if (lat !== null && lng !== null) return `${GOOGLE_MAPS_SEARCH_URL}${lat},${lng}`;
  if (address) return `${GOOGLE_MAPS_SEARCH_URL}${encodeURIComponent(address)}`;
  return null;
}

/** Builds (and caches at module scope, keyed by locale + a literal format-shape
 * key) an Intl.DateTimeFormat — same rationale as hourMinuteFormatter above.
 * `shapeKey` must uniquely identify `options`; call sites pass one of the
 * DTF_* constants below for both, so the cache key is a cheap string literal
 * join instead of a fresh JSON.stringify(options) on every call (options
 * itself is also a hoisted module constant, not a fresh object literal per
 * call). */
const DATE_TIME_FORMATTERS = new Map<string, Intl.DateTimeFormat>();
function dateTimeFormatter(
  localeCode: string,
  shapeKey: string,
  options: Intl.DateTimeFormatOptions,
  tallinn = false,
): Intl.DateTimeFormat {
  const key = tallinn ? `${localeCode}|${shapeKey}|tallinn` : `${localeCode}|${shapeKey}`;
  let fmt = DATE_TIME_FORMATTERS.get(key);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(localeCode, tallinn ? { ...options, timeZone: TALLINN_TZ } : options);
    DATE_TIME_FORMATTERS.set(key, fmt);
  }
  return fmt;
}

const DTF_WEEKDAY_SHORT: Intl.DateTimeFormatOptions = { weekday: 'short' };
const DTF_DAY_MONTH_SHORT: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' };
const DTF_WEEKDAY_LONG: Intl.DateTimeFormatOptions = { weekday: 'long' };
const DTF_DAY_MONTH_YEAR_LONG: Intl.DateTimeFormatOptions = {
  day: 'numeric', month: 'long', year: 'numeric',
};
const DTF_MONTH_YEAR: Intl.DateTimeFormatOptions = { month: 'long', year: 'numeric' };
const DTF_LONG_DATE: Intl.DateTimeFormatOptions = {
  weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
};
const DTF_DAY_MONTH_LONG: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'long' };
const DTF_ADMIN_TIMESTAMP: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' };

/** Admin console timestamp — the console is un-i18n'd, so this always renders
 * in DEFAULT_LOCALE_CODE rather than taking a locale param. */
export function formatAdminTimestamp(iso: string | null): string {
  if (!iso) return '—';
  return dateTimeFormatter(DEFAULT_LOCALE_CODE, 'admin-timestamp', DTF_ADMIN_TIMESTAMP, true).format(new Date(iso));
}

export function formatEventTime(iso: string, locale: string): string {
  const localeCode = toLocaleCode(locale);
  const date = new Date(iso);
  const weekday = dateTimeFormatter(localeCode, 'weekday-short', DTF_WEEKDAY_SHORT, true).format(date);
  const day = dateTimeFormatter(localeCode, 'day-month-short', DTF_DAY_MONTH_SHORT, true).format(date);
  const time = hourMinuteFormatter(locale, true).format(date);
  return `${weekday}, ${day} · ${time}`;
}

export function formatEventDateTime(iso: string, locale: string): string {
  const localeCode = toLocaleCode(locale);
  const date = new Date(iso);
  const weekday = dateTimeFormatter(localeCode, 'weekday-long', DTF_WEEKDAY_LONG, true).format(date);
  const day = dateTimeFormatter(localeCode, 'day-month-year-long', DTF_DAY_MONTH_YEAR_LONG, true).format(date);
  const time = hourMinuteFormatter(locale, true).format(date);
  return `${weekday}, ${day} · ${time}`;
}

/** Short "15 Aug"-style date, used as the event-detail SEO title's
 * venue-or-date fallback (useSeoMeta) when an event has no venue_name. */
export function formatEventShortDate(iso: string, locale: string): string {
  const localeCode = toLocaleCode(locale);
  return dateTimeFormatter(localeCode, 'day-month-short', DTF_DAY_MONTH_SHORT, true).format(new Date(iso));
}

/** Flatten an inline run (string or `{ text }` part) to plain text, for building
 * stable React keys off authored content (react/no-array-index-key is an error). */
export function inlineText(content: ReadonlyArray<string | { text: string }>): string {
  return content.map((part) => (typeof part === 'string' ? part : part.text)).join('');
}

// ─── Date / number helpers ───────────────────────────────────────────────────

/** Constrains `n` to the inclusive [lo, hi] range. */
export function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

/** Midnight (local time) of `d`'s calendar day. */
export function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** True when both dates fall on the same local calendar day. */
export function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

/** Shifts by whole months, clamping the day-of-month into the target month so
 * e.g. Jan 31 + 1 month lands on Feb 28/29 rather than spilling into March. */
export function addMonths(d: Date, n: number): Date {
  const r = new Date(d.getFullYear(), d.getMonth() + n, 1);
  const daysInTarget = new Date(r.getFullYear(), r.getMonth() + 1, 0).getDate();
  r.setDate(Math.min(d.getDate(), daysInTarget));
  return r;
}

// ─── DatePicker ──────────────────────────────────────────────────────────────

export interface CalendarCell {
  date: Date;
  day: number;
  spill: boolean;
  /** Stable React list key — precomputed here instead of calling the
   * expensive Date.toISOString() per cell per render. */
  key: string;
  /** Same identity string as `date.toDateString()`, precomputed once — used
   * for both the grid's `data-date` attribute and the focus-restore lookup. */
  dataDate: string;
}

/** Days elapsed since the start of `d`'s week — 0 on the week's first day
 * (`weekStart`), CALENDAR_DAYS_PER_WEEK - 1 on its last. */
export function weekdayOffset(d: Date, weekStart: number): number {
  return (d.getDay() - weekStart + CALENDAR_DAYS_PER_WEEK) % CALENDAR_DAYS_PER_WEEK;
}

/** Returns a fixed CALENDAR_WEEKS_SHOWN × CALENDAR_DAYS_PER_WEEK grid of days for
 * `month` (0-indexed) of `year`, starting on `weekStart` (0 = Sunday, 1 = Monday),
 * including leading/trailing days spilling in from adjacent months. */
export function monthGridDays(year: number, month: number, weekStart: number): CalendarCell[] {
  const first = new Date(year, month, 1);
  const startOffset = weekdayOffset(first, weekStart);
  const gridStart = new Date(year, month, 1 - startOffset);
  const totalCells = CALENDAR_WEEKS_SHOWN * CALENDAR_DAYS_PER_WEEK;
  const cells: CalendarCell[] = [];
  for (let i = 0; i < totalCells; i++) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    const dataDate = d.toDateString();
    cells.push({ date: d, day: d.getDate(), spill: d.getMonth() !== month, key: dataDate, dataDate });
  }
  return cells;
}

const WEEKDAY_HEADER_FORMATTERS = new Map<string, Intl.DateTimeFormat>();
/** Localized short weekday headers ordered starting at CALENDAR_WEEK_START, e.g.
 * ['Mo','Tu',...]. Built off CALENDAR_REFERENCE_MONDAY rather than `new Date()`,
 * so the labels don't depend on when this runs. */
export function weekdayHeaders(locale: string): string[] {
  const localeCode = toLocaleCode(locale);
  let fmt = WEEKDAY_HEADER_FORMATTERS.get(localeCode);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(localeCode, { weekday: 'short' });
    WEEKDAY_HEADER_FORMATTERS.set(localeCode, fmt);
  }
  const [refYear, refMonth, refDay] = CALENDAR_REFERENCE_MONDAY;
  const reference = new Date(refYear, refMonth, refDay);
  // Offset off the reference's own weekday rather than a hardcoded index, so
  // the loop stays correct if CALENDAR_REFERENCE_MONDAY ever moves.
  const toWeekStart = (CALENDAR_WEEK_START - reference.getDay() + CALENDAR_DAYS_PER_WEEK) % CALENDAR_DAYS_PER_WEEK;
  const labels: string[] = [];
  for (let i = 0; i < CALENDAR_DAYS_PER_WEEK; i++) {
    labels.push(fmt.format(addDays(reference, toWeekStart + i)));
  }
  return labels;
}

export interface PickerDateTime {
  year: number;
  month: number; // 0-indexed
  day: number;
  hour: number;
  minute: number;
}


/** Splits the 'YYYY-MM-DDTHH:mm' wire value (the same format the native
 * datetime-local input this component replaces used) into components, or
 * null when empty/malformed/not a real calendar date. */
export function splitDateTimeValue(value: string): PickerDateTime | null {
  const m = PICKER_VALUE_RE.exec(value);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]) - 1;
  const day = Number(m[3]);
  const hour = Number(m[4]);
  const minute = Number(m[5]);
  const date = new Date(year, month, day, hour, minute);
  if (date.getFullYear() !== year || date.getMonth() !== month || date.getDate() !== day) return null;
  if (hour > MAX_HOUR || minute > MAX_MINUTE) return null;
  return { year, month, day, hour, minute };
}

export function joinDateTimeValue(date: Date, hour: number, minute: number): string {
  return `${date.getFullYear()}-${padIndex(date.getMonth() + 1)}-${padIndex(date.getDate())}T${padIndex(hour)}:${padIndex(minute)}`;
}

/** Organizer-form wire converter: the picker's 'YYYY-MM-DDTHH:mm' local value
 * has no timezone of its own, so this reads it in the browser's local offset
 * before converting to the ISO string the API expects. Empty/unparseable
 * input becomes undefined (field left blank / not yet filled in). */
export function toIsoOrUndefined(local: string): string | undefined {
  if (!local) return undefined;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

/** Inverse of toIsoOrUndefined — the browser's local offset is used both when
 * parsing and here, so round-tripping an existing ISO value back into the
 * field reproduces the same wall-clock time the organizer originally entered. */
export function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return joinDateTimeValue(d, d.getHours(), d.getMinutes());
}

/** Validates free-typed text against the canonical wire format, returning it
 * unchanged when valid or null otherwise — kept strict since the popover also
 * writes this same canonical format back into the field, so there's no
 * locale-specific format to parse leniently. */
export function parseTypedDate(text: string): string | null {
  return splitDateTimeValue(text) ? text : null;
}

/** Cosmetic-only transform for the picker's text field: the wire format's
 * literal 'T' separator (`YYYY-MM-DDTHH:mm`, required for `toIsoOrUndefined`'s
 * `new Date(local)` parse in useOrganizerEventForm.ts) reads as noise to a
 * non-technical user, so the field displays a space instead. Only the display
 * layer changes — the committed `value`/`onChange` contract stays 'T'-joined. */
export function toDisplayDateTime(value: string): string {
  return value.replace('T', ' ');
}

/** Inverse of toDisplayDateTime — converts a typed display string back to the
 * canonical 'T'-joined wire format before it's validated/parsed. */
export function fromDisplayDateTime(text: string): string {
  return text.replace(' ', 'T');
}

/** Localized "Month Year" heading for a calendar grid's header, e.g. "July 2026". */
export function formatMonthYearLabel(year: number, month: number, locale: string): string {
  const localeCode = toLocaleCode(locale);
  const date = new Date(year, month, 1);
  return dateTimeFormatter(localeCode, 'month-year', DTF_MONTH_YEAR).format(date);
}

/** Human-readable trigger label for a valid picker value, e.g. "24 Jul, 19:00". */
export function formatPickerValue(value: string, locale: string): string {
  const parts = splitDateTimeValue(value);
  if (!parts) return '';
  const localeCode = toLocaleCode(locale);
  const date = new Date(parts.year, parts.month, parts.day, parts.hour, parts.minute);
  const day = dateTimeFormatter(localeCode, 'day-month-short', DTF_DAY_MONTH_SHORT).format(date);
  const time = hourMinuteFormatter(locale).format(date);
  return `${day}, ${time}`;
}

function formatLongDate(date: Date, locale: string, tallinn = false): string {
  const localeCode = toLocaleCode(locale);
  return dateTimeFormatter(localeCode, 'long-date', DTF_LONG_DATE, tallinn).format(date);
}

export function formatTodayDate(locale: string): string {
  return formatLongDate(new Date(), locale, true);
}

/** Landing-hero dateline: weekday-long + day/month-long, no year — the
 * Landing hero shows the city name as its own suffix instead. */
export function formatHeroDateline(locale: string): string {
  const localeCode = toLocaleCode(locale);
  const date = new Date();
  const weekday = dateTimeFormatter(localeCode, 'weekday-long', DTF_WEEKDAY_LONG, true).format(date);
  const dayMonth = dateTimeFormatter(localeCode, 'day-month-long', DTF_DAY_MONTH_LONG, true).format(date);
  return `${weekday}, ${dayMonth}`;
}

const NUMBER_FORMATTERS = new Map<string, Intl.NumberFormat>();
function numberFormatter(locale: string): Intl.NumberFormat {
  const localeCode = toLocaleCode(locale);
  let fmt = NUMBER_FORMATTERS.get(localeCode);
  if (!fmt) {
    fmt = new Intl.NumberFormat(localeCode);
    NUMBER_FORMATTERS.set(localeCode, fmt);
  }
  return fmt;
}

/** Locale-grouped integer, e.g. 1008 → "1,008" (en) / "1 008" (et). */
export function formatCount(n: number, locale: string): string {
  return numberFormatter(locale).format(n);
}

/** Formats a `YYYY-MM-DD` date-only string (e.g. `daily_feeds.feed_date`) using
 * a local-date constructor rather than `new Date(dateStr)` — the latter parses
 * a bare date as UTC midnight, which can shift a day off in timezones behind UTC. */
export function formatIsoDate(dateStr: string, locale: string): string {
  const [year, month, day] = dateStr.split('-').map(Number);
  return formatLongDate(new Date(year, month - 1, day), locale);
}

/** Parses a `YYYY-MM-DD` string into a local-midnight Date, matching
 * formatIsoDate's local-date construction — `new Date(s)` parses a bare date
 * as UTC midnight, which can land on the previous day in timezones behind UTC. */
export function parseISODateLocal(s: string): Date {
  const [year, month, day] = s.split('-').map(Number);
  return new Date(year, month - 1, day);
}

/** Short "1 Mar"-style label for a Date, used by DateRangeMenu's trigger and
 * calendar-mode range hint. */
export function formatDateShort(date: Date, locale: string): string {
  const localeCode = toLocaleCode(locale);
  return dateTimeFormatter(localeCode, 'day-month-short', DTF_DAY_MONTH_SHORT).format(date);
}

/** Short range label for DateRangeMenu's trigger, e.g. "1 Mar – 15 Mar". */
export function formatDateRangeShort(from: string, to: string, locale: string): string {
  return `${formatDateShort(parseISODateLocal(from), locale)} – ${formatDateShort(parseISODateLocal(to), locale)}`;
}

export function padIndex(n: number): string {
  return String(n).padStart(TIME_FIELD_MAX_LENGTH, '0');
}

/** Truncates `text` to at most `maxLength` chars for a meta/og:description,
 * cutting at the last word boundary before the limit (never mid-word) and
 * appending an ellipsis. Returns `text` unchanged when it already fits.
 * Splits on code points (Array.from), not raw UTF-16 slice(), so the cut
 * point can never land inside a surrogate pair (e.g. an emoji). */
export function truncateForMeta(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  // Walk code points only up to the cut, not the whole string.
  let cut = '';
  let count = 0;
  for (const ch of text) {
    if (count === maxLength) break;
    cut += ch;
    count += 1;
  }
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > 0 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
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

/** Last path segment of a URL, decoded, with any query/hash stripped — used to
 * derive a displayable filename from a stored Cloudinary image URL when no
 * File object (and thus no original filename) is available, e.g. FileField's
 * edit-mode prefill. Returns '' on an unparseable URL or an empty path. */
export function fileNameFromUrl(url: string): string {
  try {
    const pathname = new URL(url).pathname;
    const last = pathname.split('/').filter(Boolean).pop() ?? '';
    return last ? decodeURIComponent(last) : '';
  } catch {
    return '';
  }
}

/** True when a popover of `popWidth` left-anchored at `triggerLeft` (viewport-relative
 * px) would overflow the viewport's right edge. `marginPx` matches the --space-5
 * gutter .menuPop's max-width already reserves, for consistency. */
export function shouldFlipPopover(triggerLeft: number, popWidth: number, viewportWidth: number, marginPx: number): boolean {
  return triggerLeft + popWidth > viewportWidth - marginPx;
}

/** Mirror of shouldFlipPopover for a popover that's right-anchored to the
 * trigger by default (extends leftward) — flips to left-anchored when that
 * would overflow the viewport's left edge. */
export function shouldFlipPopoverLeft(triggerRight: number, popWidth: number, marginPx: number): boolean {
  return triggerRight - popWidth < marginPx;
}

// ─── Explore ─────────────────────────────────────────────────────────────────

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
 * Exported only so utils.test.ts can exercise it directly; every production
 * call site is within this module. */
export function isFullSet(sel: string[], all: readonly string[]): boolean {
  return sel.length === all.length;
}

/** Local-date `YYYY-MM-DD` serializer — inverse of parseISODateLocal. */
export function toDateStr(d: Date): string {
  return `${d.getFullYear()}-${padIndex(d.getMonth() + 1)}-${padIndex(d.getDate())}`;
}

const TALLINN_YMD_FORMATTER = new Intl.DateTimeFormat('en-US', {
  timeZone: TALLINN_TZ, year: 'numeric', month: 'numeric', day: 'numeric',
});

/** The current Tallinn calendar day as a local-midnight Date — same shape as
 * `startOfDay(new Date())` but anchored to Europe/Tallinn rather than the
 * browser zone, so "today" presets and picker minimums agree with event times. */
export function tallinnToday(): Date {
  const parts = TALLINN_YMD_FORMATTER.formatToParts(new Date());
  const pick = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return new Date(pick('year'), pick('month') - 1, pick('day'));
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
  if (preset === 'custom') return { from: null, to: null };
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
  if (filters.datePreset === 'custom' && filters.customFrom && filters.customTo) {
    params.set(EXPLORE_PARAM.dateFrom, filters.customFrom);
    params.set(EXPLORE_PARAM.dateTo, filters.customTo);
  }
  if (filters.free) params.set(EXPLORE_PARAM.free, EXPLORE_URL_FLAG_TRUE);
  if (filters.forYou) params.set(EXPLORE_PARAM.forYou, EXPLORE_URL_FLAG_TRUE);
  if (filters.sort !== SORT_DEFAULT) params.set(EXPLORE_PARAM.sort, filters.sort);
  return params;
}

/** Build the GET /explore query string for a given filter set + page offset. */
export function buildExploreApiQuery(
  filters: ExploreFilters,
  offset: number,
  cursor?: string,
): string {
  const params = new URLSearchParams();
  if (filters.q) params.set(EXPLORE_PARAM.q, filters.q);
  if (filters.category.length && !isFullSet(filters.category, CATEGORIES)) {
    params.set(EXPLORE_PARAM.category, filters.category.join(','));
  }
  if (filters.vibe.length && !isFullSet(filters.vibe, VIBES)) {
    params.set(EXPLORE_PARAM.vibe, filters.vibe.join(','));
  }
  if (filters.datePreset === 'custom') {
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
  if (cursor) params.set(EXPLORE_PARAM.cursor, cursor);
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

/** English-only ("just now" / "3h ago" / "2d ago") — admin console is
 * deliberately exempt from the shared/i18n workflow (see CLAUDE.md). */
export function relativeTimeFromNow(iso: string): string {
  const hours = Math.round((Date.now() - new Date(iso).getTime()) / MS_PER_HOUR);
  if (hours < 1) return 'just now';
  if (hours < HOURS_PER_DAY) return `${hours}h ago`;
  return `${Math.round(hours / HOURS_PER_DAY)}d ago`;
}

interface CachedEventLike {
  id: number;
}
interface CachedEventsPage {
  events: CachedEventLike[];
}

function patchEventInPage<T extends CachedEventsPage>(page: T, eventId: number, patch: object): T {
  if (!Array.isArray(page?.events) || !page.events.some((e) => e.id === eventId)) return page;
  return { ...page, events: page.events.map((e) => (e.id === eventId ? { ...e, ...patch } : e)) };
}

/** Writes `patch` (e.g. `{ my_signal }`, `{ reported }`) onto one event's row in
 * every cached Feed / Explore / event-detail payload, so a save/like/report is
 * reflected everywhere without refetching every loaded page of every list
 * (an infinite Explore query refetches all its pages sequentially). Saved-tab
 * payloads are deliberately left alone: membership there changes with the
 * signal, so callers invalidate them instead. */
export function patchCachedEvent(queryClient: QueryClient, eventId: number, patch: object): void {
  queryClient.setQueriesData<CachedEventsPage>({ queryKey: [QUERY_KEYS.feed] }, (old) =>
    old ? patchEventInPage(old, eventId, patch) : old,
  );
  queryClient.setQueriesData<InfiniteData<CachedEventsPage>>({ queryKey: [QUERY_KEYS.explore] }, (old) =>
    Array.isArray(old?.pages) ? { ...old, pages: old.pages.map((page) => patchEventInPage(page, eventId, patch)) } : old,
  );
  queryClient.setQueriesData<CachedEventLike>({ queryKey: [QUERY_KEYS.event] }, (old) =>
    old && old.id === eventId ? { ...old, ...patch } : old,
  );
}

/** `animation-delay` for the card at global list `index`: the stagger restarts
 * on every page and plateaus after CARD_ANIMATION_MAX_STEPS cards, instead of
 * growing linearly with the count of everything loaded so far. */
export function cardAnimationDelayMs(index: number): number {
  return Math.min(index % BROWSE_PAGE_SIZE, CARD_ANIMATION_MAX_STEPS) * CARD_ANIMATION_DELAY_STEP_MS;
}
