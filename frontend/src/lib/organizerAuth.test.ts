import { describe, it, expect, afterEach } from 'vitest';
import {
  setOrganizerSignedInHint,
  clearOrganizerSignedInHint,
  isAuthenticatedOrganizer,
  beginOrganizerLogout,
  isOrganizerLoggingOut,
} from './organizerAuth';

describe('organizer signed-in hint storage', () => {
  it('setOrganizerSignedInHint sets the hint, isAuthenticatedOrganizer reflects it', () => {
    setOrganizerSignedInHint();
    expect(isAuthenticatedOrganizer()).toBe(true);
  });

  it('clearOrganizerSignedInHint removes the hint', () => {
    setOrganizerSignedInHint();
    clearOrganizerSignedInHint();
    expect(isAuthenticatedOrganizer()).toBe(false);
  });

  it('isAuthenticatedOrganizer returns false when no hint set', () => {
    expect(isAuthenticatedOrganizer()).toBe(false);
  });
});

describe('organizer logout flag', () => {
  // loggingOut is module-level state, not localStorage-backed — reset it
  // explicitly so a test's beginOrganizerLogout() can't leak into the next test.
  afterEach(() => {
    setOrganizerSignedInHint();
    clearOrganizerSignedInHint();
  });

  it('isOrganizerLoggingOut is false by default', () => {
    expect(isOrganizerLoggingOut()).toBe(false);
  });

  it('beginOrganizerLogout sets isOrganizerLoggingOut to true', () => {
    beginOrganizerLogout();
    expect(isOrganizerLoggingOut()).toBe(true);
  });

  it('setOrganizerSignedInHint (a fresh sign-in) resets isOrganizerLoggingOut', () => {
    beginOrganizerLogout();
    setOrganizerSignedInHint();
    expect(isOrganizerLoggingOut()).toBe(false);
  });
});
