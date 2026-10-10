import { storageGet, storageSet, storageRemove } from './storage';
import {
  COLOR_SCHEME_DARK_QUERY,
  LEGACY_THEME_PREFERENCE_KEY,
  THEME_OVERRIDE_DEVICE_KEY,
  THEME_OVERRIDE_KEY,
  THEME_COLOR_META_DARK,
  THEME_COLOR_META_LIGHT,
} from '../constants';
import { THEME_PREFERENCES } from '../_generated/sharedConstants.js';

// What actually gets applied to the DOM / rendered — always binary, and
// always exactly one of the two (CONTEXT.md's "resolved theme"). Derived
// from THEME_PREFERENCES (shared/app-config.json) so this never drifts from
// the backend's two-value taxonomy.
export type ResolvedTheme = (typeof THEME_PREFERENCES)[number];

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

function systemPrefersDark(): boolean {
  return window.matchMedia(COLOR_SCHEME_DARK_QUERY).matches;
}

function currentDeviceTheme(): ResolvedTheme {
  return systemPrefersDark() ? 'dark' : 'light';
}

// Pure resolution function — no DOM/storage reads — so it's unit-testable
// against every combination directly (CONTEXT.md's "theme override"). An
// override only counts if it's a valid light/dark value AND was chosen
// under the device theme currently in effect — a mismatch (the device
// flipped since) means the override has expired and the device theme wins.
export function resolveTheme(
  overrideValue: string | null,
  overrideDevice: string | null,
  systemPrefersDarkFlag: boolean,
): ResolvedTheme {
  const device: ResolvedTheme = systemPrefersDarkFlag ? 'dark' : 'light';
  if (
    (overrideValue === 'light' || overrideValue === 'dark') &&
    overrideDevice === device
  ) {
    return overrideValue;
  }
  return device;
}

export function getResolvedTheme(): ResolvedTheme {
  return resolveTheme(
    storageGet(THEME_OVERRIDE_KEY),
    storageGet(THEME_OVERRIDE_DEVICE_KEY),
    systemPrefersDark(),
  );
}

// Mirrors --bg's dark (#13161e) and light (#fdfcfa) values (src/index.css) —
// duplicated here the same way index.html's pre-paint script duplicates
// resolveTheme(): must never disagree with those tokens. Replaces
// index.html's two prefers-color-scheme-media <meta name="theme-color">
// tags with a single tag pinned to the resolved theme, same technique the
// pre-paint script uses on first load — this keeps it in sync on every
// runtime theme change too (setThemeOverride), not just page load.
function syncThemeColorMeta(theme: ResolvedTheme): void {
  document.querySelectorAll('meta[name="theme-color"][media]').forEach((el) => el.remove());
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]:not([media])');
  if (!meta) {
    meta = document.createElement('meta');
    meta.name = 'theme-color';
    document.head.appendChild(meta);
  }
  meta.content = theme === 'light' ? THEME_COLOR_META_LIGHT : THEME_COLOR_META_DARK;
}

// Discards an override whose recorded device theme no longer matches the
// current one — the "load-time mismatch" expiry path (ADR 0003), as
// opposed to the live matchMedia-flip path below. Also wipes the legacy
// tri-state key unconditionally: it was never chosen under a recorded
// device theme, so there's nothing to reinterpret — every existing visitor
// starts again at device-following.
function clearStaleOverride(): void {
  storageRemove(LEGACY_THEME_PREFERENCE_KEY);
  if (storageGet(THEME_OVERRIDE_DEVICE_KEY) !== currentDeviceTheme()) {
    storageRemove(THEME_OVERRIDE_KEY);
    storageRemove(THEME_OVERRIDE_DEVICE_KEY);
  }
}

// Re-resolves from current localStorage/system state and applies it to the
// DOM, clearing a stale override first.
export function applyTheme(): void {
  clearStaleOverride();
  const resolved = getResolvedTheme();
  document.documentElement.dataset.theme = resolved;
  syncThemeColorMeta(resolved);
}

// A viewer's explicit choice — scoped to this browser only, never an
// account (ADR 0003). Records the device theme it was made under, so a
// later flip expires it.
export function setThemeOverride(value: ResolvedTheme): void {
  storageSet(THEME_OVERRIDE_KEY, value);
  storageSet(THEME_OVERRIDE_DEVICE_KEY, currentDeviceTheme());
  applyTheme();
  emitThemeChange();
}

if (typeof window !== 'undefined') {
  // Re-applies in other open tabs when the override changes in one tab —
  // the storage event only fires in tabs other than the one that made the
  // change, same as auth.ts's SIGNED_IN_HINT_KEY/LOCALE_KEY listeners.
  window.addEventListener('storage', (e) => {
    if (e.key === THEME_OVERRIDE_KEY || e.key === THEME_OVERRIDE_DEVICE_KEY) {
      applyTheme();
      emitThemeChange();
    }
  });
  // Live-reacts to an OS theme flip while a tab is open — unconditionally
  // discards any override (there's no "system" mode left to guard this
  // with) and re-resolves to the new device theme.
  window.matchMedia(COLOR_SCHEME_DARK_QUERY).addEventListener('change', () => {
    applyTheme();
    emitThemeChange();
  });
}
