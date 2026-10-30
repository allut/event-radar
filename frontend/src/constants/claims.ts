// Organizer claiming: claim statuses, kinds, verification mechanisms, admin labels, and claim error codes.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import {
  CLAIM_DISCOVERY_STATUS_CLAIMED,
  CLAIM_DISCOVERY_STATUS_NOT_CLAIMABLE,
  CLAIM_DISCOVERY_STATUS_PENDING,
  CLAIM_DISCOVERY_STATUS_UNCLAIMED,
  CLAIM_KIND_PUBLISHER,
  CLAIM_KIND_SERIES,
  CLAIM_STATUS_APPROVED,
  CLAIM_STATUS_CANCELLED,
  CLAIM_STATUS_DECLINED,
  CLAIM_STATUS_EXPIRED,
  CLAIM_STATUS_PENDING,
  CLAIM_STATUS_REVOKED,
  CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
  CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
  CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
  CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
  CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
} from '../_generated/sharedConstants.js';
import { LOCALE_EN, LOCALE_ET, LOCALE_RU } from './core.js';
import { EXPLORE_SEARCH_DEBOUNCE_MS } from './explore.js';

// Claim kinds, statuses, verification mechanisms, discovery statuses and the
// claim error codes are cross-stack: _generated/sharedConstants.ts. #415's
// ClaimPending screen switches its mechanism-specific copy off the mechanisms.
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
// piletilevi_mailbox (#428) is never self-service: the organizer can't fix a
// mailbox mismatch from this screen.
export const CLAIM_SELF_SERVICE_VERIFICATION_MECHANISMS: ReadonlySet<ClaimVerificationMechanism> = new Set([
  CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
  CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
  CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
]);

// CLAIM_STATUS_REVOKED is a real admin revoke of a granted claim (row deleted
// server-side): the backend only reports it for the AdminAction-built
// tombstone. CLAIM_STATUS_DECLINED is a declined pending claim, admin or auto
// (#447): stored as "revoked", but reported as "declined" for a live row.
export type ClaimStatus =
  | typeof CLAIM_STATUS_PENDING
  | typeof CLAIM_STATUS_APPROVED
  | typeof CLAIM_STATUS_CANCELLED
  | typeof CLAIM_STATUS_EXPIRED
  | typeof CLAIM_STATUS_REVOKED
  | typeof CLAIM_STATUS_DECLINED;

// Claim target kind — a Publisher or a Series.
export type ClaimKind = typeof CLAIM_KIND_PUBLISHER | typeof CLAIM_KIND_SERIES;

// Public `claim_status` an event reports (backend claim-discovery status).
export type EventClaimStatus =
  | typeof CLAIM_DISCOVERY_STATUS_UNCLAIMED
  | typeof CLAIM_DISCOVERY_STATUS_PENDING
  | typeof CLAIM_DISCOVERY_STATUS_CLAIMED
  | typeof CLAIM_DISCOVERY_STATUS_NOT_CLAIMABLE;

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
