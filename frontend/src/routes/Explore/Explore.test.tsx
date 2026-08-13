import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Explore from './Explore';
import { renderWithProviders, makeEvent } from '../../test/utils';
import { EXPLORE_SEARCH_DEBOUNCE_MS } from '../../constants';
import type { EventData } from '../../components/EventCard';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
  clearSignedInHint: vi.fn(),
  beginLogout: vi.fn(),
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

  it('fresh load defaults to All events with every category/vibe chip selected', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
    });

    renderWithProviders(<Explore />, { route: '/explore' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));

    expect(screen.getByRole('button', { name: 'All events' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Categories · 14/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Vibes · 10/ })).toBeInTheDocument();

    const calls = mockGet.mock.calls.map((c) => c[0] as string);
    const exploreCall = calls.find((c) => c.startsWith('/explore'));
    expect(exploreCall).toBeDefined();
    expect(exploreCall).not.toContain('category=');
    expect(exploreCall).not.toContain('vibe=');
    expect(exploreCall).toContain('for_you=false');
  });

  it('deselecting a category chip narrows the query while staying on All events', async () => {
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
      const exploreCall = calls.find((c) => c.startsWith('/explore') && c.includes('category='));
      expect(exploreCall).toBeDefined();
      expect(exploreCall).not.toMatch(/category=[^&]*\bmusic\b/);
    });
    expect(screen.getByRole('button', { name: 'All events' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('deselecting every category chip shows no results and skips the request', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
    });

    renderWithProviders(<Explore />, { route: '/explore?category=' });
    await waitFor(() => expect(screen.getByText(/no events/i)).toBeInTheDocument());

    const calls = mockGet.mock.calls.map((c) => c[0] as string);
    expect(calls.some((c) => c.startsWith('/explore'))).toBe(false);
    expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument();
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

  it('switching to For you presets chips to the persona taste and personalizes', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser); // taste: music/trendy only
      return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
    });

    renderWithProviders(<Explore />, { route: '/explore' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'All events' })).toHaveAttribute('aria-pressed', 'true'));

    await userEvent.click(screen.getByRole('button', { name: 'For you' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true'));
    expect(screen.getByRole('button', { name: /Categories · 1/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Vibes · 1/ })).toBeInTheDocument();

    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0] as string);
      const exploreCall = calls.find((c) => c.startsWith('/explore') && c.includes('for_you=true'));
      expect(exploreCall).toBeDefined();
      expect(exploreCall).toContain('category=music');
      expect(exploreCall).toContain('vibe=trendy');
    });
  });

  it('selecting a category outside the user\'s taste while in For-you auto-flips to All events, keeping the prior selection plus the new chip', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser); // taste: music/trendy only
      return Promise.resolve(exploreResponse([]));
    });

    renderWithProviders(<Explore />, { route: '/explore' });
    await userEvent.click(screen.getByRole('button', { name: 'For you' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true'));

    await userEvent.click(screen.getByRole('button', { name: /Categories/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Theatre' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'false'));
    expect(screen.getByRole('button', { name: 'All events' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Categories · 2/ })).toBeInTheDocument();

    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0] as string);
      const exploreCall = calls.find((c) => c.startsWith('/explore') && c.includes('theater'));
      expect(exploreCall).toBeDefined();
      expect(exploreCall).toContain('music');
    });
  });

  it('removing an in-taste chip while in For-you does not flip the switch off', async () => {
    const currentUserMulti = { preferred_categories: ['music', 'theater'], preferred_vibes: ['trendy'] };
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUserMulti);
      return Promise.resolve(exploreResponse([]));
    });

    renderWithProviders(<Explore />, { route: '/explore' });
    await userEvent.click(screen.getByRole('button', { name: 'For you' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Categories · 2/ })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /Categories/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Music' }));

    expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('switching back to All events reselects every category/vibe chip', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([]));
    });

    renderWithProviders(<Explore />, { route: '/explore' });
    await userEvent.click(screen.getByRole('button', { name: 'For you' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Categories · 1/ })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'All events' }));

    await waitFor(() => expect(screen.getByRole('button', { name: /Categories · 14/ })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /Vibes · 10/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'false');
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
    // Deselecting the (default-checked) Music chip narrows the category param;
    // the assertion below just needs to see both the typed text and the
    // narrowed category param land in the same committed query.
    await waitFor(
      () => {
        const calls = mockGet.mock.calls.map((c) => c[0] as string);
        // Assert on the *final* committed /explore query, not the first q=jazz
        // call. Under load the debounce may not coalesce the typed text and the
        // mid-debounce chip toggle into one window, emitting a transient q=jazz
        // call before the narrowed category lands. "No clobber" is a property
        // of the settled query, so check the last committed call.
        const exploreCalls = calls.filter((c) => c.startsWith('/explore'));
        const exploreCall = exploreCalls[exploreCalls.length - 1];
        expect(exploreCall).toContain('q=jazz');
        expect(exploreCall).toMatch(/category=/);
        expect(exploreCall).not.toMatch(/category=[^&]*\bmusic\b/);
      },
      { timeout: EXPLORE_SEARCH_DEBOUNCE_MS + 3000 },
    );
  }, EXPLORE_SEARCH_DEBOUNCE_MS + 5000);
});
