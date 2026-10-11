// Google Analytics: gtag script, route grouping, and tracked event names.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { LOCALE_URL_PREFIX_CODES } from './core.js';

// Defers pageview tracking to a macrotask so it reads the post-navigation
// location instead of racing react-router's own update (App.tsx GoogleAnalytics).
export const PAGEVIEW_TRACK_DELAY_MS = 0;

// ─── Analytics ───────────────────────────────────────────────────────────────
// Matches `/events/:id` (bare or locale-prefixed, e.g. `/en/events/:id`) so
// Google Analytics groups all event detail views under one route instead of
// one row per event id — the locale prefix itself is captured (group 1) and
// kept by maskAnalyticsUrl's replacement, so en/et/ru still group separately.
// Applied to a pathname with query/hash already stripped (see
// maskAnalyticsUrl in utils.ts).
const _LOCALE_PREFIX_RE_SRC = `(/(?:${LOCALE_URL_PREFIX_CODES.join('|')}))?`;
export const ANALYTICS_EVENT_PATH_RE = new RegExp(`^${_LOCALE_PREFIX_RE_SRC}/events/\\d+$`);
// Groups every organizer edit-form URL under one analytics row, mirroring
// ANALYTICS_EVENT_PATH_RE above — same rationale, new dynamic route.
export const ANALYTICS_ORGANIZER_EDIT_PATH_RE = new RegExp(`^${_LOCALE_PREFIX_RE_SRC}/organizer/events/\\d+/edit$`);

// GA4 loader src — googletagmanager.com only, matching the CSP script-src
// widened for it (frontend/public/_headers, see docs/security.md).
export const GTAG_SCRIPT_SRC = 'https://www.googletagmanager.com/gtag/js';

// GA4 custom event names for the public-Explore + sign-in-upsell flow (issue
// #235). Event/param names are centralized here rather than inlined at call
// sites, per CLAUDE.md's frontend-constants Code Quality Rule.
export const ANALYTICS_EVENTS = {
  landingBrowseCtaClick: 'landing_browse_cta_click',
  landingEmailSubmit: 'landing_email_submit',
  exploreView: 'explore_view',
  exploreFilterChange: 'explore_filter_change',
  exploreCardClick: 'explore_card_click',
  exploreUpsellClick: 'explore_upsell_click',
  signinModalOpen: 'signin_modal_open',
  signinModalDismiss: 'signin_modal_dismiss',
  signinModalSubmit: 'signin_modal_submit',
} as const;
