// Client routes and the nav/menu item lists built from them.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

// ─── Routes ──────────────────────────────────────────────────────────────────
// Every <Route> path, `navigate()` target and `<Link to>` in App.tsx / the
// consumer + organizer nav chrome resolves through this map so the two stay
// in sync. Dynamic segments are builder functions; `*Pattern` entries are the
// React Router path (with `:param` placeholders) used only in App.tsx's
// <Route path> table.
export const ROUTES = {
  login: '/login',
  authVerify: '/auth/verify',
  onboarding: '/onboarding',
  home: '/',
  explore: '/explore',
  saved: '/saved',
  eventDetail: (id: number | string) => `/events/${id}`,
  eventDetailPattern: '/events/:id',
  settings: '/settings',
  unsubscribe: '/unsubscribe',
  privacy: '/privacy',
  terms: '/terms',
  contact: '/contact',
  faq: '/faq',
  organizerLogin: '/organizer/login',
  organizerVerify: '/organizer/verify',
  organizerClaimVerify: '/organizer/claims/verify',
  organizerClaims: '/organizer/claims',
  organizerDashboard: '/organizer/dashboard',
  organizerClaimPending: (id: number | string) => `/organizer/claims/${id}/pending`,
  organizerClaimPendingPattern: '/organizer/claims/:id/pending',
  organizerClaimEdit: (id: number | string) => `/organizer/claims/${id}/edit`,
  organizerClaimEditPattern: '/organizer/claims/:id/edit',
  organizerClaimEvents: (id: number | string) => `/organizer/claims/${id}/events`,
  organizerClaimEventsPattern: '/organizer/claims/:id/events',
  organizerSubmit: '/organizer/submit',
  organizerSettings: '/organizer/settings',
  organizerContact: '/organizer/contact',
  organizerEventEdit: (id: number | string) => `/organizer/events/${id}/edit`,
  organizerEventEditPattern: '/organizer/events/:id/edit',
  // Admin console (issue #154) — registered entirely outside App.tsx's
  // ROUTE_DEFS/locale-prefix loop (see AdminApp), so these are never
  // locale-prefixed and never appear in NAV_ITEMS.
  adminLogin: '/admin/login',
  adminBase: '/admin',
  adminSplat: '/admin/*',
  adminEventsSplat: '/admin/events/*',
  adminDashboard: '/admin',
  adminReports: '/admin/reports',
  adminSubmissions: '/admin/submissions',
  adminClaims: '/admin/claims',
  adminEventDetail: (id: number | string) => `/admin/events/${id}`,
  adminEventDetailPattern: '/admin/events/:id',
  // Path-prefix form of adminEventDetail, for AdminApp's manual pathname
  // dispatch (see that file's comment on why it can't use nested <Routes>).
  adminEventDetailPrefix: '/admin/events/',
  adminPipeline: '/admin/pipeline',
  adminDedup: '/admin/dedup',
} as const;

// The FAQ's Organizers section anchor (FaqSection.id 'organizers') —
// OrganizerContact deep-links to it as ROUTES.faq + this hash.
export const FAQ_ORGANIZERS_HASH = '#organizers';

// The admin console's persistent nav — the clickable screens (issue #154,
// Claims added #420); /admin/login and /admin/events/:id are reached by
// URL/click-through, not nav links. No i18n: the console is an internal
// operator tool, not user-facing product surface.
export const ADMIN_NAV_ITEMS = [
  { route: ROUTES.adminDashboard, label: 'Dashboard' },
  { route: ROUTES.adminReports, label: 'Reports' },
  { route: ROUTES.adminSubmissions, label: 'Submissions' },
  { route: ROUTES.adminClaims, label: 'Claims' },
  { route: ROUTES.adminPipeline, label: 'Pipeline' },
  { route: ROUTES.adminDedup, label: 'Dedup groups' },
] as const;

export interface NavItem {
  route: string;
  labelKey: string;
}

// The signed-in primary nav — same {route, labelKey} pairs rendered by both
// TopBar (desktop) and MobileMenu (mobile), kept in one place so they can't
// drift out of sync. Settings and Contact live in ACCOUNT_MENU_ITEMS.
export const NAV_ITEMS: readonly NavItem[] = [
  { route: ROUTES.home, labelKey: 'nav_daily5' },
  { route: ROUTES.explore, labelKey: 'nav_explore' },
  { route: ROUTES.saved, labelKey: 'nav_saved' },
];

// Settings and Contact moved out of the bar into the account menu (and the
// drawer's account block) — what makes the 1024px bar fit in ET/RU.
export const ACCOUNT_MENU_ITEMS: readonly NavItem[] = [
  { route: ROUTES.settings, labelKey: 'nav_settings' },
  { route: ROUTES.contact, labelKey: 'nav_contact' },
];

// The signed-out primary nav — an explicit list rather than a filter over
// NAV_ITEMS, since it carries FAQ, which the signed-in nav doesn't. Daily
// 5/Saved/Settings are left out as dead ends for an anonymous visitor.
// Shared by TopBar and MobileMenu so they can't drift out of sync.
export const SIGNED_OUT_NAV_ITEMS: readonly NavItem[] = [
  { route: ROUTES.explore, labelKey: 'nav_explore' },
  { route: ROUTES.faq, labelKey: 'nav_faq' },
  { route: ROUTES.contact, labelKey: 'nav_contact' },
];

// Same {route, labelKey} shape as NAV_ITEMS, rendered by both OrganizerTopBar
// (desktop) and its MobileMenu (mobile). "New event" is the bar's gold CTA and
// Settings/Contact live in ORGANIZER_ACCOUNT_MENU_ITEMS.
export const ORGANIZER_NAV_ITEMS: readonly NavItem[] = [
  { route: ROUTES.organizerDashboard, labelKey: 'organizer_dashboard_title' },
  { route: ROUTES.organizerClaims, labelKey: 'dashboard_claims_title' },
];

export const ORGANIZER_ACCOUNT_MENU_ITEMS: readonly NavItem[] = [
  { route: ROUTES.organizerSettings, labelKey: 'organizer_settings_nav' },
  { route: ROUTES.organizerContact, labelKey: 'organizer_contact_nav' },
];
