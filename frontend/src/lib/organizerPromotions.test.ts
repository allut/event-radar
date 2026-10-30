import { describe, expect, it } from 'vitest';
import {
  formatMoney,
  formatPromoDays,
  formatPromoRange,
  isRegistryCodeValid,
  pauseReasonKey,
  splitAround,
} from './organizerPromotions';

describe('isRegistryCodeValid', () => {
  it('accepts codes whose check digit matches, on either weighting', () => {
    expect(isRegistryCodeValid('12345678')).toBe(true);
    // First weighting gives 10, so the second weighting applies.
    expect(isRegistryCodeValid('05000009')).toBe(true);
  });

  it('rejects a wrong check digit, a short code and non-digits', () => {
    expect(isRegistryCodeValid('12345679')).toBe(false);
    expect(isRegistryCodeValid('1234567')).toBe(false);
    expect(isRegistryCodeValid('1234567a')).toBe(false);
  });
});

describe('formatMoney', () => {
  it('drops cents on whole euros and uses the locale’s decimal mark', () => {
    expect(formatMoney(500, 'en')).toBe('€5');
    expect(formatMoney(620, 'en')).toBe('€6.20');
    expect(formatMoney(620, 'et')).toBe('€6,20');
    expect(formatMoney(3720, 'ru')).toBe('€37,20');
  });
});

describe('formatPromoRange / formatPromoDays', () => {
  it('collapses a range inside one month and spells out a longer one', () => {
    expect(formatPromoRange('2026-10-24', '2026-10-27', 'en')).toBe('24–27 Oct');
    expect(formatPromoRange('2026-10-29', '2026-11-03', 'en')).toBe('29 Oct – 3 Nov');
    expect(formatPromoRange('2026-10-24', '2026-10-24', 'en')).toBe('24 Oct');
  });

  it('counts days with the locale’s plural forms', () => {
    expect(formatPromoDays(1, 'en')).toBe('1 day');
    expect(formatPromoDays(6, 'et')).toBe('6 päeva');
    expect(formatPromoDays(2, 'ru')).toBe('2 дня');
    expect(formatPromoDays(5, 'ru')).toBe('5 дней');
    expect(formatPromoDays(21, 'ru')).toBe('21 день');
  });
});

describe('pauseReasonKey / splitAround', () => {
  it('keeps known gate codes and falls back for unknown ones', () => {
    expect(pauseReasonKey('organizer_not_owner')).toBe('organizer_not_owner');
    expect(pauseReasonKey('brand_new_code')).toBe('unknown');
    expect(pauseReasonKey(null)).toBe('unknown');
  });

  it('splits a sentence around its placeholder', () => {
    expect(splitAround('I accept {link} today', 'link')).toEqual(['I accept ', ' today']);
    expect(splitAround('No placeholder', 'link')).toEqual(['No placeholder', '']);
  });
});
