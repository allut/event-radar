// Auth tracks: signed-in hint storage keys, Google sign-in, and the auth UI state machines.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { UI_STATE } from './core.js';

// ─── Local storage keys ──────────────────────────────────────────────────────
// These hold a boolean "signed-in hint", not a credential — the real session
// token lives only in an httpOnly cookie, unreadable by page JS. The hint
// exists purely so isAuthenticated()/isAuthenticatedOrganizer() can answer
// synchronously at first paint. Key names are unchanged from the pre-cookie
// token-storage era so existing localStorage entries/cross-tab listeners
// keep working.
export const SIGNED_IN_HINT_KEY = 'session_token';

// Separate key from SIGNED_IN_HINT_KEY — organizer and consumer sessions are
// two independent auth tracks (own account table, own token salts on the
// backend) that must never be confused for one another. See lib/organizerAuth.ts.
export const ORGANIZER_SIGNED_IN_HINT_KEY = 'organizer_session_token';

// Resolved VITE_GOOGLE_SIGNIN_*_ENABLED build gates — one place so Login/
// OrganizerLogin can't drift on how the env string is parsed. Functions, not
// frozen booleans: each test file's vi.stubEnv() sets the var per-test, and
// a module-scope-evaluated constant would freeze the first test's value for
// the whole run (ES modules are cached singletons).
export function isGoogleSignInConsumerEnabled(): boolean {
  return import.meta.env.VITE_GOOGLE_SIGNIN_CONSUMER_ENABLED === 'true';
}
export function isGoogleSignInOrganizerEnabled(): boolean {
  return import.meta.env.VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED === 'true';
}
// Identity-provider slug returned by /users/me & /organizer/profile for a
// Google-linked account (vs. magic-link-only).
export const GOOGLE_IDENTITY_PROVIDER = 'google';

export const AUTH_TOKEN_PARAM = 'token';
// GoogleGMark's default render size (px) — the brand mark's own icon-only
// SVG viewBox scale, not a design-system --fs-* token (docs/adr/0002).
export const GOOGLE_G_MARK_SIZE = 20;

// ─── Auth / magic link ───────────────────────────────────────────────────────
export const AUTH_REDIRECT_DELAY_MS = 600;
// Upper bound on the post-logout 401-redirect suppression window (lib/auth.ts
// isLoggingOut) — comfortably covers the cache-clear race plus Settings'
// AUTH_REDIRECT_DELAY_MS-delayed logout-all flow, without masking a genuine
// session expiry indefinitely if the user never signs back in on this tab.
export const LOGOUT_FLAG_TTL_MS = 10_000;

export type LoginState = typeof UI_STATE.idle | typeof UI_STATE.loading | typeof UI_STATE.success | typeof UI_STATE.error;
export type VerifyState = typeof UI_STATE.verifying | typeof UI_STATE.success | typeof UI_STATE.error;
export type UnsubscribeState = typeof UI_STATE.working | typeof UI_STATE.success | typeof UI_STATE.resubscribed | typeof UI_STATE.error;

// AuthCard's three presentational kinds — shared by AuthVerify and
// OrganizerVerify, both magic-link verify flows that map the same
// three-state machine onto AuthCard's spinner/check/error rendering.
export type AuthCardKind = 'pending' | 'success' | 'error';
export const VERIFY_STATE_TO_KIND: Record<VerifyState, AuthCardKind> = {
  [UI_STATE.verifying]: 'pending',
  [UI_STATE.success]: 'success',
  [UI_STATE.error]: 'error',
};

// Admin console (routes/AdminLogin, components/AdminQueueActionPanel)
export const TOTP_CODE_LENGTH = 6;

// Parallel signed-in hint to SIGNED_IN_HINT_KEY/ORGANIZER_SIGNED_IN_HINT_KEY
// (see lib/adminAuth.ts) — a third, independent auth track's localStorage flag.
export const ADMIN_SIGNED_IN_HINT_KEY = 'admin_session_token';
