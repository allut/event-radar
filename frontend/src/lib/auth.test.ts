import { describe, it, expect } from 'vitest';
import { getToken, setToken, clearToken, isAuthenticated, getLocale, setLocale } from './auth';
import { LOCALES } from '../constants';

describe('token storage', () => {
  it('setToken stores token, getToken retrieves it', () => {
    setToken('abc123');
    expect(getToken()).toBe('abc123');
  });

  it('clearToken removes token', () => {
    setToken('abc123');
    clearToken();
    expect(getToken()).toBeNull();
  });

  it('isAuthenticated returns true when token set', () => {
    setToken('tok');
    expect(isAuthenticated()).toBe(true);
  });

  it('isAuthenticated returns false when no token', () => {
    expect(isAuthenticated()).toBe(false);
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
