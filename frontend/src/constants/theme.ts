// Theme: theme options, color-scheme media queries, theme-color meta, category gradients.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

// Legacy tri-state theme key ("system" | "light" | "dark") from the
// permanent-preference model this app replaced — wiped on every
// boot (lib/theme.ts) rather than reinterpreted, since its "system" value
// has no equivalent under the new expiring-override semantics.
export const LEGACY_THEME_PREFERENCE_KEY = 'theme_preference';
// Device-theme-following override, shared across consumer/organizer/admin
// (one SPA bundle, one light palette) — see lib/theme.ts's resolveTheme().
// Holds "light" | "dark" only; paired with THEME_OVERRIDE_DEVICE_KEY, which
// records the device theme the override was chosen under, so a later device
// flip can be detected and the override discarded.
export const THEME_OVERRIDE_KEY = 'theme_override';
export const THEME_OVERRIDE_DEVICE_KEY = 'theme_override_device';

// Keys must match the 14-category taxonomy in shared/app-config.json
// (VALID_CATEGORIES). Values reference --gradient-<slug> tokens in
// index.css's :root — the hex values live there, not here.
export const CATEGORY_GRADIENTS: Record<string, string> = {
  nightlife:    'var(--gradient-nightlife)',
  music:        'var(--gradient-music)',
  theater:      'var(--gradient-theater)',
  exhibitions:  'var(--gradient-exhibitions)',
  workshops:    'var(--gradient-workshops)',
  food_drink:   'var(--gradient-food_drink)',
  sports:       'var(--gradient-sports)',
  networking:   'var(--gradient-networking)',
  literature:   'var(--gradient-literature)',
  family:       'var(--gradient-family)',
  cinema:       'var(--gradient-cinema)',
  alternative:  'var(--gradient-alternative)',
  comedy:       'var(--gradient-comedy)',
  romantic:     'var(--gradient-romantic)',
};
export const FALLBACK_GRADIENT = 'var(--gradient-fallback)';

// ClaimEventPicker's event search: minimum trimmed query length before the
// search request fires, and its debounce (same cadence as Explore's search).
// <meta name="theme-color"> values per resolved theme — mirror --bg in
// index.css and the pre-paint script in index.html (the three must agree).
export const THEME_COLOR_META_LIGHT = '#fdfcfa';
export const THEME_COLOR_META_DARK = '#13161e';

// The two theme options rendered by PrefsRows (the preferences menu and the
// phone drawer), kept in one place so they can't drift out of sync —
// mirrors NAV_ITEMS' {value, labelKey} pattern (routes.ts). No "System" entry:
// device-following is the default state a viewer falls back to
// once their override expires, not something offered as a third choice.
export const THEME_OPTIONS = [
  { value: 'light', labelKey: 'theme_light' },
  { value: 'dark', labelKey: 'theme_dark' },
] as const;

// usePrefersReducedMotion's matchMedia query.
export const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
// theme.ts's OS-preference matchMedia query (the "system" fallback of the
// account → localStorage → OS resolution order).
export const COLOR_SCHEME_DARK_QUERY = '(prefers-color-scheme: dark)';
