import { storageGet, storageSet, storageRemove } from './storage';
import { ORGANIZER_SIGNED_IN_HINT_KEY, LOGOUT_FLAG_TTL_MS } from '../constants/auth';

// Parallel session store to lib/auth.ts's consumer track — separate listener
// set, separate storage key, separate logout flag. Two independent auth
// tracks that must never be confused for one another (see constants/auth.ts).
const organizerAuthListeners = new Set<() => void>();
function emitOrganizerAuthChange(): void {
  organizerAuthListeners.forEach((cb) => cb());
}
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === ORGANIZER_SIGNED_IN_HINT_KEY) emitOrganizerAuthChange();
  });
}
export function subscribeOrganizerAuth(cb: () => void): () => void {
  organizerAuthListeners.add(cb);
  return () => { organizerAuthListeners.delete(cb); };
}

// The hint carries no credential value and grants no access — the real
// organizer session token lives only in an httpOnly cookie. It exists purely
// so isAuthenticatedOrganizer() can answer synchronously at first paint.
export function setOrganizerSignedInHint(): void {
  organizerLoggingOut = false;
  storageSet(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
  emitOrganizerAuthChange();
}
export function clearOrganizerSignedInHint(): void {
  storageRemove(ORGANIZER_SIGNED_IN_HINT_KEY);
  emitOrganizerAuthChange();
}
export function isAuthenticatedOrganizer(): boolean { return storageGet(ORGANIZER_SIGNED_IN_HINT_KEY) !== null; }

// Mirrors lib/auth.ts's loggingOut flag — see that file for the full
// rationale (cache-clear race on a same-path logout must not trigger a
// hard-redirect that clobbers the intended post-logout navigation).
let organizerLoggingOut = false;
export function beginOrganizerLogout(): void {
  organizerLoggingOut = true;
  setTimeout(() => { organizerLoggingOut = false; }, LOGOUT_FLAG_TTL_MS);
}
export function isOrganizerLoggingOut(): boolean { return organizerLoggingOut; }
