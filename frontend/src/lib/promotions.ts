import {
  PROMOTION_STATE,
  PROMOTION_STATUS,
  type PromotionPillTone,
} from '../constants/promotions';

export interface PromotionRow {
  id: number;
  event_id: number;
  event_title: string;
  organizer_name: string | null;
  status: string;
  state: string;
  start_date: string;
  end_date: string;
  days: number;
  net_price_cents: number;
  vat_rate_percent: string;
  vat_cents: number;
  gross_price_cents: number;
  is_complimentary: boolean;
  complimentary_note: string | null;
  invoice_reference: string | null;
  advertiser_legal_name: string;
}

export interface CapDay {
  date: string;
  reserved: number;
  paid: number;
  unpaid: number;
  live: number;
  cap: number;
  free: number;
}

export interface CapStripResponse {
  today: string;
  cap: number;
  days: CapDay[];
}

export interface PromotionPrice {
  net_cents: number;
  vat_cents: number;
  gross_cents: number;
}

export interface PromotionContext {
  event_id: number;
  event_title: string;
  owner: { organizer_id: number; name: string; email: string | null } | null;
  prefill: { advertiser_legal_name: string | null; billing_email: string | null };
  today: string;
  earliest_start: string;
  event_last_day: string;
  rules: { min_days: number; max_days: number; cap: number; cap_strip_days: number };
  pricing: { day_price_cents: number; vat_rate_percent: string };
  promotions: PromotionRow[];
}

export interface PromotionValidation {
  valid: boolean;
  errors: { code: string; message: string; dates: string[] }[];
  days: number;
  price: PromotionPrice;
}

const ISO_DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

export function isIsoDay(value: string): boolean {
  return ISO_DAY_RE.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`));
}

const DAY_FORMAT = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
const DAY_SHORT_FORMAT = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const WEEKDAY_FORMAT = new Intl.DateTimeFormat('en-GB', { weekday: 'short', timeZone: 'UTC' });
const DAY_NUM_FORMAT = new Intl.DateTimeFormat('en-GB', { day: 'numeric', timeZone: 'UTC' });

// ISO calendar days are Tallinn dates; format them in UTC so the viewer's
// timezone can never shift the day.
function utcDay(iso: string): Date {
  return new Date(`${iso}T00:00:00Z`);
}

export function formatDay(iso: string): string {
  return DAY_FORMAT.format(utcDay(iso));
}

export function formatWeekday(iso: string): string {
  return WEEKDAY_FORMAT.format(utcDay(iso));
}

export function formatDayNumber(iso: string): string {
  return DAY_NUM_FORMAT.format(utcDay(iso));
}

/** "12–18 Oct" or "24 Oct – 2 Nov". */
export function formatWindow(start: string, end: string): string {
  const [s, e] = [utcDay(start), utcDay(end)];
  if (s.getUTCMonth() === e.getUTCMonth() && s.getUTCFullYear() === e.getUTCFullYear()) {
    return `${DAY_NUM_FORMAT.format(s)}–${DAY_SHORT_FORMAT.format(e)}`;
  }
  return `${DAY_SHORT_FORMAT.format(s)} – ${DAY_SHORT_FORMAT.format(e)}`;
}

export function formatEuro(cents: number): string {
  return `€${(cents / 100).toFixed(2)}`;
}

export function priceLine(price: PromotionPrice): string {
  return `${formatEuro(price.net_cents)} + ${formatEuro(price.vat_cents)} VAT = ${formatEuro(price.gross_cents)}`;
}

export function promotionPriceLabel(p: PromotionRow): string {
  return p.is_complimentary ? 'Complimentary' : `${formatEuro(p.net_price_cents)} + VAT`;
}

/** The pill a row shows: the computed state, refined by the stored commercial
 * status (awaiting payment, ended early, void). `reason` is the not-showing
 * line under it, when there is one. */
export function promotionPill(p: PromotionRow): { label: string; tone: PromotionPillTone; reason: string | null } {
  if (p.status === PROMOTION_STATUS.void) return { label: 'Void', tone: 'finished', reason: null };
  if (p.status === PROMOTION_STATUS.endedEarly) return { label: 'Ended early', tone: 'finished', reason: null };
  if (p.state === PROMOTION_STATE.finished) return { label: 'Finished', tone: 'finished', reason: null };
  if (p.status === PROMOTION_STATUS.unpaid) {
    return {
      label: 'Awaiting payment',
      tone: 'attention',
      reason: `Unpaid · voids when ${formatDay(p.start_date)} begins`,
    };
  }
  if (p.state === PROMOTION_STATE.live) return { label: 'Live', tone: 'live', reason: null };
  return { label: 'Scheduled', tone: 'scheduled', reason: null };
}
