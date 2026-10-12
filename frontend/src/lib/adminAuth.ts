import { storageGet, storageSet, storageRemove } from './storage';
import { ADMIN_SIGNED_IN_HINT_KEY, LOGOUT_FLAG_TTL_MS } from '../constants/auth';

// Parallel session store to lib/auth.ts and lib/organizerAuth.ts — a third,
// independent auth track (own listener set, own storage key, own logout
// flag) that must never be confused with the other two (see constants/auth.ts).
const adminAuthListeners = new Set<() => void>();
function emitAdminAuthChange(): void {
  adminAuthListeners.forEach((cb) => cb());
}
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === ADMIN_SIGNED_IN_HINT_KEY) emitAdminAuthChange();
  });
}
export function subscribeAdminAuth(cb: () => void): () => void {
  adminAuthListeners.add(cb);
  return () => { adminAuthListeners.delete(cb); };
}

// The hint carries no credential value and grants no access — the real admin
// session token lives only in an httpOnly cookie. It exists purely so
// isAuthenticatedAdmin() can answer synchronously at first paint.
export function setAdminSignedInHint(): void {
  adminLoggingOut = false;
  storageSet(ADMIN_SIGNED_IN_HINT_KEY, '1');
  emitAdminAuthChange();
}
export function clearAdminSignedInHint(): void {
  storageRemove(ADMIN_SIGNED_IN_HINT_KEY);
  emitAdminAuthChange();
}
export function isAuthenticatedAdmin(): boolean { return storageGet(ADMIN_SIGNED_IN_HINT_KEY) !== null; }

// Mirrors lib/auth.ts's loggingOut flag — see that file for the full
// rationale (cache-clear race on a same-path logout must not trigger a
// hard-redirect that clobbers the intended post-logout navigation).
let adminLoggingOut = false;
export function beginAdminLogout(): void {
  adminLoggingOut = true;
  setTimeout(() => { adminLoggingOut = false; }, LOGOUT_FLAG_TTL_MS);
}
export function isAdminLoggingOut(): boolean { return adminLoggingOut; }
