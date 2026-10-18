// Organizer portal: field limits, image upload, content languages, event editor settings.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { ORGANIZER_IMAGE_ALLOWED_MIME } from '../_generated/sharedConstants.js';
import { type ContentLang, LOCALE_ET } from './core.js';

// Client-only dismissal flag for the profile nudge banner (#175) — no backend
// field for this, so a stale/cleared browser just re-shows it once.
export const ORGANIZER_PROFILE_NUDGE_DISMISSED_KEY = 'organizer_profile_nudge_dismissed';

// Mirrors backend ORGANIZER_NAME_MAX_LEN (app/constants/organizer.py).
export const ORGANIZER_NAME_MAX_LEN = 255;
// Mirrors backend ORGANIZER_VENUE_NAME_MAX_LEN/ORGANIZER_VENUE_ADDRESS_MAX_LEN (app/constants/organizer.py).
export const ORGANIZER_VENUE_NAME_MAX_LEN = 255;
export const ORGANIZER_VENUE_ADDRESS_MAX_LEN = 500;

// ─── Organizer submission ────────────────────────────────────────────────────
// ORGANIZER_IMAGE_ALLOWED_MIME (_generated/sharedConstants.ts) is sourced from
// shared/app-config.json, mirroring the backend's IMAGE_UPLOAD_ALLOWED_MIME.
// The server re-validates the MIME type itself and is the actual security
// boundary — this only lets the picker reject an obviously-wrong file before
// spending a network round trip on it.
export const ORGANIZER_IMAGE_ACCEPT = ORGANIZER_IMAGE_ALLOWED_MIME.join(',');
export const ORGANIZER_EVENTS_PAGE_SIZE = 24;
/** Segment nested under QUERY_KEYS.organizerEvents for the single-event (edit prefill) query. */
export const ORGANIZER_EVENT_DETAIL_KEY = 'detail';

export const ORGANIZER_BASE_CONTENT_LANG: ContentLang = LOCALE_ET;

// ─── Organizer submission — price inputs ────────────────────────────────────
export const PRICE_INPUT_MIN = '0';
export const PRICE_INPUT_STEP = '0.01';

// Heading levels the organizer rich-text editor offers (h1/h2 stay page chrome).
export const RICH_TEXT_HEADING_LEVELS = [3, 4] as const;

// localStorage hint: whether the Promotions offer is on, learned from the
// `promotion` key on event rows or the Promotions list. Lets the top bar show
// its "Promotions" nav item without a request of its own.
export const ORGANIZER_PROMOTIONS_OFFER_KEY = 'organizer_promotions_offer';
