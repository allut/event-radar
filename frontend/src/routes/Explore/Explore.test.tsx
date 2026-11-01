import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Explore from './Explore';
import { useNavigate } from 'react-router-dom';
import { LocationProbe, renderWithProviders, makeEvent } from '../../test/utils';
import type { EventData } from '../../components/EventCard';
import { PRERENDER_RUNTIME_FLAG } from '../../constants/prerender';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
  clearSignedInHint: vi.fn(),
  beginLogout: vi.fn(),
  isAuthenticated: vi.fn(() => true),
  subscribeAuth: vi.fn(() => () => undefined),
}));

vi.mock('../../api/client', () => ({
  api: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock('../../components/EventCard', () => ({
  default: ({ event, onFeedbackBlocked, sponsored }: {
    event: { id: number; title: string };
    onFeedbackBlocked?: (signal: string) => void;
    sponsored?: { advertiser: string; explanation: string };
  }) => (
    <div data-testid="event-card" data-sponsored={sponsored ? `${sponsored.advertiser}|${sponsored.explanation}` : undefined}>
      {event.title}
      {onFeedbackBlocked && (
        <button onClick={() => onFeedbackBlocked('bookmark')}>block-bookmark-{event.id}</button>
      )}
    </div>
  ),
}));

import { api } from '../../api/client';
import { isAuthenticated } from '../../lib/auth';
const mockGet = vi.mocked(api.get);
const mockIsAuthenticated = vi.mocked(isAuthenticated);

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

/** Serves `total` matching events (ids 1..total) as GET /explore pages them,
 * sliced by the request's limit/offset. `hold(offset)` may return a promise
 * that delays that page's response. */
function mockPagedExplore(total: number, hold?: (offset: number) => Promise<void> | undefined) {
  mockGet.mockImplementation(async (path: string) => {
    if (path.startsWith('/users/me')) return currentUser;
    const params = new URL(path, 'http://x').searchParams;
    const limit = Number(params.get('limit'));
    const offset = Number(params.get('offset'));
    await hold?.(offset);
    const events: EventData[] = [];
    for (let id = offset + 1; id <= Math.min(offset + limit, total); id++) {
      events.push(makeEvent({ id, title: `Event ${id}` }));
    }
    return { events, total, limit, offset, has_more: offset + events.length < total };
  });
}

const exploreRequests = () =>
  mockGet.mock.calls.map(([url]) => url as string).filter((url) => url.startsWith('/explore?'));

function BackButton() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(-1)}>
      Back
    </button>
  );
}

function renderExplore(route: string) {
  return renderWithProviders(
    <>
      <Explore />
      <LocationProbe />
      <BackButton />
    </>,
    { route, pathPattern: '/:locale/explore' },
  );
}

beforeEach(() => {
  mockGet.mockReset();
  mockIsAuthenticated.mockReturnValue(true);
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

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });

    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.getByText('Jazz Night')).toBeInTheDocument();
  });

  it('links to the ranking disclosure in every state, with no search set', async () => {
    // Loading: the request never settles.
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return new Promise(() => undefined);
    });
    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
    expect(await screen.findByRole('link', { name: 'How results are ordered' })).toHaveAttribute(
      'href',
      '/en/ranking',
    );
  });

  it('keeps the ranking link when results load', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([makeEvent({ id: 1, title: 'Jazz Night' })]));
    });
    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));
    expect(screen.getByRole('link', { name: 'How results are ordered' })).toHaveAttribute('href', '/en/ranking');
  });

  it('fresh load defaults to All events with every category/vibe chip selected', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
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

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
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

    renderWithProviders(<Explore />, { route: '/en/explore?category=', pathPattern: '/:locale/explore' });
    await waitFor(() => expect(screen.getByText(/no events/i)).toBeInTheDocument());

    const calls = mockGet.mock.calls.map((c) => c[0] as string);
    expect(calls.some((c) => c.startsWith('/explore'))).toBe(false);
    expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument();
  });

  it('deselecting the last category chip after results loaded swaps them for the empty state', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([makeEvent({ id: 1, title: 'Old result' })]));
    });
    renderExplore('/en/explore?category=music');
    await waitFor(() => expect(screen.getByText('Old result')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /Categories/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Music' }));

    await waitFor(() => expect(screen.getByText(/no events/i)).toBeInTheDocument());
    expect(screen.queryByText('Old result')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument();
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
  });

  it('switching to For you presets chips to the persona taste and personalizes', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser); // taste: music/trendy only
      return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
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

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
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

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
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

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
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

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });

    await waitFor(() => expect(screen.getByText(/Failed to load events/i)).toBeInTheDocument());
  });

  describe('numbered pager (spec #551)', () => {
    it('pages at 24, mapping ?page to the request offset', async () => {
      mockPagedExplore(130);
      renderExplore('/en/explore?page=3');

      await waitFor(() => expect(screen.getByText('Event 49')).toBeInTheDocument());
      expect(screen.getAllByTestId('event-card')).toHaveLength(24);
      expect(screen.getByText('Event 72')).toBeInTheDocument();
      const requests = exploreRequests();
      expect(requests).toHaveLength(1);
      const params = new URL(requests[0], 'http://x').searchParams;
      expect(params.get('limit')).toBe('24');
      expect(params.get('offset')).toBe('48');
      expect(params.has('cursor')).toBe(false);
    });

    it('shows the pager under the grid with the range label instead of Load more', async () => {
      mockPagedExplore(130);
      const { container } = renderExplore('/en/explore?sort=date');
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());

      const nav = screen.getByRole('navigation', { name: 'Pages' });
      const cards = screen.getAllByTestId('event-card');
      const lastCard = cards[cards.length - 1];
      expect(lastCard.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(within(nav).getByRole('link', { name: 'Page 6' })).toHaveAttribute(
        'href',
        '/en/explore?sort=date&page=6',
      );
      expect(container.textContent).toContain('1–24 of 130');
      expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument();
    });

    it('reads "of 2,000+" when the backend flags the total as a lower bound', async () => {
      mockGet.mockImplementation(async (path: string) => {
        if (path.startsWith('/users/me')) return currentUser;
        const events = Array.from({ length: 24 }, (_, i) => makeEvent({ id: i + 1, title: `Event ${i + 1}` }));
        return { events, total: 2000, limit: 24, offset: 0, has_more: true, total_is_lower_bound: true };
      });
      const { container } = renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());

      expect(container.textContent).toContain('1–24 of 2,000+');
    });

    it('treats a missing total_is_lower_bound as false', async () => {
      mockPagedExplore(130);
      const { container } = renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());

      expect(container.textContent).not.toContain('130+');
    });

    it('after a page change focuses the hidden Events heading and instant-scrolls to it', async () => {
      mockPagedExplore(130);
      renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());
      const heading = screen.getByRole('heading', { level: 2, name: 'Events' });
      expect(heading).toHaveAttribute('tabindex', '-1');

      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

      await waitFor(() => expect(screen.getByText('Event 25')).toBeInTheDocument());
      await waitFor(() => expect(document.activeElement).toBe(heading));
      expect(window.scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'instant' }));
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/explore?page=2');
    });

    it('marks the results aria-busy while the previous page shows as placeholder data', async () => {
      let release: () => void = () => {};
      const page2 = new Promise<void>((resolve) => {
        release = resolve;
      });
      mockPagedExplore(130, (offset) => (offset === 24 ? page2 : undefined));
      renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());
      const results = screen.getByRole('heading', { level: 2, name: 'Events' }).parentElement!;
      expect(results).toHaveAttribute('aria-busy', 'false');

      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

      await waitFor(() => expect(results).toHaveAttribute('aria-busy', 'true'));
      expect(screen.getByText('Event 1')).toBeInTheDocument();
      release();
      await waitFor(() => expect(screen.getByText('Event 25')).toBeInTheDocument());
      expect(results).toHaveAttribute('aria-busy', 'false');
    });

    it('a filter change resets to page 1 in one push, and back restores the previous page', async () => {
      mockPagedExplore(130);
      renderExplore('/en/explore?page=3');
      await waitFor(() => expect(screen.getByText('Event 49')).toBeInTheDocument());

      await userEvent.click(screen.getByRole('button', { name: 'Free only' }));

      await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/explore?free=1'));
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());

      await userEvent.click(screen.getByRole('button', { name: 'Back' }));

      await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/explore?page=3'));
      await waitFor(() => expect(screen.getByText('Event 49')).toBeInTheDocument());
    });

    it('a committed search makes one history entry that resets to page 1', async () => {
      mockPagedExplore(130);
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
      renderExplore('/en/explore?page=2');
      await waitFor(() => expect(screen.getByText('Event 25')).toBeInTheDocument());

      await user.type(screen.getByPlaceholderText(/search events/i), 'jazz');

      await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/explore?q=jazz'));
      await user.click(screen.getByRole('button', { name: 'Back' }));
      await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/explore?page=2'));
    });

    it('an old deep link past the end clamps to the last page', async () => {
      mockPagedExplore(50);
      renderExplore('/en/explore?page=9');

      await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/explore?page=3'));
      await waitFor(() => expect(screen.getByText('Event 49')).toBeInTheDocument());
      expect(screen.queryByText(/no events match/i)).not.toBeInTheDocument();
    });

    it('an empty last page with total > 0 shows the empty state instead of loading forever', async () => {
      // Relevance/For you totals come from the cached ranked list, so every
      // event on the last page can drop out (went non-public) after ranking.
      mockGet.mockImplementation(async (path: string) => {
        if (path.startsWith('/users/me')) return currentUser;
        const offset = Number(new URL(path, 'http://x').searchParams.get('offset'));
        return exploreResponse([], { total: 30, offset });
      });
      renderExplore('/en/explore?page=2');

      await waitFor(() => expect(screen.getByText(/no events match/i)).toBeInTheDocument());
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/explore?page=2');
      expect(screen.queryByText('Loading…')).not.toBeInTheDocument();
    });

    it('a malformed ?page normalizes to page 1 before fetching', async () => {
      mockPagedExplore(50);
      renderExplore('/en/explore?page=abc');

      await waitFor(() => expect(screen.getByTestId('location-probe').textContent).toBe('/en/explore'));
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());
      expect(exploreRequests().every((url) => url.includes('offset=0'))).toBe(true);
    });

    it('shows no pager on an empty result set', async () => {
      mockPagedExplore(0);
      renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText(/no events match/i)).toBeInTheDocument());
      expect(screen.queryByRole('navigation', { name: 'Pages' })).not.toBeInTheDocument();
    });
  });

  describe('paged SEO (spec #551)', () => {
    const canonicalHref = () => document.head.querySelector('link[rel="canonical"]')?.getAttribute('href') ?? null;
    const itemListPositions = () => {
      const raw = Array.from(document.head.querySelectorAll('script[type="application/ld+json"]'))
        .map((el) => JSON.parse(el.textContent ?? '{}'))
        .find((body) => body['@type'] === 'ItemList');
      return raw?.itemListElement.map((el: { position: number }) => el.position) ?? [];
    };

    it('an unfiltered deep page is self-canonical with a matching og:url', async () => {
      mockPagedExplore(130);
      renderExplore('/en/explore?page=3');

      await waitFor(() => expect(canonicalHref()).toBe('https://eventradar.ee/en/explore?page=3'));
      expect(document.head.querySelector('meta[property="og:url"]')?.getAttribute('content')).toBe(
        'https://eventradar.ee/en/explore?page=3',
      );
    });

    it('a filtered deep page keeps the canonical at /explore', async () => {
      mockPagedExplore(130);
      renderExplore('/en/explore?page=3&sort=date');

      await waitFor(() => expect(screen.getByText('Event 49')).toBeInTheDocument());
      await waitFor(() => expect(canonicalHref()).toBe('https://eventradar.ee/en/explore'));
    });

    it('a past-end page canonicalises to the clamped URL, not the requested one', async () => {
      mockPagedExplore(50);
      renderExplore('/en/explore?page=9');

      await waitFor(() => expect(canonicalHref()).toBe('https://eventradar.ee/en/explore?page=3'));
      expect(canonicalHref()).not.toContain('page=9');
    });

    it('a stale page on an empty result canonicalises to the unpaged URL', async () => {
      mockPagedExplore(0);
      renderExplore('/en/explore?page=5');

      await waitFor(() => expect(screen.getByTestId('location-probe').textContent).toBe('/en/explore'));
      await waitFor(() => expect(screen.getByText(/no events match/i)).toBeInTheDocument());
      await waitFor(() => expect(canonicalHref()).toBe('https://eventradar.ee/en/explore'));
    });

    it('the ItemList covers only the current page at positions 1..n', async () => {
      mockPagedExplore(130);
      renderExplore('/en/explore?page=3');

      await waitFor(() => expect(itemListPositions()).toHaveLength(24));
      expect(itemListPositions()[0]).toBe(1);
      expect(itemListPositions()[23]).toBe(24);
    });
  });

  describe('prerender readiness marker (issue #236)', () => {
    it('is absent while the query is loading', () => {
      mockGet.mockImplementation(() => new Promise(() => {})); // never resolves
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      expect(document.querySelector('[data-prerender-ready="true"]')).toBeNull();
    });

    it('is present, with no error marker, once the query succeeds', async () => {
      mockGet.mockImplementation((path: string) => {
        if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
        return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
      });
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });

      await waitFor(() => expect(document.querySelector('[data-prerender-ready="true"]')).not.toBeNull());
      expect(document.querySelector('[data-prerender-error="true"]')).toBeNull();
    });

    it('is present alongside the error marker once the query errors, so the build can fail loudly instead of timing out', async () => {
      mockGet.mockImplementation((path: string) => {
        if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
        return Promise.reject(new Error('network'));
      });
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });

      await waitFor(() => expect(document.querySelector('[data-prerender-ready="true"]')).not.toBeNull());
      expect(document.querySelector('[data-prerender-error="true"]')).not.toBeNull();
    });
  });

  it('a chip click during a pending search debounce does not clobber it', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([]));
    });

    // Real timers made this test's debounce wait flaky under a loaded CI
    // runner (timeout races against the actual 400ms clock). Fake timers +
    // userEvent's advanceTimers option drive the debounce deterministically
    // instead — same pattern as utils/eventActions.test.ts / useToast.test.ts / Settings.test.tsx.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
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
    await waitFor(() => {
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
    });
  });

  describe('Sponsored slot (issue #603)', () => {
    const SLOT = { advertiser: 'Telliskivi Selts MTÜ', explanation: 'filters', tile: 4 };

    /** Serves `total` organic events the way GET /explore?sponsored_slot=true
     * does when page 1 has a slot: page 1 holds limit - 1 organic rows plus the
     * slot payload, later pages start one row earlier and echo the offset. */
    function mockSlotExplore(total: number, withSlot = true) {
      mockGet.mockImplementation(async (path: string) => {
        if (path.startsWith('/users/me')) return currentUser;
        const params = new URL(path, 'http://x').searchParams;
        const limit = Number(params.get('limit'));
        const offset = Number(params.get('offset'));
        const optedIn = params.get('sponsored_slot') === 'true';
        const slotted = optedIn && withSlot;
        const start = slotted && offset > 0 ? offset - 1 : offset;
        const count = slotted && offset === 0 ? limit - 1 : limit;
        const events: EventData[] = [];
        for (let id = start + 1; id <= Math.min(start + count, total); id++) {
          events.push(makeEvent({ id, title: `Event ${id}` }));
        }
        const body: Record<string, unknown> = { events, total, limit, offset, has_more: start + events.length < total };
        if (optedIn) body.page1_has_slot = slotted;
        if (slotted && offset === 0) body.sponsored_slot = { ...makeEvent({ id: 900, title: 'Paid Event' }), ...SLOT };
        return body;
      });
    }

    afterEach(() => {
      delete (window as unknown as Record<string, unknown>)[PRERENDER_RUNTIME_FLAG];
    });

    it('asks for the slot on a normal render', async () => {
      mockSlotExplore(60);
      renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());
      expect(new URL(exploreRequests()[0], 'http://x').searchParams.get('sponsored_slot')).toBe('true');
    });

    it('never asks for the slot under the prerender', async () => {
      (window as unknown as Record<string, unknown>)[PRERENDER_RUNTIME_FLAG] = true;
      mockSlotExplore(60);
      renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());
      expect(exploreRequests()[0]).not.toContain('sponsored_slot');
      expect(document.querySelector('[data-sponsored]')).toBeNull();
    });

    it('renders the slot at tile #4 of page 1 among 23 organic cards', async () => {
      mockSlotExplore(60);
      renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Paid Event')).toBeInTheDocument());
      const cards = screen.getAllByTestId('event-card');
      expect(cards).toHaveLength(24);
      expect(cards[3]).toHaveTextContent('Paid Event');
      expect(cards[3]).toHaveAttribute('data-sponsored', 'Telliskivi Selts MTÜ|filters');
      expect(cards[2]).toHaveTextContent('Event 3');
      expect(cards[4]).toHaveTextContent('Event 4');
      expect(cards.filter((c) => c.hasAttribute('data-sponsored'))).toHaveLength(1);
    });

    it.each([
      ['signed in', true],
      ['signed out', false],
    ])('makes the slot the 4th event card (3 organic before it), %s', async (_label, authed) => {
      mockIsAuthenticated.mockReturnValue(authed);
      mockSlotExplore(60);
      renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Paid Event')).toBeInTheDocument());
      const cards = screen.getAllByTestId('event-card');
      const slotAt = cards.findIndex((c) => c.hasAttribute('data-sponsored'));
      expect(slotAt).toBe(3);
      ['Event 1', 'Event 2', 'Event 3'].forEach((title, i) => expect(cards[i]).toHaveTextContent(title));
    });

    it('sizes the pager as ceil((total + 1) / limit) when page 1 carries a slot', async () => {
      mockSlotExplore(48);
      renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());
      const nav = screen.getByRole('navigation', { name: 'Pages' });
      expect(within(nav).getByRole('link', { name: 'Page 3' })).toBeInTheDocument();
    });

    it('keeps ceil(total / limit) pages when no slot fills', async () => {
      mockSlotExplore(48, false);
      renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());
      const nav = screen.getByRole('navigation', { name: 'Pages' });
      expect(within(nav).queryByRole('link', { name: 'Page 3' })).not.toBeInTheDocument();
      expect(within(nav).getByRole('link', { name: 'Page 2' })).toBeInTheDocument();
    });

    it('labels page 1 over organic rows only', async () => {
      mockSlotExplore(60);
      const { container } = renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());
      expect(container.textContent).toContain('1–23 of 60');
    });

    it('labels page 2 from the first organic row it holds', async () => {
      mockSlotExplore(60);
      const { container } = renderExplore('/en/explore?page=2');
      await waitFor(() => expect(screen.getByText('Event 24')).toBeInTheDocument());
      expect(screen.queryByText('Event 23')).not.toBeInTheDocument();
      expect(container.textContent).toContain('24–47 of 60');
    });

    it('leaves the slot out of the ItemList and keeps positions 1..n over organic events', async () => {
      mockSlotExplore(60);
      renderExplore('/en/explore');
      await waitFor(() => expect(screen.getByText('Paid Event')).toBeInTheDocument());
      await waitFor(() => expect(document.head.querySelector('script[type="application/ld+json"]')).not.toBeNull());
      const raw = Array.from(document.head.querySelectorAll('script[type="application/ld+json"]'))
        .map((el) => JSON.parse(el.textContent ?? '{}'))
        .find((body) => body['@type'] === 'ItemList');
      const items = raw.itemListElement as { position: number; item: { url: string } }[];
      expect(items.map((el) => el.position)).toEqual(Array.from({ length: 23 }, (_, i) => i + 1));
      expect(items.some((el) => el.item.url.endsWith('/events/900'))).toBe(false);
    });
  });

  describe('anonymous visitor (issue #235)', () => {
    beforeEach(() => {
      mockIsAuthenticated.mockReturnValue(false);
    });

    it('never calls /users/me when signed out', async () => {
      mockGet.mockImplementation(() => Promise.resolve(exploreResponse([makeEvent({ id: 1 }), makeEvent({ id: 2 })])));
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));

      const calls = mockGet.mock.calls.map((c) => c[0] as string);
      expect(calls.some((c) => c.startsWith('/users/me'))).toBe(false);
    });

    it('renders the persistent upsell card and opens the sign-in modal from its CTA', async () => {
      mockGet.mockImplementation(() => Promise.resolve(exploreResponse([makeEvent({ id: 1 })])));
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      await waitFor(() => expect(screen.getByText('Like what you see?')).toBeInTheDocument());

      await userEvent.click(screen.getByRole('button', { name: 'Sign in to personalize →' }));

      expect(screen.getByRole('dialog', { name: 'Sign in' })).toBeInTheDocument();
      expect(screen.getByText('Sign in for your picks')).toBeInTheDocument();
    });

    it('intercepts a blocked feedback press into the save/thumbs sign-in modal without a second trigger reopening it', async () => {
      mockGet.mockImplementation(() =>
        Promise.resolve(exploreResponse([
          makeEvent({ id: 1, title: 'First' }),
          makeEvent({ id: 2, title: 'Second' }),
          makeEvent({ id: 3, title: 'Third' }),
        ])),
      );
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(3));

      await userEvent.click(screen.getByText('block-bookmark-1'));
      expect(screen.getByText('Sign in to save this')).toBeInTheDocument();

      // A second trigger click while the modal is open is a no-op — the
      // modal keeps its original copy.
      await userEvent.click(screen.getByText('block-bookmark-2'));
      expect(screen.getByText('Sign in to save this')).toBeInTheDocument();
    });

    it('turning on For-you intercepts into the sign-in modal instead of applying the filter', async () => {
      mockGet.mockImplementation(() => Promise.resolve(exploreResponse([])));
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toBeInTheDocument());

      await userEvent.click(screen.getByRole('button', { name: 'For you' }));

      expect(screen.getByRole('dialog', { name: 'Sign in' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'false');
    });

    it('shows the sign-up strip above all 24 events on page 1', async () => {
      mockPagedExplore(60);
      renderExplore('/en/explore');

      await waitFor(() => expect(screen.getAllByTestId('event-card')).toHaveLength(24));
      const strip = screen.getByText('Like what you see?').closest('aside');
      expect(strip).not.toBeNull();
      const firstCard = screen.getAllByTestId('event-card')[0];
      expect(strip!.compareDocumentPosition(firstCard) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(strip!.parentElement).toBe(firstCard.parentElement);
    });

    it('shows the strip and all 24 events on a deep page', async () => {
      mockPagedExplore(60);
      renderExplore('/en/explore?page=2');

      await waitFor(() => expect(screen.getAllByTestId('event-card')).toHaveLength(24));
      expect(screen.getByText('Event 25')).toBeInTheDocument();
      expect(screen.getByText('Event 48')).toBeInTheDocument();
      expect(screen.getByText('Like what you see?')).toBeInTheDocument();
    });

    it('shows neither grid nor strip when nothing matches', async () => {
      mockGet.mockImplementation(() => Promise.resolve(exploreResponse([])));
      renderExplore('/en/explore');

      await waitFor(() => expect(screen.getByText('No events match')).toBeInTheDocument());
      expect(screen.queryByText('Like what you see?')).not.toBeInTheDocument();
      expect(screen.queryAllByTestId('event-card')).toHaveLength(0);
    });

    it('shows no strip when signed in', async () => {
      mockIsAuthenticated.mockReturnValue(true);
      mockPagedExplore(30);
      renderExplore('/en/explore');

      await waitFor(() => expect(screen.getAllByTestId('event-card')).toHaveLength(24));
      expect(screen.queryByText('Like what you see?')).not.toBeInTheDocument();
    });
  });

  it('keeps the page when the already-active "All events" option is picked again', async () => {
    mockPagedExplore(100);
    renderExplore('/en/explore?page=3');
    await waitFor(() => expect(screen.getByText('Event 49')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /All events/ }));

    expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/en\/explore\?page=3$/);
    expect(screen.getByText('Event 49')).toBeInTheDocument();
  });
});
