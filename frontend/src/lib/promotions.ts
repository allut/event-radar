import { TALLINN_TZ } from '../_generated/sharedConstants';
import {
  PROMOTION_DETAIL_COPY,
  PROMOTION_GATE_REASON_LABELS,
  PROMOTION_GATE_SHOWN,
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

export interface PromotionActions {
  mark_paid: boolean;
  edit: boolean;
  edit_scope: 'full' | 'end_date' | null;
  repoint: boolean;
  end: boolean;
  void: boolean;
  refund: boolean;
  refundable_cents: number;
}

export interface RepointCandidate {
  event_id: number;
  title: string;
  last_day: string;
}

export interface PromotionSnapshot {
  id: number;
  taken_at: string;
  trigger: string;
  event_id: number;
  title: { et: string | null; en: string | null; ru: string | null };
  description_excerpt: string | null;
  image_url: string | null;
  venue_name: string | null;
  event_starts_at: string | null;
  event_ends_at: string | null;
  start_date: string;
  end_date: string;
  net_price_cents: number;
  vat_rate_percent: string;
  label_text: string;
}

export interface PromotionAuditEntry {
  action: string;
  result: string;
  created_at: string;
}

export interface PromotionDetail extends PromotionRow {
  organizer_id: number;
  invoice_source: string | null;
  advertiser_registry_code: string;
  billing_email: string | null;
  granted_by: string | null;
  paid_at: string | null;
  ended_at: string | null;
  end_reason: string | null;
  end_note: string | null;
  refunded_cents: number;
  refund_note: string | null;
  created_at: string | null;
  event: {
    id: number;
    title: string;
    starts_at: string;
    ends_at: string | null;
    last_day: string;
    venue_name: string | null;
  };
  actions: PromotionActions;
  repoint_candidates: RepointCandidate[];
  snapshots: PromotionSnapshot[];
  audit: PromotionAuditEntry[];
}

export interface PromotionDailyStat {
  day: string;
  gate_outcome: string | null;
  gate_reason: string | null;
  explore_served: number;
  daily5_placed: number;
  digest_sent: number;
  web_opens: number;
  digest_opens: number;
  slot_dislikes: number;
}

export interface PromotionDailyStatsResponse {
  promotion_id: number;
  today: string;
  days: PromotionDailyStat[];
}

// The numeric columns of the per-day table, in display order.
export const DAILY_STAT_COLUMNS = [
  { key: 'explore_served', label: 'Explore served' },
  { key: 'daily5_placed', label: 'Daily 5 placed' },
  { key: 'digest_sent', label: 'Digest sent' },
  { key: 'web_opens', label: 'Web opens' },
  { key: 'digest_opens', label: 'Digest opens' },
  { key: 'slot_dislikes', label: 'Slot dislikes' },
] as const;

export function dailyStatTotals(days: PromotionDailyStat[]): number[] {
  return DAILY_STAT_COLUMNS.map((c) => days.reduce((sum, d) => sum + d[c.key], 0));
}

/** "Shown", "Paused · claim inactive", or "—" when no gate outcome was recorded. */
export function gateLabel(stat: PromotionDailyStat): string {
  if (stat.gate_outcome === null) return PROMOTION_DETAIL_COPY.notRecorded;
  if (stat.gate_outcome === PROMOTION_GATE_SHOWN) return 'Shown';
  const reason = stat.gate_reason ? (PROMOTION_GATE_REASON_LABELS[stat.gate_reason] ?? stat.gate_reason) : null;
  return reason ? `${PROMOTION_DETAIL_COPY.pausedPrefix} · ${reason}` : PROMOTION_DETAIL_COPY.pausedPrefix;
}

/** The not-showing line under the header pill: the unpaid countdown, the
 * stated end reason, or the latest recorded pause while live. */
export function detailReason(p: PromotionDetail, days: PromotionDailyStat[]): string | null {
  const pill = promotionPill(p);
  if (pill.reason) return pill.reason;
  if ((p.status === PROMOTION_STATUS.endedEarly || p.status === PROMOTION_STATUS.void) && p.end_note) {
    return `${p.status === PROMOTION_STATUS.void ? 'Voided' : 'Ended'}: ${p.end_note}`;
  }
  const latest = days.length > 0 ? days[days.length - 1] : null;
  if (p.state === PROMOTION_STATE.live && latest && latest.gate_outcome !== null && latest.gate_outcome !== PROMOTION_GATE_SHOWN) {
    return gateLabel(latest);
  }
  return null;
}

const DATE_TIME_FORMAT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: TALLINN_TZ,
});

/** "13 Oct 2026, 11:20" in Tallinn time. */
export function formatDateTime(iso: string): string {
  return DATE_TIME_FORMAT.format(new Date(iso));
}

/** Euros typed as "12.50" (or "12,5") to whole cents; null when not a positive amount. */
export function parseEuroToCents(text: string): number | null {
  const normalised = text.trim().replace(',', '.');
  if (!/^\d+(\.\d{1,2})?$/.test(normalised)) return null;
  const cents = Math.round(Number(normalised) * 100);
  return cents > 0 ? cents : null;
}
