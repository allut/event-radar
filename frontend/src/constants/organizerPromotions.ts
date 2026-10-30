// Organizer Promotions (#614, #616, #617, #618): statuses, gate-reason copy keys,
// form rules and polling. Strings are i18n keys (shared/i18n `promo_*`).
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import {
  PROMOTION_ERROR_BUSINESS_ATTESTATION,
  PROMOTION_ERROR_CHECKOUT_ATTESTATION,
  PROMOTION_ERROR_CHECKOUT_NOT_PROMOTABLE,
  PROMOTION_ERROR_CHECKOUT_TERMS,
  PROMOTION_ERROR_ENDS_AFTER_EVENT,
  PROMOTION_ERROR_INVALID_REGISTRY_CODE,
  PROMOTION_ERROR_NOT_PROMOTABLE,
  PROMOTION_ERROR_OVERLAP,
  PROMOTION_ERROR_REGISTRY_CHECKSUM,
  PROMOTION_ERROR_REQUEST_DAILY_LIMIT,
  PROMOTION_ERROR_REQUEST_PENDING,
  PROMOTION_ERROR_STARTS_TOO_EARLY,
  PROMOTION_ERROR_TERMS_NOT_ACCEPTED,
  PROMOTION_ERROR_WINDOW_ORDER,
  PROMOTION_NOT_SHOWING_BOT,
  PROMOTION_NOT_SHOWING_EVENT_ENDED,
  PROMOTION_NOT_SHOWING_EVENT_NOT_CANONICAL,
  PROMOTION_NOT_SHOWING_EVENT_NOT_PUBLIC,
  PROMOTION_NOT_SHOWING_FILTERS_MISMATCH,
  PROMOTION_NOT_SHOWING_NOT_OWNED,
  PROMOTION_NOT_SHOWING_NOT_PAID,
  PROMOTION_NOT_SHOWING_OUTSIDE_WINDOW,
  PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED,
  PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED,
  PROMOTION_NOT_SHOWING_SLOTS_DISABLED,
} from '../_generated/sharedConstants.js';

// GET /organizer/promotions item `status`; each is a `promo_status_*` key.
export const PROMOTION_LIST_STATUS = {
  requested: 'requested',
  declined: 'declined',
  awaitingPayment: 'awaiting_payment',
  awaitingCheckout: 'awaiting_checkout',
  scheduled: 'scheduled',
  live: 'live',
  paused: 'paused',
  finished: 'finished',
  endedEarly: 'ended_early',
  cancelled: 'cancelled',
} as const;

export type PromotionListStatus = (typeof PROMOTION_LIST_STATUS)[keyof typeof PROMOTION_LIST_STATUS];

export const PROMOTION_KIND = { request: 'request', promotion: 'promotion' } as const;

// Statuses whose item still holds days (the row's badge replaces "Promote").
export const PROMOTION_RUNNING_STATUSES: ReadonlySet<string> = new Set([
  PROMOTION_LIST_STATUS.awaitingPayment,
  PROMOTION_LIST_STATUS.awaitingCheckout,
  PROMOTION_LIST_STATUS.scheduled,
  PROMOTION_LIST_STATUS.live,
  PROMOTION_LIST_STATUS.paused,
]);

// Statuses at which a card payment has been taken: the success page stops polling.
export const PROMOTION_PAID_STATUSES: ReadonlySet<string> = new Set([
  PROMOTION_LIST_STATUS.scheduled,
  PROMOTION_LIST_STATUS.live,
  PROMOTION_LIST_STATUS.paused,
  PROMOTION_LIST_STATUS.finished,
]);

// The fill gate's not-showing codes (shared) that have their own plain-words
// copy (`promo_why_<code>` and `_short`); any other code falls back to
// `promo_why_unknown`.
export const PROMOTION_PAUSE_REASONS: ReadonlySet<string> = new Set([
  PROMOTION_NOT_SHOWING_SLOTS_DISABLED,
  PROMOTION_NOT_SHOWING_BOT,
  PROMOTION_NOT_SHOWING_NOT_PAID,
  PROMOTION_NOT_SHOWING_OUTSIDE_WINDOW,
  PROMOTION_NOT_SHOWING_EVENT_NOT_PUBLIC,
  PROMOTION_NOT_SHOWING_EVENT_NOT_CANONICAL,
  PROMOTION_NOT_SHOWING_EVENT_ENDED,
  PROMOTION_NOT_SHOWING_NOT_OWNED,
  PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED,
  PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED,
  PROMOTION_NOT_SHOWING_FILTERS_MISMATCH,
]);
export const PROMOTION_PAUSE_REASON_FALLBACK = 'unknown';

// The day price, VAT rate, checkout hold and longest window (PROMOTION_DAY_PRICE_CENTS,
// PROMOTION_VAT_RATE_PERCENT, PROMOTION_CHECKOUT_SESSION_MINUTES, PROMOTION_MAX_DAYS) are
// cross-stack: _generated/sharedConstants.ts. The Promotions page explainer has no event,
// so no /context answer, to read the price from; the form takes the live values from /context.

export const PROMOTION_REGISTRY_CODE_LENGTH = 8;
export const PROMOTION_REGISTRY_CODE_PLACEHOLDER = '1'.repeat(PROMOTION_REGISTRY_CODE_LENGTH);
export const PROMOTION_NOTE_ROWS = 3;
export const PROMOTION_NOTE_MAX_LEN = 2000;
export const PROMOTION_LEGAL_NAME_MAX_LEN = 255;

// Window violation and request codes (shared PROMOTION_ERROR_*) the form words
// itself. The window-length, cap, registry-lookup and checkout codes it reacts
// to are imported from _generated/sharedConstants.ts where they're used.
export const PROMOTION_FORM_ERROR_KEYS: Readonly<Record<string, string>> = {
  [PROMOTION_ERROR_WINDOW_ORDER]: 'promo_err_order',
  [PROMOTION_ERROR_STARTS_TOO_EARLY]: 'promo_err_start',
  [PROMOTION_ERROR_ENDS_AFTER_EVENT]: 'promo_err_end',
  [PROMOTION_ERROR_OVERLAP]: 'promo_err_overlap',
  [PROMOTION_ERROR_REQUEST_PENDING]: 'promo_err_pending',
  [PROMOTION_ERROR_REQUEST_DAILY_LIMIT]: 'promo_err_daily_limit',
  [PROMOTION_ERROR_NOT_PROMOTABLE]: 'promo_err_not_promotable',
  [PROMOTION_ERROR_CHECKOUT_NOT_PROMOTABLE]: 'promo_err_not_promotable',
  [PROMOTION_ERROR_TERMS_NOT_ACCEPTED]: 'promo_err_terms',
  [PROMOTION_ERROR_CHECKOUT_TERMS]: 'promo_err_terms',
  [PROMOTION_ERROR_CHECKOUT_ATTESTATION]: 'promo_err_policy',
  [PROMOTION_ERROR_BUSINESS_ATTESTATION]: 'promo_need_business',
  [PROMOTION_ERROR_INVALID_REGISTRY_CODE]: 'promo_need_code',
  [PROMOTION_ERROR_REGISTRY_CHECKSUM]: 'promo_need_code',
};

// The Promotions page and success page re-ask the list this often while a card
// payment is still being confirmed, and stop after the cap.
export const PROMOTION_CONFIRM_POLL_MS = 3000;
export const PROMOTION_CONFIRM_POLL_MAX = 20;

// Query param on /organizer/promotions that scrolls to an event's open item
// (the badge on a row links there).
export const PROMOTION_EVENT_PARAM = 'event';
// Query params of the request form and the Stripe return.
export const PROMOTION_FORM_EVENT_PARAM = 'event_id';
export const PROMOTION_SUCCESS_ID_PARAM = 'promotion_id';

// Visual tone of a status badge (one CSS modifier per tone).
export type PromotionBadgeTone = 'live' | 'attention' | 'scheduled' | 'bad' | 'muted';

export const PROMOTION_STATUS_TONE: Readonly<Record<string, PromotionBadgeTone>> = {
  requested: 'attention',
  awaiting_payment: 'attention',
  awaiting_checkout: 'attention',
  paused: 'attention',
  scheduled: 'scheduled',
  live: 'live',
  declined: 'bad',
  ended_early: 'bad',
  finished: 'muted',
  cancelled: 'muted',
};
