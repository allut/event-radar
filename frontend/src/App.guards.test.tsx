import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from './App';
import { setSignedInHint } from './lib/auth';
import { setOrganizerSignedInHint } from './lib/organizerAuth';
import { setAdminSignedInHint } from './lib/adminAuth';
import { t } from './i18n';

// Covers the two route guards in App.tsx that App.locale.test.tsx only
// touches incidentally (one Protected-redirect case): the authenticated
// pass-through branch of both Protected and OrganizerProtected, and
// OrganizerProtected's own redirect, which had no coverage at all.
//
// Network is left unmocked, same rationale as App.locale.test.tsx: every
// route exercised here renders a (still guard-correct) loading/error state
// on a failed fetch, so assertions stay focused on the guard itself.

function setPath(path: string) {
  window.history.pushState(null, '', path);
}

beforeEach(() => {
  localStorage.clear();
  setPath('/');
});

describe('App route guards', () => {
  it('Protected redirects an unauthenticated visitor to /login', async () => {
    setPath('/settings');
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe('/login'));
  });

  it('Protected renders the guarded route for an authenticated visitor', async () => {
    setSignedInHint();
    setPath('/settings');
    render(<App />);

    // Settings only mounts its TopBar once its /users/me fetch settles, so the
    // guard-passed signal here is that Settings itself mounted (its loading
    // state), not the redirect target (Login) — the fetch is left unmocked
    // and never settles inside a unit test's lifetime.
    await waitFor(() => expect(screen.getByLabelText(t('loading', 'et'))).toBeInTheDocument());
    expect(window.location.pathname).toBe('/settings');
  });

  it('OrganizerProtected redirects an unauthenticated visitor to /organizer/login', async () => {
    setPath('/organizer/dashboard');
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe('/organizer/login'));
  });

  it('OrganizerProtected renders the guarded route for an authenticated organizer', async () => {
    setOrganizerSignedInHint();
    setPath('/organizer/dashboard');
    render(<App />);

    // OrganizerDashboard's own local locale state defaults via getLocale()
    // (LOCALES[0] = 'en'), not BareLocaleGate's bare-path Estonian default —
    // see useLocalLocale.
    await waitFor(() =>
      expect(screen.getByRole('navigation', { name: t('organizer_dashboard_title', 'en') })).toBeInTheDocument(),
    );
    expect(window.location.pathname).toBe('/organizer/dashboard');
  });

  it('does not let an organizer session satisfy the consumer Protected guard, or vice versa', async () => {
    setOrganizerSignedInHint();
    setPath('/settings');
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe('/login'));
  });

  // AdminApp is a React.lazy chunk (issue #154) — first-mount compilation of
  // that chunk can outrun waitFor's default 1000ms timeout on a cold cache,
  // so these three give it more room than the rest of this file needs.
  const ADMIN_CHUNK_TIMEOUT = { timeout: 5000 };

  it('AdminProtected redirects an unauthenticated visitor to /admin/login', async () => {
    setPath('/admin');
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe('/admin/login'), ADMIN_CHUNK_TIMEOUT);
  });

  it('AdminProtected renders the guarded route for an authenticated admin', async () => {
    setAdminSignedInHint();
    setPath('/admin');
    render(<App />);

    await waitFor(
      () => expect(screen.getByRole('navigation', { name: 'Admin' })).toBeInTheDocument(),
      ADMIN_CHUNK_TIMEOUT,
    );
    expect(window.location.pathname).toBe('/admin');
  });

  it('does not let a consumer or organizer session satisfy the admin guard', async () => {
    setSignedInHint();
    setOrganizerSignedInHint();
    setPath('/admin/reports');
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe('/admin/login'), ADMIN_CHUNK_TIMEOUT);
  });

  it('gates the catch-all NotFound route behind Protected', async () => {
    // A single unmatched segment (e.g. "/nonexistent") isn't enough to reach
    // the "*" splat here — App.tsx's own "/:locale" pattern (Home's
    // locale-prefixed route) matches any one bare segment first and treats
    // it as an (unrecognized, ignored) locale param, rendering Home. Two
    // segments are needed to actually fall through to the catch-all.
    setPath('/this/route-does-not-exist');
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe('/login'));
  });
});
