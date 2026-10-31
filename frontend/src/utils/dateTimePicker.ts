import { PICKER_VALUE_RE, MAX_HOUR, MAX_MINUTE } from '../constants/core';
import { padIndex } from './calendar';
import { formatDateShort, hourMinuteFormatter } from './intlFormat';

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

/** Human-readable trigger label for a valid picker value, e.g. "24 Jul, 19:00". */
export function formatPickerValue(value: string, locale: string): string {
  const parts = splitDateTimeValue(value);
  if (!parts) return '';
  const date = new Date(parts.year, parts.month, parts.day, parts.hour, parts.minute);
  const day = formatDateShort(date, locale);
  const time = hourMinuteFormatter(locale).format(date);
  return `${day}, ${time}`;
}
