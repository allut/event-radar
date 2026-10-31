import { TALLINN_TZ } from '../_generated/sharedConstants';
import { CALENDAR_WEEKS_SHOWN, CALENDAR_DAYS_PER_WEEK, TIME_FIELD_MAX_LENGTH } from '../constants/core';

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

/** Parses a `YYYY-MM-DD` string into a local-midnight Date, matching
 * formatIsoDate's local-date construction — `new Date(s)` parses a bare date
 * as UTC midnight, which can land on the previous day in timezones behind UTC. */
export function parseISODateLocal(s: string): Date {
  const [year, month, day] = s.split('-').map(Number);
  return new Date(year, month - 1, day);
}

export function padIndex(n: number): string {
  return String(n).padStart(TIME_FIELD_MAX_LENGTH, '0');
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
