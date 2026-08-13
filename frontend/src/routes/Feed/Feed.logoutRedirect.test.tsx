import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient } from '@tanstack/react-query';
import Feed from './Feed';
import Landing from '../Landing';
import { useAuth } from '../../hooks/useAuth';
import { SIGNED_IN_HINT_KEY } from '../../constants';
import { makeEvent, renderWithProviders } from '../../test/utils';

// Reproduces the real App.tsx `Home` component: Feed for signed-in users,
// Landing for signed-out ones. Uses the real `../../api/client` and real
// `../../lib/auth` (backed by localStorage) so the actual 401 hard-redirect
// interceptor in client.ts is exercised — this is the only way to observe
// the logout race that a fully-mocked `api` module would hide.
function Home() {
  const authed = useAuth();
  return authed ? <Feed /> : <Landing />;
}

const feedResponse = {
  feed_date: '2024-07-15',
  events: [makeEvent({ id: 1, title: 'Event One' })],
  built_at: '2024-07-15T06:00:00Z',
};

const originalLocation = window.location;

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { replace: vi.fn() },
  });
});

afterEach(() => {
  Object.defineProperty(window, 'location', {
    writable: true,
    value: originalLocation,
  });
  vi.unstubAllGlobals();
});

// Stands in for the real session cookie: fetch has no visibility into
// localStorage, so this closure flag tracks "does the browser still have a
// live session cookie" the same way a real cookie jar would, flipped by the
// stubbed /auth/logout call below.
function stubFetch() {
  let authed = true;
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.startsWith('/api/auth/logout')) {
      authed = false;
      return { ok: true, status: 200, json: async () => ({}), text: async () => '' };
    }
    if (url.startsWith('/api/feed')) {
      if (authed) {
        return { ok: true, status: 200, json: async () => feedResponse, text: async () => '' };
      }
      return { ok: false, status: 401, json: async () => ({}), text: async () => '' };
    }
    // Landing's public showcase query, and anything else — always succeeds, no auth required.
    return { ok: true, status: 200, json: async () => ({ events: [] }), text: async () => '' };
  }));
}

function renderHome(queryClient: QueryClient) {
  // Home is one of the two public SEO routes (App.tsx's ROUTE_DEFS): its bare
  // path always renders Estonian, so this test drives it through an explicit
  // `/en` locale prefix (mirroring App.tsx's `/:locale` route registration)
  // to keep asserting against English strings.
  return renderWithProviders(null, {
    route: '/en',
    queryClient,
    routes: [
      { path: '/:locale', element: <Home /> },
      { path: '/', element: <Home /> },
      { path: '/login', element: <div>login page</div> },
    ],
  });
}

describe('logout redirect from the Feed route (/)', () => {
  it('does not hard-redirect to /login when signing out while on the feed', async () => {
    localStorage.setItem(SIGNED_IN_HINT_KEY, '1');
    stubFetch();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    renderHome(queryClient);

    await waitFor(() => expect(screen.getByText('Event One')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /sign out/i }));

    // The user must land on the marketing Landing page, not a stale/broken
    // Feed. Post-logout navigation lands on bare "/" — one of the two public
    // SEO routes, which always renders Estonian regardless of any earlier
    // locale — so this asserts on the login link's href, not its (now
    // Estonian) accessible name.
    await waitFor(() => expect(screen.getByRole('link', { name: /logi sisse/i })).toHaveAttribute('href', '/login'));
    expect(screen.queryByText(/voo laadimine ebaõnnestus/i)).not.toBeInTheDocument();

    // Let any spurious refetch + its 401 handling resolve.
    await waitFor(() => expect(localStorage.getItem(SIGNED_IN_HINT_KEY)).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(window.location.replace).not.toHaveBeenCalledWith('/login');
  });
});
