// Organizer claiming: claim statuses, kinds, verification mechanisms, admin labels, and claim error codes.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { LOCALE_EN, LOCALE_ET, LOCALE_RU } from './core.js';
import { EXPLORE_SEARCH_DEBOUNCE_MS } from './explore.js';

// Mirrors backend CLAIM_VERIFICATION_MECHANISM_* / CLAIM_STATUS_* (app/constants/claims.py)
// — #415's ClaimPending screen switches its mechanism-specific copy off these.
export const CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN = 'fienta_token';
export const CLAIM_VERIFICATION_MECHANISM_DNS_TXT = 'dns_txt';
export const CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER = 'piletilevi_promoter';
// (#428) Piletilevi's mailbox-match fallback tier — never self-service: the
// organizer can't fix a mismatch from this screen (unlike DNS-TXT/Fienta),
// so it's deliberately excluded from CLAIM_SELF_SERVICE_VERIFICATION_MECHANISMS
// below and behaves like admin_review in #415's pending screen.
export const CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX = 'piletilevi_mailbox';
export const CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW = 'admin_review';
export type ClaimVerificationMechanism =
  | typeof CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN
  | typeof CLAIM_VERIFICATION_MECHANISM_DNS_TXT
  | typeof CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER
  | typeof CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX
  | typeof CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW;
export const CLAIM_DNS_VERIFICATION_MECHANISMS: ReadonlySet<ClaimVerificationMechanism> = new Set([
  CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
  CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
]);
// The mechanisms with something an organizer can actually go do (add a DNS
// record, place a code in their listing) — #415's pending screen shows the
// "keep checking in background" hint only for these; every other mechanism
// (admin_review, piletilevi_mailbox) gets the admin-review hint instead.
export const CLAIM_SELF_SERVICE_VERIFICATION_MECHANISMS: ReadonlySet<ClaimVerificationMechanism> = new Set([
  CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
  CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
  CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
]);

// Mirrors backend ERROR_CLAIM_JUSTIFICATION_REQUIRED (app/constants/claims.py) — the
// one claim-creation error the UI reacts to structurally (revealing the
// justification field, #428) rather than just displaying; matched by exact
// string since claim creation has no structured error-code contract.
export const CLAIM_JUSTIFICATION_REQUIRED_ERROR =
  'A justification is required for a series claim (no specific promoter' +
  ' could be identified for this listing).';

// Mirrors backend CLAIM_ERROR_CODE_NOT_GRANTED/CLAIM_ERROR_CODE_DORMANT
// (app/constants/claims.py) — the two reasons the claim-editing surface's GET/PATCH
// can 409, told apart via ApiError.code rather than the English message (#444).
export const CLAIM_ERROR_CODE_NOT_GRANTED = 'claim_not_granted';
export const CLAIM_ERROR_CODE_DORMANT = 'claim_dormant';

export const CLAIM_STATUS_PENDING = 'pending';
export const CLAIM_STATUS_APPROVED = 'approved';
export const CLAIM_STATUS_CANCELLED = 'cancelled';
export const CLAIM_STATUS_EXPIRED = 'expired';
// A real admin revoke of a granted claim (row deleted server-side) — the
// backend only ever reports this for the AdminAction-built tombstone.
export const CLAIM_STATUS_REVOKED = 'revoked';
// A declined pending claim, admin or auto (#447) — the backend still stores
// this as "revoked" internally, but never reports that literal for a row
// that still exists, only this one.
export const CLAIM_STATUS_DECLINED = 'declined';
export type ClaimStatus =
  | typeof CLAIM_STATUS_PENDING
  | typeof CLAIM_STATUS_APPROVED
  | typeof CLAIM_STATUS_CANCELLED
  | typeof CLAIM_STATUS_EXPIRED
  | typeof CLAIM_STATUS_REVOKED
  | typeof CLAIM_STATUS_DECLINED;

// Claim target kind — a Publisher or a Series (mirrors backend claim `kind`).
export const CLAIM_KIND_PUBLISHER = 'publisher';
export const CLAIM_KIND_SERIES = 'series';
export type ClaimKind = typeof CLAIM_KIND_PUBLISHER | typeof CLAIM_KIND_SERIES;

// Public `claim_status` an event reports (mirrors backend EVENT_CLAIM_STATUS_*).
export const EVENT_CLAIM_STATUS_UNCLAIMED = 'unclaimed';
export const EVENT_CLAIM_STATUS_PENDING = 'pending';
export const EVENT_CLAIM_STATUS_CLAIMED = 'claimed';
export const EVENT_CLAIM_STATUS_NOT_CLAIMABLE = 'not_claimable';
export type EventClaimStatus =
  | typeof EVENT_CLAIM_STATUS_UNCLAIMED
  | typeof EVENT_CLAIM_STATUS_PENDING
  | typeof EVENT_CLAIM_STATUS_CLAIMED
  | typeof EVENT_CLAIM_STATUS_NOT_CLAIMABLE;

// Admin claims queue: badge text per verification mechanism, and the resolution
// tag shown for each admin action.
export const ADMIN_CLAIM_MECHANISM_LABELS: Record<string, string> = {
  [CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN]: 'Fienta',
  [CLAIM_VERIFICATION_MECHANISM_DNS_TXT]: 'DNS-TXT',
  [CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER]: 'DNS-TXT',
  [CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX]: 'Contact mailbox',
  [CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW]: 'Admin review',
};
// Success line shown after an admin resolves a report or submission — shared by
// the queue rows and the event-detail action bar.
export const ADMIN_RESOLUTION_MESSAGES = {
  resolved: 'Resolved.',
  taken_down: 'Event taken down.',
  approved: 'Submission approved.',
  retracted: 'Submission retracted.',
} as const;
export type AdminResolutionKind = keyof typeof ADMIN_RESOLUTION_MESSAGES;
export type AdminClaimActionKind = 'granted' | 'declined' | 'revoked';
export const ADMIN_CLAIM_ACTION_TAGS: Record<AdminClaimActionKind, string> = {
  granted: 'Granted',
  declined: 'Declined',
  revoked: 'Revoked',
};

// Closed, no further action possible — never involved an admin for cancelled/expired,
// so ClaimPending's terminal screens must not show the pending pill or "Admin review" eyebrow (#449).
export const CLAIM_TERMINAL_STATUSES: ReadonlySet<ClaimStatus> = new Set([
  CLAIM_STATUS_CANCELLED,
  CLAIM_STATUS_EXPIRED,
  CLAIM_STATUS_REVOKED,
  CLAIM_STATUS_DECLINED,
]);

/** Localized-text slots the claim-edit form renders, in display order. */
export const CLAIM_EDIT_LOCALES = [LOCALE_ET, LOCALE_EN, LOCALE_RU] as const;

export const CLAIM_SEARCH_MIN_CHARS = 2;
export const CLAIM_SEARCH_DEBOUNCE_MS = EXPLORE_SEARCH_DEBOUNCE_MS;

// ─── Organizer: Your claims (/organizer/claims, spec #551) ─────────────────
// The page size, ORGANIZER_OWN_CLAIMS_PAGE_SIZE, is cross-stack: _generated/sharedConstants.ts.
// The dashboard summary line only reads `total` and `pending_count`, so it
// asks GET /organizer/claims for the smallest page it allows.
export const ORGANIZER_CLAIMS_SUMMARY_LIMIT = 1;
/** Segment nested under QUERY_KEYS.organizerClaims for the dashboard summary query. */
export const ORGANIZER_CLAIMS_SUMMARY_KEY = 'summary';

// ─── Organizer: Publisher-claim event list (page size CLAIM_EVENTS_PAGE_SIZE is cross-stack) ───
