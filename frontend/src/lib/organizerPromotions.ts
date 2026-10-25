// Organizer Promotions (#614, #616, #617, #618): response shapes and the pure
// helpers the list, the form and the success page share. Dates are Tallinn
// calendar days (`YYYY-MM-DD`), formatted in UTC so the browser zone can't move them.
import { LOCALE_EN, toLocaleCode } from '../constants/core';
import {
  PROMOTION_PAUSE_REASON_FALLBACK,
  PROMOTION_PAUSE_REASONS,
  PROMOTION_REGISTRY_CODE_LENGTH,
  type PromotionListStatus,
} from '../constants/organizerPromotions';
import { formatCount } from '../utils';
import { tn } from '../i18n';

export interface PromotionPrice {
  net_cents: number;
  vat_cents: number;
  gross_cents: number;
}

/** One row of GET /organizer/promotions: a request or a Promotion. */
export interface OrganizerPromotionItem {
  kind: 'request' | 'promotion';
  id: number;
  event_id: number;
  event_title: string;
  status: PromotionListStatus;
  paused_reason: string | null;
  decline_reason: string | null;
  note: string | null;
  start_date: string;
  end_date: string;
  days: number;
  advertiser_legal_name: string;
  advertiser_registry_code: string;
  /** Where the invoice or receipt goes; null on older rows. */
  billing_email: string | null;
  price: PromotionPrice;
  can_withdraw: boolean;
  has_report: boolean;
  created_at: string;
  /** Stripe's hosted invoice, on a card-paid Promotion (when the API sends it). */
  invoice_url?: string | null;
}

export interface OrganizerPromotionsResponse {
  items: OrganizerPromotionItem[];
}

/** The `promotion` key on an event row of the Organizer's event lists. It is
 * absent while the offer flag is off. */
export interface PromotionRowFlags {
  promotable: boolean;
  badge: PromotionListStatus | null;
}

export interface PromotionRequestContext {
  event_id: number;
  event_title: string;
  promotable: boolean;
  badge: PromotionListStatus | null;
  /** Card checkout is switched on (the offer is on, or this route would 404). */
  checkout_available: boolean;
  /** The event is not assessed clear, so card checkout would refuse it. */
  review_required: boolean;
  today: string;
  earliest_start: string;
  event_last_day: string;
  rules: { min_days: number; max_days: number };
  pricing: { day_price_cents: number; vat_rate_percent: string };
  terms_version: number;
  billing_email_default: string;
  unavailable_dates: string[];
}

export interface PromotionRuleError {
  code: string;
  message: string;
  dates: string[];
}

export interface PromotionValidation {
  valid: boolean;
  errors: PromotionRuleError[];
  days: number;
  price: PromotionPrice;
}

export interface PromotionReportDay {
  day: string;
  shown: boolean;
  paused: boolean;
  paused_reason: string | null;
  explore_served: number;
  daily5_placed: number;
  digest_sent: number;
  web_opens: number;
  digest_opens: number;
}

export interface PromotionReport {
  promotion_id: number;
  event_id: number;
  start_date: string;
  end_date: string;
  updated: string;
  through: string | null;
  daily5_reach: number | null;
  days: PromotionReportDay[];
}

export interface RegistryLookupResult {
  registry_code: string;
  legal_name: string;
}

export interface CheckoutStarted {
  promotion_id: number;
  checkout_url: string;
  expires_at: string | null;
}

export interface PromotionRequestCreated {
  id: number;
  event_title: string;
  start_date: string;
  end_date: string;
  days: number;
  advertiser_legal_name: string;
  price: PromotionPrice;
}

export function isIsoDay(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`));
}

function utcDay(iso: string): Date {
  return new Date(`${iso}T00:00:00Z`);
}

function dayFormat(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat(toLocaleCode(locale), { ...options, timeZone: 'UTC' });
}

/** "Sat, 24 Oct". */
export function formatPromoDay(iso: string, locale: string): string {
  return dayFormat(locale, { weekday: 'short', day: 'numeric', month: 'short' }).format(utcDay(iso));
}

function formatShortDay(iso: string, locale: string): string {
  return dayFormat(locale, { day: 'numeric', month: 'short' }).format(utcDay(iso));
}

/** "12–18 Oct", "24 Oct – 2 Nov", or one day. */
export function formatPromoRange(start: string, end: string, locale: string): string {
  if (start === end) return formatShortDay(start, locale);
  if (start.slice(0, 7) === end.slice(0, 7)) {
    return `${dayFormat(locale, { day: 'numeric' }).format(utcDay(start))}–${formatShortDay(end, locale)}`;
  }
  return `${formatShortDay(start, locale)} – ${formatShortDay(end, locale)}`;
}

/** "5 days" / "5 päeva" / "5 дней". */
export function formatPromoDays(count: number, locale: string): string {
  return tn('promo_days', locale, count, { count: formatCount(count, locale) });
}

/** "€5", "€6.20" (en) or "€6,20" (et, ru): whole euros drop the cents.
 * `symbol: false` returns the bare number, for callers that place the € themselves. */
export function formatMoney(cents: number, locale: string, { symbol = true }: { symbol?: boolean } = {}): string {
  const whole = cents % 100 === 0;
  const digits = whole ? String(cents / 100) : (cents / 100).toFixed(2);
  const amount = locale === LOCALE_EN ? digits : digits.replace('.', ',');
  return symbol ? `€${amount}` : amount;
}

/** Net plus VAT, rounded to the cent. Mirrors the backend's gross-price math. */
export function grossCents(netCents: number, vatPercent: number): number {
  return Math.round((netCents * (100 + vatPercent)) / 100);
}

/** Estonian business-register code check digit. The server stays the authority;
 * this only spares the lookup round trip for a typo. */
export function isRegistryCodeValid(code: string): boolean {
  if (!new RegExp(`^\\d{${PROMOTION_REGISTRY_CODE_LENGTH}}$`).test(code)) return false;
  const digits = code.split('').map(Number);
  const weighted = (weights: number[]) => weights.reduce((sum, w, i) => sum + w * digits[i], 0) % 11;
  let check = weighted([1, 2, 3, 4, 5, 6, 7]);
  if (check === 10) {
    check = weighted([3, 4, 5, 6, 7, 8, 9]);
    if (check === 10) check = 0;
  }
  return check === digits[7];
}

/** `promo_why_*` key suffix for a gate not-showing code. */
export function pauseReasonKey(code: string | null): string {
  return code && PROMOTION_PAUSE_REASONS.has(code) ? code : PROMOTION_PAUSE_REASON_FALLBACK;
}

/** Splits a translation around one `{name}` placeholder so a link can sit inside the sentence. */
export function splitAround(template: string, name: string): [string, string] {
  const [before, after = ''] = template.split(`{${name}}`);
  return [before, after];
}
