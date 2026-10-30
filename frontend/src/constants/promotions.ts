// Admin Promotions (#600): list paging, state filter, pill labels, form rules.
// Admin console is English-only, so these are plain strings (no shared/i18n).
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { PROMOTION_INVOICE_PREFIX, PROMOTION_REGISTRY_CODE_PATTERN } from '../_generated/sharedConstants.js';

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

// The form pre-checks the invoice prefix (PROMOTION_INVOICE_PREFIX,
// _generated/sharedConstants.ts) and the registry code for instant feedback;
// the server stays authoritative. The code pattern is shared and anchored here
// as the backend's fullmatch is; both run shared/fixtures/promotion_registry_codes.json.
export const PROMOTION_REGISTRY_CODE_RE = new RegExp(`^(?:${PROMOTION_REGISTRY_CODE_PATTERN})$`);
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
  clearRestriction: 'clear_restriction',
  markPaid: 'mark_paid',
  edit: 'edit',
  repoint: 'repoint',
  end: 'end',
  void: 'void',
  refund: 'refund',
  withdraw: 'withdraw',
} as const;
export type PromotionActionKey = (typeof PROMOTION_ACTION)[keyof typeof PROMOTION_ACTION];

export const PROMOTION_EDIT_SCOPE = { full: 'full', endDate: 'end_date' } as const;

export const PROMOTION_ACTION_LABELS: Readonly<Record<PromotionActionKey, string>> = {
  clear_restriction: 'Clear restriction',
  mark_paid: 'Mark paid',
  edit: 'Edit',
  repoint: 'Re-point',
  end: 'End early',
  void: 'Void',
  refund: 'Record refund',
  withdraw: 'Withdraw',
};

export const PROMOTION_DETAIL_COPY = {
  withdrawHeading: 'Withdraw this Promotion',
  withdrawNote:
    'Ends it with feature_withdrawn and records a full refund of its unused days. The Organizer gets the P2B email. Needs the slots flag off.',
  withdrawConfirm: 'Withdraw',
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
  clearHeading: (tag: string) => `Clear restriction: ${tag}`,
  clearNote: (tag: string) =>
    `Records that you reviewed this event for the ${tag} restriction. The Promotion resumes. It covers only this restriction, so a different flag pauses it again.`,
  clearNoteLabel: 'Clearance note (required)',
  clearNoteRequired: 'Add a clearance note. It is recorded with your name.',
  clearConfirm: 'Clear restriction',
  restrictionPaused: (tag: string) =>
    `Paused: the event was flagged for the ${tag} restriction after the Promotion was scheduled. Clear the restriction to resume it, or end it early.`,
  eventRestrictionLabel: 'Event restriction',
  clearanceLabel: 'Restriction clearance',
  clearanceNoteRowLabel: 'Clearance note',
  restrictionNone: 'None',
  notRecorded: '—',
} as const;

// Request queue (#615): status tabs, row copy and the not-grantable reasons.
export const ADMIN_PROMOTION_REQUESTS_PAGE_SIZE = 50;
// URL param that opens the queue on a non-pending status; omitted while pending.
export const ADMIN_PROMOTION_REQUESTS_PARAM = 'requests';
export const PROMOTION_REQUEST_STATUS = {
  pending: 'pending',
  granted: 'granted',
  declined: 'declined',
  expired: 'expired',
} as const;
export const PROMOTION_REQUEST_STATUS_OPTIONS = [
  { value: PROMOTION_REQUEST_STATUS.pending, label: 'Pending' },
  { value: PROMOTION_REQUEST_STATUS.granted, label: 'Granted' },
  { value: PROMOTION_REQUEST_STATUS.declined, label: 'Declined' },
  { value: PROMOTION_REQUEST_STATUS.expired, label: 'Expired' },
] as const;
export const PROMOTION_DECLINE_ROWS = 4;
// Backend PROMOTION_NOT_SHOWING_NOT_OWNED: a dormant claim, which can recover.
export const PROMOTION_REQUEST_DORMANT_CODE = 'organizer_not_owner';
export const PROMOTION_RESTRICTION_NONE = 'none';

// Backend PROMOTION_ERROR_* rule codes, worded for a request row.
export const PROMOTION_REQUEST_REASON_LABELS: Readonly<Record<string, string>> = {
  no_owner: 'The event has no owning Organizer.',
  window_order: 'The end date is before the start date.',
  window_too_short: 'The window is shorter than the minimum.',
  window_too_long: 'The window is longer than the maximum.',
  starts_too_early: 'The start date has passed. Pick dates from tomorrow.',
  ends_after_event: 'The window ends after the event’s last day.',
  overlap: 'The window overlaps another Promotion on this event.',
  cap_exceeded: 'A day in the window is already full.',
  not_promotable: 'The event cannot be promoted right now.',
  organizer_not_owner: 'Your claim is inactive, so this event cannot be promoted yet.',
};

export const PROMOTION_REQUEST_COPY = {
  heading: 'Requests',
  pendingCount: (n: number) => `${n} pending`,
  statusLabel: 'Request status',
  hint: 'Oldest first. A request stays pending through a dormant claim or dates that no longer fit; it expires at once when its event is cancelled or its claim revoked, and otherwise at its start date.',
  historyHint: 'Newest first.',
  showHistory: 'Show history',
  noPending: 'No pending requests',
  noPendingHint: 'Requests from the Organizer portal appear here, oldest first.',
  nothingHere: 'Nothing here',
  noneInStatus: (status: string) => `No ${status} requests yet.`,
  loadFailed: 'Couldn’t load the requests.',
  truncated: (shown: number, total: number) => `Showing the first ${shown} of ${total}.`,
  grant: 'Grant',
  decline: 'Decline',
  notAssessed: 'Not assessed',
  organizerNote: 'Organizer note: ',
  notGrantable: 'Not grantable as requested: ',
  dormantTail: 'Stays pending until the claim is active again.',
  editTail: 'Edit the dates in the grant form, or leave it to expire at its start date.',
  reasonSent: 'Reason sent: ',
  grantHeading: (id: number) => `Grant Promotion from request #${id}`,
  requestedBy: 'Requested by',
  datesMatch: 'Dates match the request.',
  datesDiffer: (window: string) => `Dates differ from the request (${window}). Fine when agreed with the Organizer.`,
  grantNote:
    'Granting creates the Promotion and marks the request granted in one step, audited as promotion_request_grant. Nothing is emailed to the Organizer, so send the invoice yourself.',
  granted: (title: string) => `Promotion granted for ${title}. The request is marked granted. The Organizer was not emailed.`,
  declined: (title: string) => `Declined ${title}. The reason is queued as an email to the Organizer.`,
  declineHeading: (title: string) => `Decline request for ${title}`,
  declineTo: (email: string) => `The reason is emailed to ${email} in their language. Write it so the Organizer knows what to change.`,
  declineReasonLabel: 'Reason (required, sent to the Organizer)',
  declineReasonRequired: 'Give a reason. It is emailed to the Organizer.',
  declineConfirm: 'Decline request',
  restrictionTitle: (tag: string) => `This event carries the ${tag} restriction`,
  restrictionBody: 'It cannot show until you review it and record a clearance. Granting without one is refused.',
  clearanceAck: 'I reviewed this event and clear it for a Promotion despite the restriction.',
  clearanceNoteLabel: 'Clearance note (required)',
  clearanceAckRequired: 'Tick the box to confirm you reviewed the event.',
  clearanceNoteRequired: 'Add a clearance note. It is recorded with your name.',
  unassessedTitle: 'This event has not been assessed yet',
  unassessedBody:
    'The Promotion is saved, but the slot stays empty until the content policy check marks the event clear or you clear its restriction later.',
} as const;

// Stripe look in the list and the detail (#618, #619).
export const PROMOTION_INVOICE_SOURCE_STRIPE = 'stripe';
export const PROMOTION_INVOICE_SOURCE_MANUAL = 'manual';
export const PROMOTION_STRIPE_COPY = {
  datesLocked: "A card-paid Promotion's dates cannot change. End it early or refund part of it instead.",
  chip: 'Stripe',
  bankChip: 'Bank transfer',
  paidByCard: 'Paid by card via Stripe',
  checkoutOpen: 'Stripe Checkout open',
  awaitingCheckout: 'Awaiting checkout',
  invoiceColumn: 'Invoice',
  hostedInvoice: 'hosted invoice',
  invoiceAfterPayment: 'Issued when Stripe confirms payment',
  paymentLabel: 'Payment',
  stripeCard: 'Stripe card',
  bankTransfer: 'Bank transfer',
  listHint:
    'Awaiting checkout: the Organizer has opened Stripe and not finished. It holds its days until the session expires (30 min, swept at +1 h) and then voids on its own. Abandoned checkouts drop out of the Organizer’s list but stay visible here while open.',
  checkoutOpenHint: 'Mark paid is not offered: Stripe marks it paid when the card payment completes. Void is the only action while checkout is open.',
  voidNote: 'Voiding an open checkout also expires its Stripe session. A payment that lands afterwards is refunded in full automatically.',
  refundHeading: 'Issue refund',
  refundSuggested: 'Suggested: ',
  refundCardNote: (invoice: string | null) =>
    `Issuing creates a credit note against ${invoice ?? 'the invoice'} (reversing the VAT) and refunds the card, in one step. Audited as promotion_refund.`,
  refundPerDayNote: (gross: string, days: number) =>
    `Price per day is what was paid (${gross} incl. VAT over ${days} days). Paused days come from the daily stats and count in the Organizer’s favour. Edit the amount for a partial or goodwill refund.`,
  refundManualNote: 'Record-only: this does not move money. Pay it back off-platform first.',
  refundMax: (max: string) => `Up to ${max} (paid, minus refunded)`,
  refundPlaceholder: 'Why is this refund being issued?',
  issueRefund: (amount: string | null) => (amount ? `Issue refund of ${amount}` : 'Issue refund'),
  stripeActionLabel: 'Issue refund',
  checkoutReason: (expires: string | null) =>
    `Organizer is in Stripe Checkout.${expires ? ` The session expires ${expires};` : ''} This voids on its own an hour after that. Days are held meanwhile.`,
  creditNoteHint: (invoice: string | null) =>
    `Issue refund creates a credit note against ${invoice ?? 'the invoice'} (reversing the VAT) and refunds the card in one step.`,
  bankRefundHint: 'Bank-transfer refunds are record-only: pay the money back yourself, then record it here. Withdraw needs the slots flag off.',
  checkoutExpires: 'Checkout expires',
  pricePerDay: 'Price per day (gross)',
  daysUnusedPaused: 'Days unused / paused',
} as const;

// Trust panel, complaint logger and Withdraw (#620).
export const PROMOTION_COMPLAINT_NOTE_ROWS = 3;
export const PROMOTION_COMPLAINT_NOTE_MAX = 1000;
export const PROMOTION_COMPLAINT_SOURCES = [
  { value: 'email', label: 'Email' },
  { value: 'contact_form', label: 'Contact form' },
  { value: 'other', label: 'Other' },
] as const;
export const PROMOTION_COMPLAINT_SOURCE_DEFAULT = 'email';
export const PROMOTION_SLOTS_STILL_ENABLED_CODE = 'slots_still_enabled';
// One page of live or scheduled Promotions is the whole Withdraw table (backend max page size).
export const ADMIN_PROMOTIONS_WITHDRAW_LIMIT = 500;
export const PROMOTION_PERIODS = ['rolling_4_weeks', 'since_launch'] as const;
export type PromotionPeriod = (typeof PROMOTION_PERIODS)[number];
export const PROMOTION_PERIOD_LABELS: Readonly<Record<PromotionPeriod, string>> = {
  rolling_4_weeks: 'Rolling 4 weeks',
  since_launch: 'Since launch',
};
// Backend consent sources (EmailAdConsentLog.source), worded for the panel.
export const PROMOTION_CONSENT_SOURCE_LABELS: Readonly<Record<string, string>> = {
  settings: 'Settings toggle',
  email_link: 'Slot email link',
  email_link_undo: 'Slot email link undo',
  digest_unsubscribe: 'Digest unsubscribe',
  wording_change: 'Wording change',
  account_deletion: 'Account deletion',
};
export const PROMOTION_SURFACE_LABELS: Readonly<Record<string, string>> = {
  explore: 'Explore',
  daily5: 'Daily 5',
  digest: 'Digest',
};
// docs/backend-ops.md "Promotions: Trust Review and Withdrawal" thresholds.
export const PROMOTION_TRIPWIRE_MIN_WITHDRAWALS = 3;
export const PROMOTION_TRIPWIRE_MIN_DISLIKES = 3;
export const PROMOTION_TRIPWIRE_MIN_COMPLAINTS = 2;
export const PROMOTION_TRIPWIRE_MIN_UPHELD = 2;
export const PROMOTION_SLOT_WITHDRAWAL_SOURCES = ['settings', 'email_link'] as const;

export const PROMOTION_TRUST_COPY = {
  heading: 'Trust panel',
  loadFailed: 'Couldn’t load the Trust panel.',
  livePromotions: 'Live Promotions',
  currentConsenters: 'Current consenters',
  complaintsLogged: 'Complaints logged',
  reports: 'Reports on promoted events',
  reportsSub: (upheld: number, resolved: number) => `upheld ${upheld} · resolved ${resolved}`,
  consentsGranted: 'Consents granted',
  consentsGrantedSub: 'Email ad consent',
  withdrawals: 'Consent withdrawals',
  slotsServed: 'Slots served',
  webOpens: 'Web opens from the slot',
  dislikes: 'Slot dislikes',
  adminOnly: 'admin-only',
  complaints: 'Complaints logged',
  sinceFirstSale: 'since first sale',
  panelHint: (start: string) =>
    `Rolling 4 weeks runs from ${start} (window_start). Slot dislikes and complaints are admin-only; they never reach an Organizer. Read only: nothing here flips a flag.`,
  tripwiresHeading: 'Stop-selling tripwires · rolling 4 weeks',
  tripped: 'Tripped',
  clear: 'Clear',
  tripwireWithdrawals: 'Consent withdrawals through the slot link or the toggle outnumber new consents, with at least 3 withdrawals.',
  tripwireDislikes: 'Slot dislikes outnumber web opens from the slot, with at least 3 dislikes.',
  tripwireComplaints: 'At least 2 complaints about the ads from different people.',
  tripwireReports: 'At least 2 upheld reports on promoted events: the eligibility bar may be too loose.',
  figWithdrawals: (w: number, c: number) => `${w} withdrawals (settings + slot link) vs ${c} new consents`,
  figDislikes: (d: number, o: number) => `${d} dislikes vs ${o} web opens`,
  figComplaints: (n: number) => `${n} logged`,
  figComplaintsCheck: (n: number) => `${n} logged (check the names below are different people)`,
  figReports: (upheld: number, all: number) => `${upheld} upheld, ${all} reports in all`,
  verdictTripped: (n: number) => `${n} of 4 stop-selling conditions hold`,
  verdictTrippedBody:
    'Stop selling: set PROMOTIONS_OFFER_ENABLED and PROMOTIONS_CHECKOUT_ENABLED off in Render and restart. Slots keep filling and live or scheduled Promotions run to the end of their window. Decline pending requests by hand with a reason.',
  verdictClear: 'No stop-selling condition holds',
  verdictClearBody: 'Nothing to do this week. Review again next week.',
  thresholdsHint:
    'Thresholds from docs/backend-ops.md, Promotions: Trust Review and Withdrawal. Withdraw at once on regulator contact (TTJA or AKI) about ad disclosure or a dark-pattern problem, and when a Stop-selling condition still holds 4 weeks after a fix.',
  complaintHeading: 'Log a complaint',
  complaintSource: 'Arrived by',
  complaintWho: 'Complainant (optional)',
  complaintWhoPlaceholder: 'Name or address. Two complaints from one person count once.',
  complaintNote: 'Note (required)',
  complaintNotePlaceholder: 'What did they say, and which placement or email were they talking about?',
  complaintNoteRequired: 'A note is required. Say what they said and where they saw it.',
  complaintSubmit: 'Log complaint',
  complaintAudit: 'Audited as promotion_complaint. Counted in the panel above.',
  complaintLogged: 'Complaint logged and counted above.',
  recentHeading: 'Recent complaints',
  noComplaints: 'No complaints logged.',
  noName: 'No name given',
  withdrawHeading: 'Withdraw',
  slotsOnTitle: 'Withdraw needs the slots flag off',
  slotsOnBody:
    'The server refuses with 409 slots_still_enabled until PROMOTIONS_SLOTS_ENABLED is off, so no ad is still served while Promotions end. The buttons below stay clickable and show that refusal if the flag is still on.',
  slotsStillEnabled: 'Slots are still enabled. Turn PROMOTIONS_SLOTS_ENABLED off in Render and restart, then try again.',
  steps: [
    'Stop selling: offer and checkout flags off, restart.',
    'Slots flag off, restart.',
    'End each paid Promotion below, or all at once.',
  ],
  colEvent: 'Event',
  colWindow: 'Window',
  colUnused: 'Unused days',
  colRefund: 'Refund on withdraw',
  noRefund: '€0.00 (nothing to refund)',
  withdraw: 'Withdraw',
  withdrawAll: (n: number) => `Withdraw all (${n})`,
  noneLeft: 'No paid Promotions left to withdraw.',
  withdrawOneHeading: 'Withdraw this Promotion',
  withdrawOneBody:
    'Ends it with feature_withdrawn and records a full refund of its unused days. The Organizer gets the P2B email. Needs the slots flag off.',
  withdrawAllHeading: (n: number) => `Withdraw all ${n} paid Promotions`,
  withdrawAllBody:
    'Each ends with feature_withdrawn, records a full refund of its unused whole days (today counts as used; scheduled ones refund in full; complimentary have nothing to refund), emails each Organizer the P2B notice and writes an audit row. One failing Promotion is skipped and listed; the rest still end.',
  withdrawAck: 'I turned the slots flag off and understand this cannot be undone.',
  withdrawAckRequired: 'Tick the box to confirm.',
  withdrawn: (n: number, refunds: string) => `Withdrew ${n} Promotion${n === 1 ? '' : 's'} · ${refunds} refunds recorded`,
  withdrawnUnused: (days: number) => `${days} unused days`,
  withdrawnRefund: (amount: string) => `${amount} recorded`,
  withdrawnNothing: 'nothing to refund',
  withdrawnHint: 'Each Organizer was emailed the P2B notice and each end and refund wrote an audit row.',
  withdrawnStripe: (titles: string) => ` Withdraw records the refund only. Issue the card refund in Stripe for ${titles}.`,
  skipped: (n: number) => `Skipped ${n}`,
  skippedHint: 'The rest still ended. Open a skipped Promotion to see why, then withdraw it on its own page.',
  withdrawFailed: 'Couldn’t withdraw.',
  loadWithdrawFailed: 'Couldn’t load the paid Promotions.',
} as const;

export const PROMOTION_TRUST_HEADING = 'Trust review';
export const PROMOTION_TRUST_CADENCE = 'weekly for the first 4 weeks after the first sale, then with the price review';

// ActionPanels.tsx: the inline panels' headings, buttons and field labels.
export const PROMOTION_ACTION_PANEL_COPY = {
  markPaidHeading: 'Mark paid',
  markPaidConfirm: 'Confirm mark paid',
  saveChanges: 'Save changes',
  startDate: 'Start date',
  endDate: 'End date',
  advertiserName: 'Advertiser legal name',
  registryCode: 'Registry code',
  billingEmail: 'Billing email',
  invoiceReference: 'Invoice reference',
  repointConfirm: 'Confirm re-point',
  endEarlyConfirm: 'Confirm end early',
  voidConfirm: 'Confirm void',
  refundConfirm: 'Confirm refund',
} as const;

// AdminPromotionDetail.tsx: the commercial record's row labels.
export const PROMOTION_RECORD_LABEL = {
  advertiser: 'Advertiser',
  registryCode: 'Registry code',
  billingEmail: 'Billing email',
  organizer: 'Organizer',
  grantedBy: 'Granted by',
  netPrice: 'Net price',
  netPriceComplimentary: '€0.00 (complimentary)',
  gross: 'Gross',
  invoice: 'Invoice',
  paidAt: 'Paid at',
  refunded: 'Refunded',
  complimentaryNote: 'Complimentary note',
  refundNote: 'Refund note',
} as const;

// Pill labels (promotionPill) and the per-day table's "Shown" outcome.
export const PROMOTION_PILL_LABEL = {
  void: 'Void',
  endedEarly: 'Ended early',
  finished: 'Finished',
  awaitingPayment: 'Awaiting payment',
  live: 'Live',
  scheduled: 'Scheduled',
  shown: 'Shown',
} as const;

// Column headers of the per-day table, keyed by PromotionDailyStat field.
export const PROMOTION_DAILY_STAT_LABELS = {
  explore_served: 'Explore served',
  daily5_placed: 'Daily 5 placed',
  digest_sent: 'Digest sent',
  web_opens: 'Web opens',
  digest_opens: 'Digest opens',
  slot_dislikes: 'Slot dislikes',
} as const;
