import { describe, it, expect } from 'vitest';
import { isValidLocale, localeLabel, localizedFieldLabel, localizedTriplet } from './locale';
import { t } from '../i18n';

describe('isValidLocale', () => {
  it('accepts every configured locale code', () => {
    expect(isValidLocale('en')).toBe(true);
    expect(isValidLocale('et')).toBe(true);
    expect(isValidLocale('ru')).toBe(true);
  });

  it('rejects an unrecognized or missing code', () => {
    expect(isValidLocale('xx')).toBe(false);
    expect(isValidLocale(undefined)).toBe(false);
  });
});

describe('localeLabel', () => {
  it('returns the configured label for a known code', () => {
    expect(localeLabel('et')).toBe('ET');
  });
  it('falls back to the upper-cased code for an unknown one', () => {
    expect(localeLabel('xx')).toBe('XX');
  });
});

describe('localizedFieldLabel', () => {
  it('suffixes the translated field name with the language label', () => {
    expect(localizedFieldLabel('claim_edit_field_title', 'en', 'ru')).toBe(`${t('claim_edit_field_title', 'en')} (${localeLabel('ru')})`);
  });
});

describe('localizedTriplet', () => {
  it('reads et/en/ru slots from the record', () => {
    expect(localizedTriplet({ et: 'a', en: 'b', ru: 'c' }, 'base')).toEqual(['a', 'b', 'c']);
  });
  it('falls back to base for ET and blanks for EN/RU', () => {
    expect(localizedTriplet(null, 'base')).toEqual(['base', '', '']);
    expect(localizedTriplet(undefined, undefined)).toEqual(['', '', '']);
  });
});
