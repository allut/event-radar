import { describe, it, expect } from 'vitest';
import { resolveTheme, getThemePreference, setThemePreference, applyTheme } from './theme';

describe('resolveTheme', () => {
  it('account preference "light" wins regardless of localStorage/system', () => {
    expect(resolveTheme('light', 'dark', true)).toBe('light');
  });

  it('account preference "dark" wins regardless of localStorage/system', () => {
    expect(resolveTheme('dark', 'light', false)).toBe('dark');
  });

  it('account unset + explicit localStorage "light" wins over system', () => {
    expect(resolveTheme(null, 'light', true)).toBe('light');
  });

  it('account unset + explicit localStorage "dark" wins over system', () => {
    expect(resolveTheme(null, 'dark', false)).toBe('dark');
  });

  it('account unset + localStorage "system" falls through to media query (dark)', () => {
    expect(resolveTheme(null, 'system', true)).toBe('dark');
  });

  it('account unset + localStorage "system" falls through to media query (light)', () => {
    expect(resolveTheme(null, 'system', false)).toBe('light');
  });

  it('account unset + localStorage unset (null) falls through to media query (dark)', () => {
    expect(resolveTheme(null, null, true)).toBe('dark');
  });

  it('account unset + localStorage unset (null) falls through to media query (light)', () => {
    expect(resolveTheme(null, null, false)).toBe('light');
  });

  it('account unset + localStorage garbage value falls through to media query', () => {
    expect(resolveTheme(null, 'blue', true)).toBe('dark');
  });
});

describe('getThemePreference', () => {
  it('returns "system" when nothing stored', () => {
    expect(getThemePreference()).toBe('system');
  });

  it('returns "light"/"dark" when stored', () => {
    setThemePreference('dark');
    expect(getThemePreference()).toBe('dark');
    setThemePreference('light');
    expect(getThemePreference()).toBe('light');
  });

  it('returns "system" when the stored value is invalid', () => {
    localStorage.setItem('theme_preference', 'blue');
    expect(getThemePreference()).toBe('system');
  });
});

describe('setThemePreference / applyTheme', () => {
  it('setThemePreference persists to localStorage and applies data-theme', () => {
    setThemePreference('light');
    expect(localStorage.getItem('theme_preference')).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');

    setThemePreference('dark');
    expect(localStorage.getItem('theme_preference')).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('applyTheme re-resolves from current localStorage/system state', () => {
    setThemePreference('system');
    applyTheme();
    // Default mocked matchMedia().matches is false → resolves "light".
    expect(document.documentElement.dataset.theme).toBe('light');
  });
});
