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
  adminCounts: 'adminCounts',
  adminReports: 'adminReports',
  adminSubmissions: 'adminSubmissions',
  adminClaims: 'adminClaims',
  adminDedupGroups: 'adminDedupGroups',
  adminEventDetail: 'adminEventDetail',
} as const;

// Pagination query-param names shared by every paginated list fetch
// (Saved Events, admin queues, organizer dashboard) — /explore routes its
// own copies through EXPLORE_PARAM (explore.ts).
export const PAGE_PARAM = {
  limit: 'limit',
  offset: 'offset',
  cursor: 'cursor',
} as const;

// The frontend URL's 1-based page number (spec #551), read by usePageParam and
// written by <Pager>'s links. Page 1 omits it. Never sent to the backend,
// which only ever sees PAGE_PARAM.limit/offset.
export const PAGE_QUERY_PARAM = 'page';

// Router location-state key usePageParam's setListParams writes, so
// usePagedQuery can tell a filter/sort/search/tab push (which resets to
// page 1 silently) from a pager-link push (a real page change).
export const LIST_PARAMS_NAV_STATE = 'listParamsChange';

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
