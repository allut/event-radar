import { TALLINN_TZ } from '../_generated/sharedConstants';
import { ApiError } from '../api/client';
import { MS_PER_DAY } from '../constants/core';
import { apiErrorMessage } from '../utils';
import {
  PROMOTION_DETAIL_COPY,
  PROMOTION_GATE_REASON_LABELS,
  PROMOTION_INVOICE_SOURCE_STRIPE,
  PROMOTION_RESTRICTION_NONE,
  PROMOTION_SLOT_WITHDRAWAL_SOURCES,
  PROMOTION_SLOTS_STILL_ENABLED_CODE,
  PROMOTION_STRIPE_COPY,
  PROMOTION_TRIPWIRE_MIN_COMPLAINTS,
  PROMOTION_TRIPWIRE_MIN_DISLIKES,
  PROMOTION_TRIPWIRE_MIN_UPHELD,
  PROMOTION_TRIPWIRE_MIN_WITHDRAWALS,
  PROMOTION_TRUST_COPY,
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
  refunded_cents: number;
  invoice_source: string | null;
  invoice_url: string | null;
  awaiting_checkout: boolean;
  checkout_expires_at: string | null;
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
  promotion_restriction?: string | null;
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

const TIME_FORMAT = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: TALLINN_TZ });

/** "15:42" in Tallinn time. */
export function formatTime(iso: string): string {
  return TIME_FORMAT.format(new Date(iso));
}

export function isStripePaid(p: { invoice_source: string | null }): boolean {
  return p.invoice_source === PROMOTION_INVOICE_SOURCE_STRIPE;
}

/** A restriction tag ("alcohol") worded for a tag chip; null for clear or unassessed. */
export function restrictionTag(restriction: string | null | undefined): string | null {
  if (restriction === null || restriction === undefined || restriction === PROMOTION_RESTRICTION_NONE) return null;
  return restriction.charAt(0).toUpperCase() + restriction.slice(1);
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
  if (p.status === PROMOTION_STATUS.unpaid && p.awaiting_checkout) {
    return {
      label: PROMOTION_STRIPE_COPY.awaitingCheckout,
      tone: 'attention',
      reason: `Organizer is in Stripe Checkout${p.checkout_expires_at ? ` · session expires ${formatTime(p.checkout_expires_at)}` : ''}, voids on its own`,
    };
  }
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

export interface PromotionRestrictionClearance {
  restriction: string;
  by: string;
  note: string;
  cleared_at: string | null;
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
  /** The event's current restriction is not covered by this Promotion's clearance (#612). */
  clear_restriction: boolean;
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
  /** The audit row's JSON `result`: a status snapshot plus the command's own fields. */
  result: Record<string, unknown>;
  created_at: string;
}

const AUDIT_DETAIL_KEYS = ['actor', 'reason', 'note', 'invoice_reference', 'end_reason', 'to_event_id', 'changes'] as const;

/** One line of what a command recorded ("reason: …, invoice_reference: ER-M-1"). The
 * status snapshot every row carries is left out. */
export function auditSummary(result: PromotionAuditEntry['result']): string {
  if (typeof result !== 'object' || result === null) return String(result ?? '');
  return AUDIT_DETAIL_KEYS.flatMap((key) => {
    const value = result[key];
    if (value === undefined || value === null || value === '') return [];
    return [`${key}: ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`];
  }).join(', ');
}

export interface RefundPrefill {
  mode: 'stripe' | 'manual';
  unused_days: number;
  paused_days: number;
  gross_per_day_cents: number;
  suggested_cents: number;
  remaining_cents: number;
}

export interface PromotionDetail extends PromotionRow {
  organizer_id: number;
  refund_prefill: RefundPrefill | null;
  advertiser_registry_code: string;
  billing_email: string | null;
  granted_by: string | null;
  paid_at: string | null;
  ended_at: string | null;
  end_reason: string | null;
  end_note: string | null;
  refund_note: string | null;
  created_at: string | null;
  event: {
    id: number;
    title: string;
    starts_at: string;
    ends_at: string | null;
    last_day: string;
    venue_name: string | null;
    promotion_restriction?: string | null;
  };
  restriction_clearance: PromotionRestrictionClearance | null;
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

/** The lowercase restriction tag of a paid Promotion whose event was flagged
 * after its clearance (or without one); null otherwise (#612). */
export function newlyFlaggedTag(p: PromotionDetail): string | null {
  if (p.status !== PROMOTION_STATUS.paid || !p.actions.clear_restriction) return null;
  return restrictionTag(p.event.promotion_restriction)?.toLowerCase() ?? null;
}

/** The header pill: a live Promotion that the restriction gate pauses reads
 * "Paused" in the attention tone. */
export function detailPill(p: PromotionDetail): ReturnType<typeof promotionPill> {
  const pill = promotionPill(p);
  if (p.state === PROMOTION_STATE.live && newlyFlaggedTag(p) !== null) {
    return { ...pill, label: PROMOTION_DETAIL_COPY.pausedPrefix, tone: 'attention' };
  }
  return pill;
}

/** The not-showing line under the header pill: the unpaid countdown, the
 * stated end reason, or the latest recorded pause while live. */
export function detailReason(p: PromotionDetail, days: PromotionDailyStat[]): string | null {
  const flagged = newlyFlaggedTag(p);
  if (flagged !== null) return PROMOTION_DETAIL_COPY.restrictionPaused(flagged);
  const pill = promotionPill(p);
  if (p.awaiting_checkout) {
    return PROMOTION_STRIPE_COPY.checkoutReason(p.checkout_expires_at ? formatTime(p.checkout_expires_at) : null);
  }
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

const DAY_MONTH_FORMAT = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: TALLINN_TZ });

/** "11 Oct" in Tallinn time. */
export function formatDayMonth(iso: string): string {
  return DAY_MONTH_FORMAT.format(new Date(iso));
}

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

export interface PromotionRequestRow {
  id: number;
  event_id: number;
  event_title: string;
  organizer_id: number;
  organizer_name: string;
  organizer_email: string;
  status: string;
  start_date: string;
  end_date: string;
  days: number;
  price: PromotionPrice;
  advertiser_legal_name: string;
  advertiser_registry_code: string;
  billing_email: string | null;
  note: string | null;
  decline_reason: string | null;
  promotion_restriction: string | null;
  not_eligible_reason: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface PromotionRequestsResponse {
  pending_count: number;
  requests: PromotionRequestRow[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface TrustPeriod {
  reports_on_promoted: number;
  reports_resolved: number;
  promotions_taken_down: number;
  consents_granted: number;
  consent_withdrawals: { total: number; by_source: Record<string, number> };
  slots_served: number;
  slots_served_by_surface: Record<string, number>;
  web_opens: number;
  slot_dislikes: number;
  complaints: number;
}

export interface PromotionComplaint {
  id: number;
  created_at: string;
  source: string | null;
  complainant: string | null;
  note: string | null;
}

export interface TrustResponse {
  as_of: string;
  window_days: number;
  window_start: string;
  current: { live_promotions: number; consenters: number };
  periods: { rolling_4_weeks: TrustPeriod; since_launch: TrustPeriod };
  recent_complaints: PromotionComplaint[];
}

/** A withdraw failure worded for the admin: the slots-flag 409 gets its runbook step. */
export function withdrawErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.status === 409 && (err.code ?? err.message) === PROMOTION_SLOTS_STILL_ENABLED_CODE) {
    return PROMOTION_TRUST_COPY.slotsStillEnabled;
  }
  return apiErrorMessage(err, fallback);
}

export interface Tripwire {
  key: string;
  tripped: boolean;
  rule: string;
  figures: string;
}

/** The four stop-selling conditions over the rolling 4 weeks, with the figures
 * behind each. Guidance only: nothing here flips a flag. */
export function evaluateTripwires(p: TrustPeriod): Tripwire[] {
  const T = PROMOTION_TRUST_COPY;
  const withdrawals = PROMOTION_SLOT_WITHDRAWAL_SOURCES.reduce((n, s) => n + (p.consent_withdrawals.by_source[s] ?? 0), 0);
  return [
    {
      key: 'withdrawals',
      tripped: withdrawals > p.consents_granted && withdrawals >= PROMOTION_TRIPWIRE_MIN_WITHDRAWALS,
      rule: T.tripwireWithdrawals,
      figures: T.figWithdrawals(withdrawals, p.consents_granted),
    },
    {
      key: 'dislikes',
      tripped: p.slot_dislikes > p.web_opens && p.slot_dislikes >= PROMOTION_TRIPWIRE_MIN_DISLIKES,
      rule: T.tripwireDislikes,
      figures: T.figDislikes(p.slot_dislikes, p.web_opens),
    },
    {
      key: 'complaints',
      tripped: p.complaints >= PROMOTION_TRIPWIRE_MIN_COMPLAINTS,
      rule: T.tripwireComplaints,
      figures: p.complaints >= PROMOTION_TRIPWIRE_MIN_COMPLAINTS ? T.figComplaintsCheck(p.complaints) : T.figComplaints(p.complaints),
    },
    {
      key: 'reports',
      tripped: p.promotions_taken_down >= PROMOTION_TRIPWIRE_MIN_UPHELD,
      rule: T.tripwireReports,
      figures: T.figReports(p.promotions_taken_down, p.reports_on_promoted),
    },
  ];
}

/** Whole days of the window that never started: all of them while scheduled,
 * the days after today while live. Mirrors backend withdraw.py::unused_days(). */
export function unusedDays(p: Pick<PromotionRow, 'start_date' | 'end_date' | 'days'>, today: string): number {
  if (p.start_date > today) return p.days;
  return Math.max(Math.round((Date.parse(p.end_date) - Date.parse(today)) / MS_PER_DAY), 0);
}

/** The refund Withdraw will record for `unused` days: the exact amount paid
 * for the whole window, otherwise the net share plus its VAT, never beyond
 * what is still refundable. Mirrors backend withdraw.py::refund_for_unused(). */
export function withdrawRefundCents(p: PromotionRow, unused: number): number {
  if (p.is_complimentary || unused <= 0) return 0;
  const rate = Number(p.vat_rate_percent);
  const vat = (net: number) => Math.round((net * rate) / 100);
  const gross = p.net_price_cents + vat(p.net_price_cents);
  let owed = gross;
  if (unused < p.days) {
    const net = Math.floor((p.net_price_cents * unused) / p.days);
    owed = net + vat(net);
  }
  return Math.max(Math.min(owed, gross - p.refunded_cents), 0);
}
