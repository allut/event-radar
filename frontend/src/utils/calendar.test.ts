import { describe, it, expect } from 'vitest';
import { monthGridDays, weekdayOffset } from './calendar';

describe('monthGridDays', () => {
  it('produces a 6x7 grid starting on the configured week start', () => {
    // July 2024 starts on a Monday — with weekStart=1 the grid should start
    // exactly on 1 Jul with no leading spill.
    const cells = monthGridDays(2024, 6, 1);
    expect(cells).toHaveLength(42);
    expect(cells[0].date.getDate()).toBe(1);
    expect(cells[0].spill).toBe(false);
  });

  it('spills leading days from the previous month when the 1st is not the week start', () => {
    // February 2024 (leap year) starts on a Thursday.
    const cells = monthGridDays(2024, 1, 1);
    expect(cells[0].spill).toBe(true);
    expect(cells[0].date.getMonth()).toBe(0);
    // 29 Feb 2024 exists (leap year) and is not spill.
    const leapDay = cells.find((c) => c.date.getMonth() === 1 && c.day === 29);
    expect(leapDay?.spill).toBe(false);
  });

  it('spills trailing days into the next month to fill the fixed 42-cell grid', () => {
    const cells = monthGridDays(2024, 6, 1);
    const last = cells[cells.length - 1];
    expect(last.spill).toBe(true);
  });
});

describe('weekdayOffset', () => {
  it('counts days since the week start', () => {
    const wednesday = new Date(2024, 6, 3);
    expect(weekdayOffset(wednesday, 1)).toBe(2);
    expect(weekdayOffset(wednesday, 0)).toBe(3);
    expect(weekdayOffset(new Date(2024, 6, 7), 1)).toBe(6);
  });
});
