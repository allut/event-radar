import { describe, it, expect, afterEach } from 'vitest';
import {
  getOrganizerToken,
  setOrganizerToken,
  clearOrganizerToken,
  isAuthenticatedOrganizer,
  beginOrganizerLogout,
  isOrganizerLoggingOut,
} from './organizerAuth';

describe('organizer token storage', () => {
  it('setOrganizerToken stores token, getOrganizerToken retrieves it', () => {
    setOrganizerToken('abc123');
    expect(getOrganizerToken()).toBe('abc123');
  });

  it('clearOrganizerToken removes token', () => {
    setOrganizerToken('abc123');
    clearOrganizerToken();
    expect(getOrganizerToken()).toBeNull();
  });

  it('isAuthenticatedOrganizer returns true when token set', () => {
    setOrganizerToken('tok');
    expect(isAuthenticatedOrganizer()).toBe(true);
  });

  it('isAuthenticatedOrganizer returns false when no token', () => {
    expect(isAuthenticatedOrganizer()).toBe(false);
  });
});

describe('organizer logout flag', () => {
  // loggingOut is module-level state, not localStorage-backed — reset it
  // explicitly so a test's beginOrganizerLogout() can't leak into the next test.
  afterEach(() => {
    setOrganizerToken('reset');
    clearOrganizerToken();
  });

  it('isOrganizerLoggingOut is false by default', () => {
    expect(isOrganizerLoggingOut()).toBe(false);
  });

  it('beginOrganizerLogout sets isOrganizerLoggingOut to true', () => {
    beginOrganizerLogout();
    expect(isOrganizerLoggingOut()).toBe(true);
  });

  it('setOrganizerToken (a fresh sign-in) resets isOrganizerLoggingOut', () => {
    beginOrganizerLogout();
    setOrganizerToken('fresh-token');
    expect(isOrganizerLoggingOut()).toBe(false);
  });
});
