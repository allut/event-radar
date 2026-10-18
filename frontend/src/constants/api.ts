// API client: base URLs, endpoint builders, React Query keys and tuning, shared error codes, pagination params.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

// ─── React Query ─────────────────────────────────────────────────────────────
export const QUERY_RETRY = 1;
export const QUERY_STALE_TIME = 30_000;

// Frontend-only marker (no backend counterpart) client.ts assigns to
// ApiError.code for a FastAPI 422 list `detail` — lets a caller tell "the
// backend rejected a field" apart from every other error shape (#452).
export const VALIDATION_ERROR_CODE = 'validation_error';

// Frontend-only marker (no backend counterpart), mirroring
// VALIDATION_ERROR_CODE above — client.ts assigns this to ApiError.code when
// `fetch` itself rejects (network error, or the request never left the
// browser at all — e.g. blocked by an ad/tracker blocker, #453) rather than
// the server returning any response. Lets a caller show a distinguishable
// "couldn't reach Event Radar" message instead of the generic fallback.
export const NETWORK_ERROR_CODE = 'network_error';

// HTTP status the claim-editing surface reads structurally (not-granted / dormant).
export const HTTP_STATUS_CONFLICT = 409;

// ─── React Query keys ──────────────────────────────────────────────────────────
// Query-key root strings shared across routes and useFeedback's invalidation
// fan-out — a typo in one spot would silently break refresh, so it's centralized.
export const QUERY_KEYS = {
  feed: 'feed',
  explore: 'explore',
  saved: 'saved',
  event: 'event',
  settings: 'settings',
  showcase: 'showcase',
  counts: 'counts',
  authMe: 'authMe',
  organizerEvents: 'organizerEvents',
  organizerProfile: 'organizerProfile',
  organizerVenues: 'organizerVenues',
  organizerClaimSuggestions: 'organizerClaimSuggestions',
  organizerClaimSearch: 'organizerClaimSearch',
  organizerClaims: 'organizerClaims',
  organizerClaim: 'organizerClaim',
  organizerClaimEvent: 'organizerClaimEvent',
  organizerClaimEvents: 'organizerClaimEvents',
  organizerClaimForEvent: 'organizerClaimForEvent',
  organizerPromotions: 'organizerPromotions',
  organizerPromotionContext: 'organizerPromotionContext',
  organizerPromotionValidate: 'organizerPromotionValidate',
  organizerPromotionRegistry: 'organizerPromotionRegistry',
  organizerPromotionReport: 'organizerPromotionReport',
  organizerPromotionEvent: 'organizerPromotionEvent',
  adminCounts: 'adminCounts',
  adminReports: 'adminReports',
  adminSubmissions: 'adminSubmissions',
  adminClaims: 'adminClaims',
  adminDedupGroups: 'adminDedupGroups',
  adminEventDetail: 'adminEventDetail',
  adminPromotions: 'adminPromotions',
  adminPromotionCapStrip: 'adminPromotionCapStrip',
  adminPromotionDetail: 'adminPromotionDetail',
  adminPromotionDailyStats: 'adminPromotionDailyStats',
  adminPromotionContext: 'adminPromotionContext',
  adminPromotionValidate: 'adminPromotionValidate',
  adminPromotionRequests: 'adminPromotionRequests',
  adminPromotionTrust: 'adminPromotionTrust',
  adminPromotionWithdrawable: 'adminPromotionWithdrawable',
} as const;

// Pagination query-param names shared by every paginated list fetch
// (Saved Events, admin queues, organizer dashboard) — /explore routes its
// own copies through EXPLORE_PARAM (explore.ts).
export const PAGE_PARAM = {
  limit: 'limit',
  offset: 'offset',
} as const;

// The frontend URL's 1-based page number (spec #551), read by usePageParam and
// written by <Pager>'s links. Page 1 omits it. Never sent to the backend,
// which only ever sees PAGE_PARAM.limit/offset.
export const PAGE_QUERY_PARAM = 'page';

// Router location-state key every <Pager> link carries. usePagedQuery only
// treats a push with it (or a POP) as a page change that scrolls, focuses and
// announces; anything else that lands on another page (a setListParams
// filter/sort/search/tab push, a nav link, a preset chip) is silent.
export const PAGER_NAV_STATE = 'pagerPageChange';

// i18n keys for <Pager>'s live-region announcement, one per item noun: the
// Explore-style lists announce "Events", lists of anything else "Items".
export const PAGER_LIVE_KEY = {
  events: 'pager_live_events',
  items: 'pager_live_items',
} as const;
export type PagerLiveNoun = keyof typeof PAGER_LIVE_KEY;

// Prefix every backend request is proxied under (see
// functions/api/[[path]].ts's catch-all proxy, keyed on this same string) —
// api/client.ts's fetch wrapper and NDJSON stream path both prepend it.
export const API_BASE = '/api';

// Render Frankfurt backend origin (issue #342) the `/api/*` proxy
// (functions/api/[[path]].ts, a Cloudflare Pages Function) forwards to. Not
// the same value as vite.config.ts's PRERENDER_BACKEND_TARGET (a Node-only build-time constant
// scripts/prerender.ts and the dev proxy use — that file can't import from
// here, and a real dry run needs to override it independently via
// PRERENDER_API_ORIGIN), but both currently point at the same backend.
export const BACKEND_ORIGIN = 'https://event-radar-api-r7l6.onrender.com';

// ─── API endpoints ───────────────────────────────────────────────────────────
// Every backend request path resolves through this map (or a builder function
// for a dynamic segment) so a typo can't silently desync a call site from the
// route it's meant to hit.
export const API = {
  me: '/users/me',
  authMe: '/auth/me',
  authVerify: '/auth/verify',
  authLogout: '/auth/logout',
  authLogoutAll: '/auth/logout-all',
  authRequestLink: '/auth/request-link',
  authGoogleStart: '/auth/google/start',
  meIdentity: (provider: string) => `/users/me/identities/${provider}`,
  organizerAuthLogout: '/organizer/auth/logout',
  organizerAuthLogoutAll: '/organizer/auth/logout-all',
  organizerAuthVerify: '/organizer/auth/verify',
  organizerAuthRequestLink: '/organizer/auth/request-link',
  organizerAuthGoogleStart: '/organizer/auth/google/start',
  organizerProfileIdentity: (provider: string) => `/organizer/profile/identities/${provider}`,
  onboardingPersona: '/onboarding/persona',
  contact: '/contact',
  feed: '/feed',
  feedback: '/feedback',
  feedbackEvent: (id: number) => `/feedback/${id}`,
  feedbackEvents: '/feedback/events',
  explore: '/explore',
  publicShowcase: '/public/showcase',
  publicCounts: '/public/counts',
  emailUnsubscribe: '/email/unsubscribe',
  emailResubscribe: '/email/resubscribe',
  emailConsentOff: '/email/ads-off',
  emailConsentOn: '/email/ads-on',
  event: (id: number | string) => `/events/${encodeURIComponent(String(id))}`,
  organizerEvents: '/organizer/events',
  organizerEvent: (id: number | string) => `/organizer/events/${encodeURIComponent(String(id))}`,
  organizerEventImage: '/organizer/events/image',
  organizerProfile: '/organizer/profile',
  organizerContact: '/organizer/contact',
  organizerVenues: '/organizer/venues',
  organizerVenue: (id: number | string) => `/organizer/venues/${encodeURIComponent(String(id))}`,
  organizerClaims: '/organizer/claims',
  organizerClaim: (id: number | string) => `/organizer/claims/${encodeURIComponent(String(id))}`,
  organizerClaimCancel: (id: number | string) => `/organizer/claims/${encodeURIComponent(String(id))}/cancel`,
  organizerClaimRecheck: (id: number | string) => `/organizer/claims/${encodeURIComponent(String(id))}/recheck`,
  organizerClaimLinkRequest: '/organizer/claims/request-link',
  organizerClaimLinkVerify: '/organizer/claims/verify-link',
  organizerClaimSearch: '/organizer/claims/search',
  organizerClaimSuggestions: '/organizer/claims/suggestions',
  // Path-based, not a query string (#453) — `...?event_id=...` reads as an
  // analytics-beacon URL shape and gets silently dropped by ad/tracker
  // blockers (ERR_BLOCKED_BY_CLIENT).
  organizerClaimEvent: (id: number | string, eventId?: number) =>
    eventId !== undefined
      ? `/organizer/claims/${id}/events/${eventId}`
      : `/organizer/claims/${id}/event`,
  organizerClaimEvents: (id: number | string) => `/organizer/claims/${encodeURIComponent(String(id))}/events`,
  organizerClaimForEvent: (eventId: number | string) => `/organizer/claims/for-event/${encodeURIComponent(String(eventId))}`,
  organizerPromotions: '/organizer/promotions',
  organizerPromotionContext: '/organizer/promotions/context',
  organizerPromotionValidate: '/organizer/promotions/validate',
  organizerPromotionRequests: '/organizer/promotions/requests',
  organizerPromotionWithdraw: (id: number | string) =>
    `/organizer/promotions/requests/${encodeURIComponent(String(id))}/withdraw`,
  organizerPromotionReport: (id: number | string) => `/organizer/promotions/${encodeURIComponent(String(id))}/report`,
  organizerPromotionRegistryLookup: '/organizer/promotions/registry-lookup',
  organizerPromotionCheckout: '/organizer/promotions/checkout',
  reports: '/reports',
  adminAuthLogin: '/admin/auth/login',
  adminAuthLogout: '/admin/auth/logout',
  adminAuthMe: '/admin/auth/me',
  adminCounts: '/admin/counts',
  adminReports: '/admin/reports',
  adminReportResolve: (id: number) => `/admin/reports/${id}/resolve`,
  adminReportTakedown: (id: number) => `/admin/reports/${id}/takedown`,
  adminSubmissions: '/admin/submissions',
  adminDedupGroups: '/admin/dedup/groups',
  adminSubmissionApprove: (id: number) => `/admin/submissions/${id}/approve`,
  adminSubmissionRetract: (id: number) => `/admin/submissions/${id}/retract`,
  adminClaims: '/admin/claims',
  adminClaimGrant: (id: number) => `/admin/claims/${id}/grant`,
  adminClaimDecline: (id: number) => `/admin/claims/${id}/decline`,
  adminClaimRevoke: (id: number) => `/admin/claims/${id}/revoke`,
  adminEventDetail: (id: number | string) => `/admin/events/${encodeURIComponent(String(id))}`,
  adminPromotions: '/admin/promotions',
  adminPromotionCapStrip: '/admin/promotions/cap-strip',
  adminPromotionDetail: (id: number | string) => `/admin/promotions/${id}`,
  adminPromotionMarkPaid: (id: number | string) => `/admin/promotions/${id}/mark-paid`,
  adminPromotionRepoint: (id: number | string) => `/admin/promotions/${id}/repoint`,
  adminPromotionEnd: (id: number | string) => `/admin/promotions/${id}/end`,
  adminPromotionVoid: (id: number | string) => `/admin/promotions/${id}/void`,
  adminPromotionRefund: (id: number | string) => `/admin/promotions/${id}/refund`,
  adminPromotionDailyStats: (id: number | string) => `/admin/promotions/${id}/daily-stats`,
  adminPromotionContext: (eventId: number | string) => `/admin/events/${eventId}/promotion-context`,
  adminPromotionValidate: (eventId: number | string) => `/admin/events/${eventId}/promotions/validate`,
  adminPromotionGrant: (eventId: number | string) => `/admin/events/${eventId}/promotions`,
  adminPromotionRequests: '/admin/promotion-requests',
  adminPromotionRequestGrant: (id: number) => `/admin/promotion-requests/${id}/grant`,
  adminPromotionRequestDecline: (id: number) => `/admin/promotion-requests/${id}/decline`,
  adminPromotionTrust: '/admin/promotions/trust',
  adminPromotionComplaints: '/admin/promotions/complaints',
  adminPromotionWithdraw: (id: number | string) => `/admin/promotions/${id}/withdraw`,
  adminPromotionWithdrawAll: '/admin/promotions/withdraw-all',
  adminIngestAll: '/admin/ingest',
  adminIngestSource: (slug: string) => `/admin/ingest/${slug}`,
  adminDedupRun: '/admin/dedup',
  adminClassify: '/admin/classify',
  adminPublish: '/admin/publish',
  adminGeocode: '/admin/geocode',
  adminRefetch: '/admin/refetch',
  adminSyncOrganizers: '/admin/sync-organizers',
  adminCleanup: (dryRun: boolean) => `/admin/cleanup?dry_run=${dryRun}`,
  adminBuildFeeds: '/admin/build-feeds',
  adminSendDigests: (dryRun: boolean) => `/admin/send-digests?dry_run=${dryRun}`,
  adminPipelineRun: (dryRun: boolean) => `/admin/pipeline/run?dry_run=${dryRun}`,
} as const;
