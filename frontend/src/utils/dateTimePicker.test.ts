import { describe, it, expect } from 'vitest';
import {
  formatPickerValue,
  fromDisplayDateTime,
  joinDateTimeValue,
  parseTypedDate,
  splitDateTimeValue,
  toDisplayDateTime,
} from './dateTimePicker';

describe('splitDateTimeValue / joinDateTimeValue', () => {
  it('round-trips a canonical value', () => {
    const parts = splitDateTimeValue('2026-08-01T18:00');
    expect(parts).toEqual({ year: 2026, month: 7, day: 1, hour: 18, minute: 0 });
    expect(joinDateTimeValue(new Date(2026, 7, 1), 18, 0)).toBe('2026-08-01T18:00');
  });

  it('rejects an impossible calendar date', () => {
    expect(splitDateTimeValue('2026-02-30T10:00')).toBeNull();
  });

  it('rejects malformed text', () => {
    expect(splitDateTimeValue('not a date')).toBeNull();
    expect(splitDateTimeValue('')).toBeNull();
  });
});

describe('parseTypedDate', () => {
  it('accepts a valid canonical value', () => {
    expect(parseTypedDate('2026-08-01T18:00')).toBe('2026-08-01T18:00');
  });

  it('rejects a partial or invalid value', () => {
    expect(parseTypedDate('2026-08-01')).toBeNull();
    expect(parseTypedDate('2026-08-01T18')).toBeNull();
  });
});

describe('formatPickerValue', () => {
  it('formats a valid value', () => {
    expect(formatPickerValue('2026-08-01T18:00', 'en')).toBe('1 Aug, 18:00');
  });

  it('returns an empty string for an empty/invalid value', () => {
    expect(formatPickerValue('', 'en')).toBe('');
    expect(formatPickerValue('garbage', 'en')).toBe('');
  });
});

describe('toDisplayDateTime / fromDisplayDateTime', () => {
  it('replaces the T separator with a space for display', () => {
    expect(toDisplayDateTime('2026-08-01T18:00')).toBe('2026-08-01 18:00');
  });

  it('leaves an empty string unchanged', () => {
    expect(toDisplayDateTime('')).toBe('');
  });

  it('round-trips back to the canonical T-joined format', () => {
    expect(fromDisplayDateTime('2026-08-01 18:00')).toBe('2026-08-01T18:00');
    expect(fromDisplayDateTime(toDisplayDateTime('2026-08-01T18:00'))).toBe('2026-08-01T18:00');
  });

  it('leaves malformed text without a space unchanged', () => {
    expect(fromDisplayDateTime('garbage')).toBe('garbage');
  });
});
