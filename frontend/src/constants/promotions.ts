// Admin Promotions (#600): list paging, state filter, pill labels, form rules.
// Admin console is English-only, so these are plain strings (no shared/i18n).
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

export const ADMIN_PROMOTIONS_PAGE_SIZE = 50;

// URL param carrying the list's state filter; omitted for "All".
export const ADMIN_PROMOTIONS_STATE_PARAM = 'state';

export const PROMOTION_STATE = {
  scheduled: 'scheduled',
  live: 'live',
  finished: 'finished',
} as const;

export const PROMOTION_STATUS = {
  unpaid: 'unpaid',
  paid: 'paid',
  endedEarly: 'ended_early',
  void: 'void',
} as const;

export const ADMIN_PROMOTIONS_STATE_FILTERS = [
  { value: '', label: 'All' },
  { value: PROMOTION_STATE.live, label: 'Live' },
  { value: PROMOTION_STATE.scheduled, label: 'Scheduled' },
  { value: PROMOTION_STATE.finished, label: 'Finished' },
] as const;

export type PromotionPillTone = 'live' | 'scheduled' | 'finished' | 'attention';

// Mirrors backend PROMOTION_INVOICE_PREFIX / PROMOTION_REGISTRY_CODE_RE: the
// form pre-checks these for instant feedback; the server stays authoritative.
export const PROMOTION_INVOICE_PREFIX = 'ER-M-';
export const PROMOTION_REGISTRY_CODE_RE = /^\d{8}$/;
export const PROMOTION_NOTE_ROWS = 2;

// Rule-violation codes (backend PROMOTION_ERROR_*) that flag the start date
// field; every other window, overlap or cap error flags the end date.
export const PROMOTION_ERROR_START_CODES: ReadonlySet<string> = new Set(['starts_too_early']);

export const PROMOTION_COPY = {
  capStripHeading: 'Cap · next 14 days',
  listHeading: 'Promotions',
  grantHeading: 'Grant Promotion',
  legendLive: 'Live',
  legendReserved: 'Reserved (scheduled or unpaid)',
  legendFull: 'Full',
  legendSelected: 'Selected in form',
  noPromotions: 'No Promotions',
  noPromotionsHint: 'Granted Promotions appear here.',
  loadFailed: 'Couldn’t load Promotions.',
  noOwner:
    'This event has no owning Organizer, so it cannot be promoted. An Organizer must have submitted it or hold an approved claim on it.',
  pickDates: 'Pick a start and end date.',
  datesAvailable: 'Dates are available.',
  checking: 'Checking dates…',
  nameRequired: 'Advertiser legal name is required.',
  registryInvalid: 'Registry code must be 8 digits.',
  invoiceInvalid: `Invoice reference must start with ${PROMOTION_INVOICE_PREFIX}.`,
  noteRequired: 'Complimentary grants need a note.',
  granted: 'Promotion granted.',
  complimentary: 'Complimentary',
  complimentaryPrice: 'Complimentary · €0.00',
} as const;
