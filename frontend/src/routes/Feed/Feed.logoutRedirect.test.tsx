import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import Feed from './Feed';
import Landing from '../Landing';
import { useAuth } from '../../hooks/useAuth';
import { TOKEN_KEY } from '../../constants';
import { makeEvent } from '../../test/utils';

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

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const headers = (init?.headers ?? {}) as Record<string, string>;
    if (url.startsWith('/api/feed')) {
      if (headers['Authorization']) {
        return { ok: true, status: 200, json: async () => feedResponse, text: async () => '' };
      }
      return { ok: false, status: 401, json: async () => ({}), text: async () => '' };
    }
    // Landing's public showcase query, and anything else — always succeeds, no auth required.
    return { ok: true, status: 200, json: async () => ({ events: [] }), text: async () => '' };
  }));
}

function renderHome(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<div>login page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('logout redirect from the Feed route (/)', () => {
  it('does not hard-redirect to /login when signing out while on the feed', async () => {
    localStorage.setItem(TOKEN_KEY, 'test-session-token');
    stubFetch();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    renderHome(queryClient);

    await waitFor(() => expect(screen.getByText('Event One')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /sign out/i }));

    // The user must land on the marketing Landing page, not a stale/broken Feed.
    await waitFor(() => expect(screen.getByRole('link', { name: /sign in/i })).toBeInTheDocument());
    expect(screen.queryByText(/failed to load your feed/i)).not.toBeInTheDocument();

    // Let any spurious refetch + its 401 handling resolve.
    await waitFor(() => expect(localStorage.getItem(TOKEN_KEY)).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(window.location.replace).not.toHaveBeenCalledWith('/login');
  });
});
