import { storageGet, storageSet, storageRemove } from './storage';
import { LOCALES } from '../_generated/sharedConstants';
import { SIGNED_IN_HINT_KEY, LOGOUT_FLAG_TTL_MS } from '../constants/auth';
import { LOCALE_EN, LOCALE_KEY } from '../constants/core';

// Auth-change subscriber store, so components can react to setSignedInHint()/
// clearSignedInHint() instead of only reading localStorage once at render
// time — see subscribeAuth().
const authListeners = new Set<() => void>();
function emitAuthChange(): void {
  authListeners.forEach((cb) => cb());
}
// Cross-tab sign-out/sign-in propagation: the storage event only fires in
// OTHER tabs (the tab that made the change never receives its own event).
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === SIGNED_IN_HINT_KEY) emitAuthChange();
  });
}
export function subscribeAuth(cb: () => void): () => void {
  authListeners.add(cb);
  return () => { authListeners.delete(cb); };
}

// The hint carries no credential value and grants no access — the real
// session token lives only in an httpOnly cookie. It exists purely so
// isAuthenticated() can answer synchronously at first paint.
export function setSignedInHint(): void {
  loggingOut = false;
  storageSet(SIGNED_IN_HINT_KEY, '1');
  emitAuthChange();
}
export function clearSignedInHint(): void {
  storageRemove(SIGNED_IN_HINT_KEY);
  emitAuthChange();
}
export function isAuthenticated(): boolean { return storageGet(SIGNED_IN_HINT_KEY) !== null; }

// Set by an explicit logout action, before clearSignedInHint()/queryClient.clear()
// run. A logout on a route that doesn't change path (e.g. Feed at "/") doesn't
// unmount its active queries, so clearing the cache can trigger an in-place
// refetch with no auth cookie — the resulting 401 must not hard-redirect to
// /login and clobber the intended post-logout navigation (see api/client.ts).
// Reset on the next successful sign-in so a genuine session expiry later
// still redirects normally, and auto-expires after LOGOUT_FLAG_TTL_MS so it
// can't mask a real session expiry indefinitely if the user never signs
// back in on this tab.
let loggingOut = false;
export function beginLogout(): void {
  loggingOut = true;
  setTimeout(() => { loggingOut = false; }, LOGOUT_FLAG_TTL_MS);
}
export function isLoggingOut(): boolean { return loggingOut; }

export function getLocale(): string {
  const stored = storageGet(LOCALE_KEY);
  return LOCALES.some((l) => l.code === stored) ? stored! : LOCALE_EN;
}
// Raw stored locale preference, or null if never explicitly set — unlike
// getLocale(), this doesn't fall back to LOCALE_EN. The locale-routing
// wrapper (App.tsx) needs to tell "no preference yet" apart from "explicitly
// en", since only an explicit non-Estonian preference should redirect a bare
// URL — a first-time visitor with no preference must land on Estonian.
export function getStoredLocale(): string | null {
  const stored = storageGet(LOCALE_KEY);
  return LOCALES.some((l) => l.code === stored) ? stored : null;
}
export function setLocale(l: string): void {
  storageSet(LOCALE_KEY, l);
}
// Restores the "no explicit preference" state getStoredLocale()/BareLocaleGate
// depend on — used to roll back an optimistic locale switch that was never
// actually stored (e.g. a failed PATCH with no prior preference), since
// writing 'et' there would fabricate a preference that was never made.
export function clearLocale(): void {
  storageRemove(LOCALE_KEY);
}
