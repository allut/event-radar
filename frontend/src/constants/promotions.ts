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

// Promotion detail (#601, #606): action panels, per-day table, snapshots.
export const PROMOTION_REASON_ROWS = 2;
export const PROMOTION_GATE_SHOWN = 'shown';

// Backend PROMOTION_NOT_SHOWING_* codes, worded for the per-day table.
export const PROMOTION_GATE_REASON_LABELS: Readonly<Record<string, string>> = {
  slots_disabled: 'slots off',
  bot_user_agent: 'bot request',
  not_paid: 'not paid',
  outside_window: 'outside window',
  event_not_public: 'event not public',
  event_not_canonical: 'lost duplicate',
  event_ended: 'event ended',
  organizer_not_owner: 'claim inactive',
  restriction_unassessed: 'restriction unassessed',
  restriction_flagged: 'restricted',
  filters_mismatch: 'filters mismatch',
};

// Backend PROMOTION_SNAPSHOT_TRIGGER_*.
export const PROMOTION_SNAPSHOT_TRIGGER_LABELS: Readonly<Record<string, string>> = {
  grant: 'grant',
  mark_paid: 'mark paid',
  edit: 'edit',
  repoint: 're-point',
};

export const PROMOTION_ACTION = {
  markPaid: 'mark_paid',
  edit: 'edit',
  repoint: 'repoint',
  end: 'end',
  void: 'void',
  refund: 'refund',
} as const;
export type PromotionActionKey = (typeof PROMOTION_ACTION)[keyof typeof PROMOTION_ACTION];

export const PROMOTION_EDIT_SCOPE = { full: 'full', endDate: 'end_date' } as const;

export const PROMOTION_ACTION_LABELS: Readonly<Record<PromotionActionKey, string>> = {
  mark_paid: 'Mark paid',
  edit: 'Edit',
  repoint: 'Re-point',
  end: 'End early',
  void: 'Void',
  refund: 'Record refund',
};

export const PROMOTION_DETAIL_COPY = {
  loadFailed: 'Couldn’t load this Promotion.',
  back: '← Promotions',
  actionsHeading: 'Actions',
  recordHeading: 'Commercial record',
  deliveryHeading: 'Delivery · per day',
  snapshotsHeading: 'Content snapshots · newest first',
  auditHeading: 'Audit',
  actionsHint: 'Buttons follow what the server allows for this Promotion’s state.',
  noActions: 'No actions left except refunds: this Promotion has ended.',
  noActionsAtAll: 'No actions are available for this Promotion.',
  cancel: 'Cancel',
  invoiceOptional: 'Invoice reference (optional)',
  invoiceInvalid: `Invoice reference must start with ${PROMOTION_INVOICE_PREFIX}.`,
  editFullHeading: 'Edit Promotion',
  editShortenHeading: 'Shorten live window',
  editFullNote:
    'Before the start date: dates (cap rechecked, price recomputed), advertiser details and invoice reference.',
  editShortenNote:
    'Live: only an earlier end date, never before today. The price paid stays; refund unused days separately.',
  noChanges: 'Change something first.',
  repointHeading: 'Re-point to another event',
  repointLabel: 'Same Organizer, same duplicate group',
  repointNone: 'No other event of this Organizer in the same duplicate group.',
  repointPick: 'Pick an event.',
  endHeading: 'End early',
  endNote: 'Releases every remaining cap day now and stops the slot immediately.',
  voidHeading: 'Void',
  reasonLabel: 'Reason (emailed to the Organizer)',
  reasonRequired: 'Give a reason. It is emailed to the Organizer.',
  refundHeading: 'Record refund',
  refundAmountLabel: 'Amount (gross, €)',
  refundNoteLabel: 'Note (required)',
  refundNoteRequired: 'A note is required.',
  deliveryNote:
    '“Served” is not “seen”. Complete days only, updated daily. Known bots are excluded. Anonymous totals; no viewer data. Today is not shown until it ends.',
  noDays: 'No complete days yet. The first row appears the morning after the start date.',
  noSnapshots: 'No snapshots yet. One is taken when the Promotion is paid.',
  noAudit: 'No audit entries.',
  pausedPrefix: 'Paused',
  notRecorded: '—',
} as const;
