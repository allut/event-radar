import { DEFAULT_CURRENCY } from '../_generated/sharedConstants';
import { EUR_SYMBOL } from '../constants/core';
import { t, ti } from '../i18n';

/** Displayable currency symbol: the app's EUR glyph for the default currency,
 * else the raw currency code (or '' when absent). */
export function currencySymbol(currency: string | null): string {
  return currency === DEFAULT_CURRENCY ? EUR_SYMBOL : currency ?? '';
}

export function formatPrice(min: number | null, max: number | null, currency: string | null, locale: string, hasFreeTier = false): string | null {
  if (min === null && max === null) return null;
  const sym = currencySymbol(currency);
  if (min === 0) {
    // Base admission is free; a positive max means an optional paid tier exists
    // (e.g. an open-mic's support ticket) — surface it rather than showing a
    // bare "Free" that hides the paid option entirely.
    if (max !== null && max > 0) {
      return ti('price_free_with_paid', locale, { amount: `${sym}${max}` });
    }
    return t('price_free', locale);
  }
  let priceStr: string | null;
  if (min !== null && max !== null && min !== max) {
    priceStr = `${sym}${min}–${sym}${max}`;
  } else if (min !== null) {
    priceStr = `${sym}${min}`;
  } else {
    priceStr = null;
  }
  if (priceStr && hasFreeTier) {
    return `${priceStr} · ${t('price_free_options', locale)}`;
  }
  return priceStr;
}
