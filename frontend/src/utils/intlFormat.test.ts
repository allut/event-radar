import { describe, it, expect, vi, afterEach } from 'vitest';
import { parseISODateLocal, tallinnToday } from './calendar';
import {
  formatDateRangeShort,
  formatEventShortDate,
  formatEventTime,
  formatHourMinute,
  formatMonthYearLabel,
  weekdayHeaders,
} from './intlFormat';
import { datePresetRange } from './exploreFilters';

describe('formatHourMinute', () => {
  it('formats time as HH:MM', () => {
    const result = formatHourMinute('2024-07-15T18:30:00Z', 'en');
    expect(result).toMatch(/\d{2}:\d{2}/);
  });
});

describe('formatEventShortDate', () => {
  it('formats a short day-month date', () => {
    const result = formatEventShortDate('2024-07-15T18:30:00Z', 'en');
    expect(result).toMatch(/\d{1,2}/);
    expect(result).not.toMatch(/\d{4}/); // no year in the short form
  });
});

describe('parseISODateLocal / formatDateRangeShort', () => {
  it('parses a YYYY-MM-DD string as a local-midnight Date', () => {
    const d = parseISODateLocal('2026-09-15');
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(8);
    expect(d.getDate()).toBe(15);
  });

  it('formats a short range label', () => {
    const result = formatDateRangeShort('2026-09-01', '2026-09-15', 'en');
    expect(result).toContain('–');
    expect(result).toMatch(/^1 Sep\w* – 15 Sep\w*$/);
  });
});

describe('weekdayHeaders', () => {
  it('returns 7 labels starting on Monday', () => {
    const labels = weekdayHeaders('en');
    expect(labels).toHaveLength(7);
  });
});

describe('formatMonthYearLabel', () => {
  it('formats a month and year', () => {
    expect(formatMonthYearLabel(2026, 6, 'en')).toBe('July 2026');
  });
});

describe('Europe/Tallinn pinning', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('formats event instants as Tallinn wall-clock time (winter, UTC+2)', () => {
    expect(formatHourMinute('2026-01-15T17:00:00Z', 'en')).toBe('19:00');
  });

  it('formats event instants as Tallinn wall-clock time (summer, UTC+3)', () => {
    expect(formatHourMinute('2026-07-15T17:00:00Z', 'en')).toBe('20:00');
  });

  it('rolls the date over when Tallinn is already on the next day', () => {
    expect(formatEventTime('2026-07-15T22:30:00Z', 'en')).toContain('16 Jul');
    expect(formatEventTime('2026-07-15T22:30:00Z', 'en')).toContain('01:30');
  });

  it('tallinnToday follows the Tallinn calendar day, not the host zone', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-15T22:30:00Z')); // 01:30 on 16 Jul in Tallinn
    const today = tallinnToday();
    expect([today.getFullYear(), today.getMonth(), today.getDate()]).toEqual([2026, 6, 16]);
    expect(datePresetRange('today')).toEqual({ from: '2026-07-16', to: '2026-07-16' });
  });
});
