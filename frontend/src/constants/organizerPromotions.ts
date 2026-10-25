// Organizer Promotions (#614, #616, #617, #618): statuses, gate-reason copy keys,
// form rules and polling. Strings are i18n keys (shared/i18n `promo_*`).
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

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

// The fill gate's not-showing codes (backend PROMOTION_NOT_SHOWING_*) that
// have their own plain-words copy (`promo_why_<code>` and `_short`); any other
// code falls back to `promo_why_unknown`.
export const PROMOTION_PAUSE_REASONS: ReadonlySet<string> = new Set([
  'slots_disabled',
  'bot_user_agent',
  'not_paid',
  'outside_window',
  'event_not_public',
  'event_not_canonical',
  'event_ended',
  'organizer_not_owner',
  'restriction_unassessed',
  'restriction_flagged',
  'filters_mismatch',
]);
export const PROMOTION_PAUSE_REASON_FALLBACK = 'unknown';

// Mirrors backend PROMOTION_DAY_PRICE_CENTS / PROMOTION_VAT_RATE_PERCENT: the
// explainer on the Promotions page has no event, so no /context answer, to read
// them from. The form takes the live values from /context.
export const PROMOTION_DAY_NET_CENTS = 500;
export const PROMOTION_VAT_PERCENT = 24;

// Backend PROMOTION_CHECKOUT_SESSION_MINUTES: how long card checkout holds the days.
export const PROMOTION_CHECKOUT_HOLD_MINUTES = 30;

// Mirrors backend PROMOTION_MAX_DAYS: the end picker's furthest day from the start.
export const PROMOTION_MAX_DAYS = 14;

export const PROMOTION_REGISTRY_CODE_LENGTH = 8;
export const PROMOTION_REGISTRY_CODE_PLACEHOLDER = '1'.repeat(PROMOTION_REGISTRY_CODE_LENGTH);
export const PROMOTION_NOTE_ROWS = 3;
export const PROMOTION_NOTE_MAX_LEN = 2000;
export const PROMOTION_LEGAL_NAME_MAX_LEN = 255;

// Window violation codes (backend PROMOTION_ERROR_*) the form words itself.
export const PROMOTION_FORM_ERROR_KEYS: Readonly<Record<string, string>> = {
  window_order: 'promo_err_order',
  starts_too_early: 'promo_err_start',
  ends_after_event: 'promo_err_end',
  overlap: 'promo_err_overlap',
  request_pending: 'promo_err_pending',
  daily_request_limit: 'promo_err_daily_limit',
  not_promotable: 'promo_err_not_promotable',
  event_not_promotable: 'promo_err_not_promotable',
  terms_not_accepted: 'promo_err_terms',
  organizer_terms_required: 'promo_err_terms',
  content_policy_attestation_required: 'promo_err_policy',
  invalid_registry_code: 'promo_need_code',
  registry_code_checksum: 'promo_need_code',
};
export const PROMOTION_ERROR_TOO_SHORT = 'window_too_short';
export const PROMOTION_ERROR_TOO_LONG = 'window_too_long';
export const PROMOTION_ERROR_CAP_EXCEEDED = 'cap_exceeded';

// Registry lookup refusals (backend PROMOTION_ERROR_REGISTRY_*).
export const PROMOTION_REGISTRY_CODE = {
  invalid: 'registry_invalid_code',
  deleted: 'registry_company_deleted',
  notFound: 'registry_company_not_found',
  unavailable: 'registry_unavailable',
} as const;

// Checkout refusals the form reacts to structurally (backend PROMOTION_ERROR_CHECKOUT_*).
export const PROMOTION_CHECKOUT_CODE = {
  needsReview: 'event_needs_review',
  provider: 'checkout_unavailable',
} as const;

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
