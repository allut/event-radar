import { describe, it, expect, vi } from 'vitest';
import { resolveTheme, getResolvedTheme, setThemeOverride, applyTheme } from './theme';

// theme.ts registers its matchMedia('change') listener once, at module
// import time — captured here, at this file's own module-eval time, before
// the global afterEach's vi.clearAllMocks() (test/setup.ts) wipes the
// recorded call off the mock.
const registeredChangeHandler = (() => {
  const results = vi.mocked(window.matchMedia).mock.results;
  const addEventListenerMock = vi.mocked(results[0].value.addEventListener);
  const call = addEventListenerMock.mock.calls.find(
    (args: unknown[]) => args[0] === 'change',
  );
  if (!call) throw new Error('theme.ts never registered a matchMedia change listener');
  return call[1] as () => void;
})();

describe('resolveTheme', () => {
  it('a light override chosen under the current (light) device theme wins', () => {
    expect(resolveTheme('light', 'light', false)).toBe('light');
  });

  it('a dark override chosen under the current (dark) device theme wins', () => {
    expect(resolveTheme('dark', 'dark', true)).toBe('dark');
  });

  it('an override chosen under a device theme that no longer matches expires — device wins', () => {
    // Override "light" was chosen while the device was dark; device is now light.
    expect(resolveTheme('light', 'dark', false)).toBe('light');
    // Override "dark" was chosen while the device was light; device is now dark.
    expect(resolveTheme('dark', 'light', true)).toBe('dark');
  });

  it('no override falls through to the device theme (dark)', () => {
    expect(resolveTheme(null, null, true)).toBe('dark');
  });

  it('no override falls through to the device theme (light)', () => {
    expect(resolveTheme(null, null, false)).toBe('light');
  });

  it('a garbage override value falls through to the device theme', () => {
    expect(resolveTheme('blue', 'light', false)).toBe('light');
  });

  it('an override with no recorded device (garbage/missing pairing) falls through', () => {
    expect(resolveTheme('light', null, false)).toBe('light');
    expect(resolveTheme('light', null, true)).toBe('dark');
  });
});

describe('getResolvedTheme / setThemeOverride / applyTheme', () => {
  it('setThemeOverride persists the override plus the device it was chosen under, and applies data-theme', () => {
    setThemeOverride('light');
    expect(localStorage.getItem('theme_override')).toBe('light');
    expect(localStorage.getItem('theme_override_device')).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(getResolvedTheme()).toBe('light');

    setThemeOverride('dark');
    expect(localStorage.getItem('theme_override')).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('applyTheme discards an override whose recorded device no longer matches (load-time mismatch)', () => {
    setThemeOverride('dark');
    // Device is mocked light; recording an override under a stale "dark" device
    // simulates the device having flipped since the override was made.
    localStorage.setItem('theme_override_device', 'dark');
    applyTheme();
    expect(localStorage.getItem('theme_override')).toBeNull();
    expect(localStorage.getItem('theme_override_device')).toBeNull();
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('applyTheme wipes the legacy tri-state key unconditionally', () => {
    localStorage.setItem('theme_preference', 'dark');
    applyTheme();
    expect(localStorage.getItem('theme_preference')).toBeNull();
  });

  it('an override matching the current device theme survives applyTheme', () => {
    setThemeOverride('dark');
    applyTheme();
    expect(localStorage.getItem('theme_override')).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('a live device-theme flip discards an active override (matchMedia change path)', () => {
    setThemeOverride('light'); // recorded under the mocked light device
    expect(document.documentElement.dataset.theme).toBe('light');

    const original = vi.mocked(window.matchMedia).getMockImplementation();
    // Flip the mocked device to dark, then fire the listener theme.ts
    // registered at import time — mirrors a real matchMedia 'change' event.
    vi.mocked(window.matchMedia).mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    try {
      registeredChangeHandler();
      expect(localStorage.getItem('theme_override')).toBeNull();
      expect(document.documentElement.dataset.theme).toBe('dark');
    } finally {
      if (original) vi.mocked(window.matchMedia).mockImplementation(original);
    }
  });
});
