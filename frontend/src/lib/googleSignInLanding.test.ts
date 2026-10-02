import { describe, it, expect, vi, afterEach } from 'vitest';
import { consumeGoogleSignInLanding } from './googleSignInLanding';
import { isAuthenticated } from './auth';
import { isAuthenticatedOrganizer } from './organizerAuth';

function setUrl(search: string, path = '/'): void {
  window.history.replaceState({}, '', `${path}${search}`);
}

describe('consumeGoogleSignInLanding', () => {
  afterEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    window.history.replaceState({}, '', '/');
  });

  it('sets the consumer signed-in hint for google_signin=user and strips the param', () => {
    setUrl('?google_signin=user', '/onboarding');

    consumeGoogleSignInLanding();

    expect(isAuthenticated()).toBe(true);
    expect(isAuthenticatedOrganizer()).toBe(false);
    expect(window.location.search).toBe('');
    expect(window.location.pathname).toBe('/onboarding');
  });

  it('sets the organizer signed-in hint for google_signin=organizer and strips the param', () => {
    setUrl('?google_signin=organizer', '/organizer/dashboard');

    consumeGoogleSignInLanding();

    expect(isAuthenticatedOrganizer()).toBe(true);
    expect(isAuthenticated()).toBe(false);
    expect(window.location.search).toBe('');
  });

  it('preserves other query params while stripping google_signin', () => {
    setUrl('?foo=bar&google_signin=user', '/onboarding');

    consumeGoogleSignInLanding();

    expect(window.location.search).toBe('?foo=bar');
  });

  it('is a no-op with no google_signin param', () => {
    setUrl('', '/onboarding');

    consumeGoogleSignInLanding();

    expect(isAuthenticated()).toBe(false);
    expect(isAuthenticatedOrganizer()).toBe(false);
  });

  it('is a no-op with an unrecognized google_signin value', () => {
    setUrl('?google_signin=admin', '/onboarding');

    consumeGoogleSignInLanding();

    expect(isAuthenticated()).toBe(false);
    expect(isAuthenticatedOrganizer()).toBe(false);
    expect(window.location.search).toBe('?google_signin=admin');
  });
});
