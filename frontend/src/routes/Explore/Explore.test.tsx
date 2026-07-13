import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Explore from './Explore';
import { renderWithProviders, makeEvent } from '../../test/utils';
import { EXPLORE_SEARCH_DEBOUNCE_MS } from '../../constants';
import type { EventData } from '../../components/EventCard';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
  clearToken: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock('../../components/EventCard', () => ({
  default: ({ event }: { event: { title: string } }) => <div data-testid="event-card">{event.title}</div>,
}));

import { api } from '../../api/client';
const mockGet = vi.mocked(api.get);

interface ExploreResponse {
  events: EventData[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

function exploreResponse(
  events: EventData[],
  opts: Partial<Pick<ExploreResponse, 'total' | 'offset' | 'has_more'>> = {},
): ExploreResponse {
  return {
    events,
    total: opts.total ?? events.length,
    limit: 24,
    offset: opts.offset ?? 0,
    has_more: opts.has_more ?? false,
  };
}

const currentUser = { preferred_categories: ['music'], preferred_vibes: ['trendy'] };

beforeEach(() => {
  mockGet.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('Explore', () => {
  it('renders event grid from the API', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(
        exploreResponse([makeEvent({ id: 1, title: 'Jazz Night' }), makeEvent({ id: 2, title: 'Art Show' })]),
      );
    });

    renderWithProviders(<Explore />, { route: '/explore' });

    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.getByText('Jazz Night')).toBeInTheDocument();
  });

  it('clicking a category chip updates the URL/query and refetches', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
    });

    renderWithProviders(<Explore />, { route: '/explore' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));

    await userEvent.click(screen.getByRole('button', { name: /Categories/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Music' }));

    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0] as string);
      expect(calls.some((c) => c.startsWith('/explore') && c.includes('category=music'))).toBe(true);
    });
  });

  it('load more fetches the next page and appends results', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      if (path.includes('offset=1')) {
        return Promise.resolve(exploreResponse([makeEvent({ id: 2, title: 'Second Event' })], { total: 2, offset: 1 }));
      }
      return Promise.resolve(
        exploreResponse([makeEvent({ id: 1, title: 'First Event' })], { total: 2, offset: 0, has_more: true }),
      );
    });

    renderWithProviders(<Explore />, { route: '/explore' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));

    await userEvent.click(screen.getByRole('button', { name: /load more/i }));

    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.getByText('Second Event')).toBeInTheDocument();
  });

  it('selecting a category outside the user\'s taste auto-flips For-you off', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser); // taste: music/trendy only
      return Promise.resolve(exploreResponse([]));
    });

    renderWithProviders(<Explore />, { route: '/explore' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true'));

    await userEvent.click(screen.getByRole('button', { name: /Categories/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Theatre' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'false'));
    expect(screen.getByRole('button', { name: 'All events' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('selecting an in-taste category keeps For-you on', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([]));
    });

    renderWithProviders(<Explore />, { route: '/explore' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true'));

    await userEvent.click(screen.getByRole('button', { name: /Categories/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Music' }));

    expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows error state on fetch failure', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.reject(new Error('network'));
    });

    renderWithProviders(<Explore />, { route: '/explore' });

    await waitFor(() => expect(screen.getByText(/Failed to load events/i)).toBeInTheDocument());
  });

  it('a chip click during a pending search debounce does not clobber it', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([]));
    });

    const user = userEvent.setup();

    renderWithProviders(<Explore />, { route: '/explore' });
    await waitFor(() => expect(screen.getByRole('button', { name: /Categories/ })).toBeInTheDocument());

    await user.type(screen.getByPlaceholderText(/search events/i), 'jazz');
    await user.click(screen.getByRole('button', { name: /Categories/ }));
    await user.click(screen.getByRole('button', { name: 'Music' }));

    // Wait past the debounce window — both the typed text and the chip click
    // (made while the debounce was still pending) must land in the committed
    // query, not just whichever one the debounce effect's closure captured.
    await waitFor(
      () => {
        const calls = mockGet.mock.calls.map((c) => c[0] as string);
        expect(
          calls.some((c) => c.startsWith('/explore') && c.includes('q=jazz') && c.includes('category=music')),
        ).toBe(true);
      },
      { timeout: EXPLORE_SEARCH_DEBOUNCE_MS + 3000 },
    );
  }, EXPLORE_SEARCH_DEBOUNCE_MS + 5000);
});
