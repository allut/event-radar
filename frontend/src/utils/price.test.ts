import { describe, it, expect } from 'vitest';
import { formatPrice } from './price';

describe('formatPrice', () => {
  it('returns null when both null', () => {
    expect(formatPrice(null, null, null, 'en')).toBeNull();
  });

  it('returns free label when min === 0', () => {
    const result = formatPrice(0, null, 'EUR', 'en');
    expect(result).toBe('Free');
  });

  it('shows range when min !== max', () => {
    const result = formatPrice(10, 20, 'EUR', 'en');
    expect(result).toContain('10');
    expect(result).toContain('20');
    expect(result).toContain('€');
  });

  it('shows single price when min only', () => {
    const result = formatPrice(15, null, 'EUR', 'en');
    expect(result).toBe('€15');
  });

  it('uses EUR symbol for EUR currency', () => {
    const result = formatPrice(10, 10, 'EUR', 'en');
    expect(result).toContain('€');
  });

  it('uses raw code for non-EUR currency', () => {
    const result = formatPrice(10, null, 'USD', 'en');
    expect(result).toContain('USD');
  });

  it('shows free-with-paid note when min is 0 and max is positive', () => {
    const result = formatPrice(0, 10, 'EUR', 'en');
    expect(result).toContain('Free');
    expect(result).toContain('10');
  });

  it('returns plain free label when min is 0 and max is also 0', () => {
    const result = formatPrice(0, 0, 'EUR', 'en');
    expect(result).toBe('Free');
  });

  it('appends free-options note when hasFreeTier is true', () => {
    const result = formatPrice(14, 17, 'EUR', 'en', true);
    expect(result).toContain('14');
    expect(result).toContain('17');
    expect(result?.toLowerCase()).toContain('free');
  });

  it('does not append free-options note when hasFreeTier is false', () => {
    const result = formatPrice(14, 17, 'EUR', 'en', false);
    expect(result).toBe('€14–€17');
  });
});
