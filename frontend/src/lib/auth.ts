import { TOKEN_KEY, LOCALES, LOCALE_KEY, LOGOUT_FLAG_TTL_MS } from '../constants';

// Auth-change subscriber store, so components can react to setToken()/clearToken()
// instead of only reading localStorage once at render time — see subscribeAuth().
const authListeners = new Set<() => void>();
function emitAuthChange(): void {
  authListeners.forEach((cb) => cb());
}
// Locale-change subscriber store, mirroring the auth store above, so globally
// mounted chrome (the Footer) re-renders when setLocale() runs on any page —
// locale lives in localStorage with no global React state otherwise.
const localeListeners = new Set<() => void>();
function emitLocaleChange(): void {
  localeListeners.forEach((cb) => cb());
}
// Cross-tab sign-out/sign-in + locale propagation: the storage event only fires
// in OTHER tabs (the tab that made the change never receives its own event).
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === TOKEN_KEY) emitAuthChange();
    if (e.key === LOCALE_KEY) emitLocaleChange();
  });
}
export function subscribeAuth(cb: () => void): () => void {
  authListeners.add(cb);
  return () => { authListeners.delete(cb); };
}
export function subscribeLocale(cb: () => void): () => void {
  localeListeners.add(cb);
  return () => { localeListeners.delete(cb); };
}

export function getToken(): string | null { return localStorage.getItem(TOKEN_KEY); }
export function setToken(t: string): void {
  loggingOut = false;
  localStorage.setItem(TOKEN_KEY, t);
  emitAuthChange();
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  emitAuthChange();
}
export function isAuthenticated(): boolean { return !!getToken(); }

// Set by an explicit logout action, before clearToken()/queryClient.clear() run.
// A logout on a route that doesn't change path (e.g. Feed at "/") doesn't
// unmount its active queries, so clearing the cache can trigger an in-place
// refetch with no auth token — the resulting 401 must not hard-redirect to
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
  const stored = localStorage.getItem(LOCALE_KEY);
  return LOCALES.some((l) => l.code === stored) ? stored! : LOCALES[0].code;
}
export function setLocale(l: string): void {
  localStorage.setItem(LOCALE_KEY, l);
  emitLocaleChange();
}
