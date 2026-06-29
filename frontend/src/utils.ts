import DOMPurify from 'dompurify';
import { api } from './api/client';
import { CATEGORY_GRADIENTS, FALLBACK_GRADIENT, EUR_SYMBOL, type Signal, toLocaleCode, SAFE_URL_SCHEMES, SANITIZE_ALLOWED_TAGS, SANITIZE_ALLOWED_ATTR, SIGNAL_TO_CLASS } from './constants';
import { t } from './i18n';

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}

/** Defense-in-depth render guard: only allow http(s) URLs into href/src attributes.
 * The backend already drops non-http(s) schemes at ingest time (safe_external_url),
 * but this protects against any other path that might surface a raw URL. */
export function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const proto = new URL(url).protocol.replace(/:$/, '');
    return SAFE_URL_SCHEMES.has(proto) ? url : null;
  } catch {
    return null;
  }
}

/** Client-side sanitizer for HTML from event description/important_info fields.
 * Strictly matches the backend nh3 allowlist; defense-in-depth before dangerouslySetInnerHTML. */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: SANITIZE_ALLOWED_TAGS,
    ALLOWED_ATTR: SANITIZE_ALLOWED_ATTR,
  });
}

export function formatHourMinute(iso: string, locale: string): string {
  return new Date(iso).toLocaleTimeString(toLocaleCode(locale), {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

export function trackExternalClick(eventId: number): void {
  api.post('/feedback', { event_id: eventId, signal: 'click_external' }).catch(() => undefined);
}

export function categoryGradient(categories: string[]): string {
  const key = categories[0]?.toLowerCase().replace(/\s+/g, '_') ?? '';
  return CATEGORY_GRADIENTS[key] ?? FALLBACK_GRADIENT;
}

export function formatPrice(min: number | null, max: number | null, currency: string | null, locale: string): string | null {
  if (min === null && max === null) return null;
  const sym = currency === 'EUR' ? EUR_SYMBOL : currency ?? '';
  if (min === 0) return t('price_free', locale);
  if (min !== null && max !== null && min !== max) return `${sym}${min}–${sym}${max}`;
  if (min !== null) return `${sym}${min}`;
  return null;
}

export function formatEventTime(iso: string, locale: string): string {
  const localeCode = toLocaleCode(locale);
  const date = new Date(iso);
  const weekday = date.toLocaleDateString(localeCode, { weekday: 'short' });
  const day = date.toLocaleDateString(localeCode, { day: 'numeric', month: 'short' });
  const time = date.toLocaleTimeString(localeCode, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${weekday}, ${day} · ${time}`;
}

export function formatEventDateTime(iso: string, locale: string): string {
  const localeCode = toLocaleCode(locale);
  const date = new Date(iso);
  const weekday = date.toLocaleDateString(localeCode, { weekday: 'long' });
  const day = date.toLocaleDateString(localeCode, { day: 'numeric', month: 'long', year: 'numeric' });
  const time = date.toLocaleTimeString(localeCode, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${weekday}, ${day} · ${time}`;
}

export function formatTodayDate(locale: string): string {
  const localeCode = toLocaleCode(locale);
  return new Date().toLocaleDateString(localeCode, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

export function makeActiveClassMap(styles: Record<string, string>): Record<Signal, string> {
  const result = {} as Record<Signal, string>;
  for (const [signal, cssKey] of Object.entries(SIGNAL_TO_CLASS) as [Signal, string][]) {
    const cls = styles[cssKey];
    if (!cls) throw new Error(`makeActiveClassMap: CSS class "${cssKey}" is missing from styles module`);
    result[signal] = cls;
  }
  return result;
}
