import { describe, it, expect, afterEach } from 'vitest';
import { setSignedInHint, clearSignedInHint, isAuthenticated, getLocale, getStoredLocale, setLocale, clearLocale, subscribeLocale, beginLogout, isLoggingOut } from './auth';
import { LOCALES } from '../constants';

describe('signed-in hint storage', () => {
  it('setSignedInHint sets the hint, isAuthenticated reflects it', () => {
    setSignedInHint();
    expect(isAuthenticated()).toBe(true);
  });

  it('clearSignedInHint removes the hint', () => {
    setSignedInHint();
    clearSignedInHint();
    expect(isAuthenticated()).toBe(false);
  });

  it('isAuthenticated returns false when no hint set', () => {
    expect(isAuthenticated()).toBe(false);
  });
});

describe('logout flag', () => {
  // loggingOut is module-level state, not localStorage-backed — reset it
  // explicitly so a test's beginLogout() can't leak into the next test.
  afterEach(() => {
    setSignedInHint();
    clearSignedInHint();
  });

  it('isLoggingOut is false by default', () => {
    expect(isLoggingOut()).toBe(false);
  });

  it('beginLogout sets isLoggingOut to true', () => {
    beginLogout();
    expect(isLoggingOut()).toBe(true);
  });

  it('setSignedInHint (a fresh sign-in) resets isLoggingOut', () => {
    beginLogout();
    setSignedInHint();
    expect(isLoggingOut()).toBe(false);
  });
});

describe('getLocale', () => {
  it('returns stored locale when valid', () => {
    setLocale('et');
    expect(getLocale()).toBe('et');
  });

  it('returns first locale when stored value invalid', () => {
    localStorage.setItem('locale', 'zz');
    expect(getLocale()).toBe(LOCALES[0].code);
  });

  it('returns first locale when nothing stored', () => {
    expect(getLocale()).toBe(LOCALES[0].code);
  });
});

describe('setLocale', () => {
  it('persists locale to localStorage', () => {
    setLocale('ru');
    expect(localStorage.getItem('locale')).toBe('ru');
  });
});

describe('clearLocale', () => {
  it('removes the stored locale key', () => {
    setLocale('ru');
    clearLocale();
    expect(localStorage.getItem('locale')).toBeNull();
    expect(getStoredLocale()).toBeNull();
  });

  it('notifies locale subscribers', () => {
    setLocale('ru');
    let notified = false;
    const unsubscribe = subscribeLocale(() => { notified = true; });
    clearLocale();
    unsubscribe();
    expect(notified).toBe(true);
  });
});
