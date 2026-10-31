import { DEFAULT_LOCALE_CODE, TALLINN_TZ } from '../_generated/sharedConstants';
import {
  toLocaleCode,
  CALENDAR_WEEK_START,
  CALENDAR_DAYS_PER_WEEK,
  CALENDAR_REFERENCE_MONDAY,
  MS_PER_HOUR,
  HOURS_PER_DAY,
} from '../constants/core';
import { addDays, parseISODateLocal } from './calendar';

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
export function hourMinuteFormatter(locale: string, tallinn = false): Intl.DateTimeFormat {
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
  return cachedDateTimeFormat(localeCode, shapeKey, options, tallinn ? TALLINN_TZ : undefined);
}

/** The cache behind every formatter here, for one outside this module (ESLint
 * bans a per-call `new Intl.*` elsewhere). `timeZone: 'UTC'` formats a bare
 * YYYY-MM-DD day built with a `Z` suffix without shifting it. */
export function cachedDateTimeFormat(
  localeCode: string,
  shapeKey: string,
  options: Intl.DateTimeFormatOptions,
  timeZone?: string,
): Intl.DateTimeFormat {
  const key = `${localeCode}|${shapeKey}|${timeZone ?? ''}`;
  let fmt = DATE_TIME_FORMATTERS.get(key);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(localeCode, timeZone ? { ...options, timeZone } : options);
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

/** Localized "Month Year" heading for a calendar grid's header, e.g. "July 2026". */
export function formatMonthYearLabel(year: number, month: number, locale: string): string {
  const localeCode = toLocaleCode(locale);
  const date = new Date(year, month, 1);
  return dateTimeFormatter(localeCode, 'month-year', DTF_MONTH_YEAR).format(date);
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

/** English-only ("just now" / "3h ago" / "2d ago") — admin console is
 * deliberately exempt from the shared/i18n workflow (see docs/frontend.md "Admin Console"). */
export function relativeTimeFromNow(iso: string): string {
  const hours = Math.round((Date.now() - new Date(iso).getTime()) / MS_PER_HOUR);
  if (hours < 1) return 'just now';
  if (hours < HOURS_PER_DAY) return `${hours}h ago`;
  return `${Math.round(hours / HOURS_PER_DAY)}d ago`;
}
