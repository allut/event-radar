import { THEME_PREFERENCE_KEY } from '../constants';

// Tri-state stored/selectable preference. "system" (or an unset/invalid
// localStorage value) falls through to the OS media query.
export type ThemePreference = 'system' | 'light' | 'dark';
// What actually gets applied to the DOM / rendered — always binary.
export type ResolvedTheme = 'light' | 'dark';

// Theme-change subscriber store, mirroring auth.ts's authListeners/localeListeners
// — lets globally mounted chrome re-render when the effective theme changes from
// a source other than its own state (a matchMedia flip, another tab's write).
const themeListeners = new Set<() => void>();
function emitThemeChange(): void {
  themeListeners.forEach((cb) => cb());
}
export function subscribeTheme(cb: () => void): () => void {
  themeListeners.add(cb);
  return () => { themeListeners.delete(cb); };
}

// Pure resolution function — no DOM/storage reads — so it's unit-testable
// against every combination in the resolution order directly. accountPreference
// is unused by the rest of this module today (nothing supplies a non-null value
// until account sync lands in a later ticket) but is part of the seam now so
// callers don't need to change shape when it does.
export function resolveTheme(
  accountPreference: ResolvedTheme | null,
  localStorageValue: string | null,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (accountPreference === 'light' || accountPreference === 'dark') return accountPreference;
  if (localStorageValue === 'light' || localStorageValue === 'dark') return localStorageValue;
  return systemPrefersDark ? 'dark' : 'light';
}

function systemPrefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

// Raw stored preference, defaulting to "system" when unset/invalid — unlike a
// getStoredLocale()-style raw accessor, there's no "no preference yet" case to
// preserve here yet, since nothing downstream (account sync) consumes it in
// this ticket.
export function getThemePreference(): ThemePreference {
  const stored = localStorage.getItem(THEME_PREFERENCE_KEY);
  return stored === 'light' || stored === 'dark' ? stored : 'system';
}

// Re-resolves from current localStorage/system state and applies it to the DOM.
// No account-preference input yet — see resolveTheme's accountPreference note.
export function applyTheme(): void {
  const resolved = resolveTheme(null, localStorage.getItem(THEME_PREFERENCE_KEY), systemPrefersDark());
  document.documentElement.dataset.theme = resolved;
}

export function setThemePreference(pref: ThemePreference): void {
  localStorage.setItem(THEME_PREFERENCE_KEY, pref);
  applyTheme();
  emitThemeChange();
}

// Shared post-verify sync policy for both auth tracks (#253 consumer,
// #254 organizer): an existing account preference wins and is mirrored
// locally; otherwise an explicit local override (set before sign-in) seeds
// the account via patchAccountTheme. Each call site supplies its own
// track-specific PATCH so the tracks' state stays independent (CONTEXT.md).
export function syncAccountTheme(
  accountTheme: ResolvedTheme | null,
  patchAccountTheme: (theme: ResolvedTheme) => Promise<unknown>,
): void {
  if (accountTheme === 'light' || accountTheme === 'dark') {
    setThemePreference(accountTheme);
    return;
  }
  const local = getThemePreference();
  if (local === 'light' || local === 'dark') {
    void patchAccountTheme(local).catch(() => {
      // Non-fatal — account sync isn't required for sign-in to succeed.
    });
  }
}

if (typeof window !== 'undefined') {
  // Re-applies in other open tabs when theme_preference changes in one tab —
  // the storage event only fires in tabs other than the one that made the
  // change, same as auth.ts's SIGNED_IN_HINT_KEY/LOCALE_KEY listeners.
  window.addEventListener('storage', (e) => {
    if (e.key === THEME_PREFERENCE_KEY) {
      applyTheme();
      emitThemeChange();
    }
  });
  // Live-reacts to an OS theme flip while a tab is open, but only while the
  // effective preference is "System" — an explicit light/dark override must
  // not be disturbed by the OS changing underneath it.
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (getThemePreference() === 'system') {
      applyTheme();
      emitThemeChange();
    }
  });
}
