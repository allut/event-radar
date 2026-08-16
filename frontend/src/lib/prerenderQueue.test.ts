import { describe, it, expect } from 'vitest';
import { prioritizeRenderQueue, createBudgetedCursor, type QueueCandidate } from './prerenderQueue';

describe('prioritizeRenderQueue', () => {
  it('puts every home route ahead of every event route', () => {
    const items: QueueCandidate[] = [
      { eventId: 1, updatedAt: '2026-01-01T00:00:00.000Z' },
      { /* home, en */ },
      { eventId: 2, updatedAt: '2026-01-02T00:00:00.000Z' },
      { /* home, et */ },
    ];
    const result = prioritizeRenderQueue(items);
    expect(result.slice(0, 2)).toEqual([items[1], items[3]]);
    expect(result.slice(2)).toEqual([items[0], items[2]]);
  });

  it('orders event routes oldest-unrendered-first', () => {
    const newer = { eventId: 2, updatedAt: '2026-03-01T00:00:00.000Z' };
    const older = { eventId: 1, updatedAt: '2026-01-01T00:00:00.000Z' };
    const middle = { eventId: 3, updatedAt: '2026-02-01T00:00:00.000Z' };
    const result = prioritizeRenderQueue([newer, older, middle]);
    expect(result).toEqual([older, middle, newer]);
  });

  it('keeps stable relative order for ties (same updatedAt, or home vs. home)', () => {
    const homeEn: QueueCandidate & { locale: string } = { locale: 'en' };
    const homeEt: QueueCandidate & { locale: string } = { locale: 'et' };
    const evA: QueueCandidate & { locale: string } = { eventId: 1, updatedAt: '2026-01-01T00:00:00.000Z', locale: 'en' };
    const evB: QueueCandidate & { locale: string } = { eventId: 2, updatedAt: '2026-01-01T00:00:00.000Z', locale: 'et' };
    const result = prioritizeRenderQueue([evA, homeEn, evB, homeEt]);
    expect(result).toEqual([homeEn, homeEt, evA, evB]);
  });

  it('does not mutate the input array', () => {
    const items: QueueCandidate[] = [
      { eventId: 1, updatedAt: '2026-02-01T00:00:00.000Z' },
      {},
    ];
    const copy = [...items];
    prioritizeRenderQueue(items);
    expect(items).toEqual(copy);
  });
});

describe('createBudgetedCursor', () => {
  it('yields every index in order when the deadline never hits', () => {
    const cursor = createBudgetedCursor(3, Date.now() + 60_000);
    expect(cursor.next()).toBe(0);
    expect(cursor.next()).toBe(1);
    expect(cursor.next()).toBe(2);
    expect(cursor.next()).toBeNull();
    expect(cursor.remaining()).toEqual([]);
  });

  it('stops handing out indices once now() reaches the deadline, leaving the rest queued', () => {
    let now = 0;
    const clock = () => now;
    const cursor = createBudgetedCursor(5, 100, clock);
    expect(cursor.next()).toBe(0);
    expect(cursor.next()).toBe(1);
    now = 100;
    expect(cursor.next()).toBeNull();
    expect(cursor.remaining()).toEqual([2, 3, 4]);
  });

  it('returns null immediately for a budget that is already exhausted (artificially small budget)', () => {
    const cursor = createBudgetedCursor(4, 0, () => 1);
    expect(cursor.next()).toBeNull();
    expect(cursor.remaining()).toEqual([0, 1, 2, 3]);
  });

  it('handles a total of zero', () => {
    const cursor = createBudgetedCursor(0, Date.now() + 60_000);
    expect(cursor.next()).toBeNull();
    expect(cursor.remaining()).toEqual([]);
  });
});
