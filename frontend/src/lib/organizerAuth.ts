import { ORGANIZER_TOKEN_KEY, LOGOUT_FLAG_TTL_MS } from '../constants';

// Parallel session store to lib/auth.ts's consumer track — separate listener
// set, separate storage key, separate logout flag. Two independent auth
// tracks that must never be confused for one another (see constants.ts).
const organizerAuthListeners = new Set<() => void>();
function emitOrganizerAuthChange(): void {
  organizerAuthListeners.forEach((cb) => cb());
}
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === ORGANIZER_TOKEN_KEY) emitOrganizerAuthChange();
  });
}
export function subscribeOrganizerAuth(cb: () => void): () => void {
  organizerAuthListeners.add(cb);
  return () => { organizerAuthListeners.delete(cb); };
}

export function getOrganizerToken(): string | null { return localStorage.getItem(ORGANIZER_TOKEN_KEY); }
export function setOrganizerToken(t: string): void {
  organizerLoggingOut = false;
  localStorage.setItem(ORGANIZER_TOKEN_KEY, t);
  emitOrganizerAuthChange();
}
export function clearOrganizerToken(): void {
  localStorage.removeItem(ORGANIZER_TOKEN_KEY);
  emitOrganizerAuthChange();
}
export function isAuthenticatedOrganizer(): boolean { return !!getOrganizerToken(); }

// Mirrors lib/auth.ts's loggingOut flag — see that file for the full
// rationale (cache-clear race on a same-path logout must not trigger a
// hard-redirect that clobbers the intended post-logout navigation).
let organizerLoggingOut = false;
export function beginOrganizerLogout(): void {
  organizerLoggingOut = true;
  setTimeout(() => { organizerLoggingOut = false; }, LOGOUT_FLAG_TTL_MS);
}
export function isOrganizerLoggingOut(): boolean { return organizerLoggingOut; }
