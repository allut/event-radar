import { CATEGORY_GRADIENTS, FALLBACK_GRADIENT, EUR_SYMBOL, FREE_LABEL, type Signal } from './constants';

export function categoryGradient(categories: string[]): string {
  const key = categories[0]?.toLowerCase().replace(/\s+/g, '_') ?? '';
  return CATEGORY_GRADIENTS[key] ?? FALLBACK_GRADIENT;
}

export function formatPrice(min: number | null, max: number | null, currency: string | null): string | null {
  if (min === null && max === null) return null;
  const sym = currency === 'EUR' ? EUR_SYMBOL : currency ?? '';
  if (min === 0) return FREE_LABEL;
  if (min !== null && max !== null && min !== max) return `${sym}${min}–${sym}${max}`;
  if (min !== null) return `${sym}${min}`;
  return null;
}

const SIGNAL_TO_CLASS: Record<Signal, string> = {
  like: 'activeLike',
  dislike: 'activeDislike',
  bookmark: 'activeBookmark',
};

export function makeActiveClassMap(styles: Record<string, string>): Record<Signal, string> {
  const result = {} as Record<Signal, string>;
  for (const [signal, cssKey] of Object.entries(SIGNAL_TO_CLASS) as [Signal, string][]) {
    const cls = styles[cssKey];
    if (!cls) throw new Error(`makeActiveClassMap: CSS class "${cssKey}" is missing from styles module`);
    result[signal] = cls;
  }
  return result;
}
