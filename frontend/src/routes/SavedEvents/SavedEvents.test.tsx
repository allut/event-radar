import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SavedEvents from './SavedEvents';
import { LocationProbe, renderWithProviders, makeEvent } from '../../test/utils';
import { useFeedback } from '../../hooks/useFeedback';
import type { EventData } from '../../components/EventCard';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
  isAuthenticated: vi.fn(() => true),
  subscribeAuth: vi.fn(() => () => undefined),
  clearSignedInHint: vi.fn(),
  beginLogout: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn().mockResolvedValue(undefined),
    delete: vi.fn(),
  },
}));

// The card's unsave goes through the real useFeedback, the one path that
// tells the Saved list its membership changed.
vi.mock('../../components/EventCard', () => ({
  default: function MockEventCard({ event }: { event: { id: number; title: string } }) {
    const { sendFeedback } = useFeedback(event.id, { initialSignal: 'bookmark' });
    return (
      <div data-testid="event-card">
        {event.title}
        <button type="button" onClick={() => sendFeedback('bookmark')}>
          Unsave {event.title}
        </button>
      </div>
    );
  },
}));

import { api } from '../../api/client';
const mockGet = vi.mocked(api.get);
const mockDelete = vi.mocked(api.delete);

interface SavedEventsResponse {
  events: EventData[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

function savedResponse(events: EventData[], total = events.length): SavedEventsResponse {
  return { events, total, limit: 24, offset: 0, has_more: false };
}

/** Serves GET /feedback/events from per-signal lists of event ids, sliced by
 * the request's limit/offset the way the endpoint pages them. DELETE
 * /feedback/{id} removes the id from every list (an unsave). */
function mockSavedServer(lists: Partial<Record<string, number[]>>) {
  const state: Record<string, number[]> = {};
  for (const [signal, ids] of Object.entries(lists)) state[signal] = [...(ids ?? [])];
  mockGet.mockImplementation(async (path: string) => {
    const params = new URL(path, 'http://x').searchParams;
    const ids = state[params.get('signal') ?? ''] ?? [];
    const limit = Number(params.get('limit'));
    const offset = Number(params.get('offset'));
    const events = ids
      .slice(offset, offset + limit)
      .map((id) => makeEvent({ id, title: `Saved ${id}` }));
    return { events, total: ids.length, limit, offset, has_more: offset + events.length < ids.length };
  });
  mockDelete.mockImplementation(async (path: string) => {
    const id = Number(path.split('/').pop());
    for (const signal of Object.keys(state)) state[signal] = state[signal].filter((x) => x !== id);
    return undefined;
  });
}

const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => from + i);

const savedRequests = () =>
  mockGet.mock.calls.map(([url]) => url as string).filter((url) => url.startsWith('/feedback/events?'));

function renderSaved(route: string) {
  return renderWithProviders(
    <>
      <SavedEvents />
      <LocationProbe />
    </>,
    { route },
  );
}

beforeEach(() => {
  mockGet.mockReset();
  mockDelete.mockReset();
});

describe('SavedEvents', () => {
  it('renders bookmarked events by default', async () => {
    mockGet.mockImplementation((path: string) => {
      expect(path).toContain('signal=bookmark');
      return Promise.resolve(savedResponse([makeEvent({ id: 1, title: 'Jazz Night' })]));
    });

    renderWithProviders(<SavedEvents />, { route: '/saved' });

    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));
    expect(screen.getByText('Jazz Night')).toBeInTheDocument();
  });

  it('shows empty state when no events match', async () => {
    mockGet.mockResolvedValue(savedResponse([]));

    renderWithProviders(<SavedEvents />, { route: '/saved' });

    await waitFor(() => expect(screen.getByText('Nothing here yet')).toBeInTheDocument());
  });

  it('shows error state on failure', async () => {
    mockGet.mockRejectedValue(new Error('network'));

    renderWithProviders(<SavedEvents />, { route: '/saved' });

    await waitFor(() =>
      expect(screen.getByText('Failed to load saved events. Please refresh.')).toBeInTheDocument(),
    );
  });

  describe('paging', () => {
    it('pages at 24, mapping ?page to the request offset', async () => {
      mockSavedServer({ bookmark: range(1, 60) });

      renderSaved('/saved?page=2');

      await waitFor(() => expect(screen.getByText('Saved 25')).toBeInTheDocument());
      expect(screen.getByText('Saved 48')).toBeInTheDocument();
      expect(screen.queryByText('Saved 49')).not.toBeInTheDocument();
      expect(savedRequests()).toEqual(['/feedback/events?signal=bookmark&limit=24&offset=24&locale=en']);
    });

    it('shows the pager with the range label instead of Load more', async () => {
      mockSavedServer({ bookmark: range(1, 60) });

      const { container } = renderSaved('/saved');

      await waitFor(() => expect(screen.getByText('Saved 1')).toBeInTheDocument());
      const nav = screen.getByRole('navigation', { name: 'Pages' });
      expect(within(nav).getByRole('link', { name: 'Page 3' })).toHaveAttribute('href', '/saved?page=3');
      expect(container.textContent).toContain('1–24 of 60');
      expect(screen.queryByText('Load more')).not.toBeInTheDocument();
    });

    it('after a page change focuses the results heading and instant-scrolls to it', async () => {
      mockSavedServer({ bookmark: range(1, 60) });

      renderSaved('/saved');
      await waitFor(() => expect(screen.getByText('Saved 1')).toBeInTheDocument());
      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

      await waitFor(() => expect(screen.getByText('Saved 25')).toBeInTheDocument());
      await waitFor(() =>
        expect(document.activeElement).toBe(screen.getByRole('heading', { level: 2, name: 'Bookmarked' })),
      );
      expect(window.scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'instant' }));
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/saved?page=2');
    });

    it('marks the grid aria-busy while the previous page shows as placeholder data', async () => {
      let release: () => void = () => {};
      const page2 = new Promise<void>((resolve) => {
        release = resolve;
      });
      mockSavedServer({ bookmark: range(1, 60) });
      const serve = mockGet.getMockImplementation()!;
      mockGet.mockImplementation(async (path: string) => {
        if (path.includes('offset=24')) await page2;
        return serve(path);
      });

      renderSaved('/saved');
      await waitFor(() => expect(screen.getByText('Saved 1')).toBeInTheDocument());
      const grid = screen.getByRole('region', { name: 'Bookmarked' });
      expect(grid).toHaveAttribute('aria-busy', 'false');

      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));
      await waitFor(() => expect(grid).toHaveAttribute('aria-busy', 'true'));
      expect(screen.getByText('Saved 1')).toBeInTheDocument();

      release();
      await waitFor(() => expect(screen.getByText('Saved 25')).toBeInTheDocument());
      expect(screen.getByRole('region', { name: 'Bookmarked' })).toHaveAttribute('aria-busy', 'false');
    });
  });

  describe('signal tab in the URL', () => {
    it('reads a non-default tab and the page from the URL, so a refresh keeps both', async () => {
      mockSavedServer({ like: range(101, 160) });

      renderSaved('/saved?signal=like&page=3');

      await waitFor(() => expect(screen.getByText('Saved 149')).toBeInTheDocument());
      expect(savedRequests()).toEqual(['/feedback/events?signal=like&limit=24&offset=48&locale=en']);
      expect(screen.getByRole('button', { name: /Liked/ })).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('link', { name: 'Page 2' })).toHaveAttribute('href', '/saved?signal=like&page=2');
    });

    it('switching tabs writes the tab to the URL and starts again at page 1', async () => {
      mockSavedServer({ bookmark: range(1, 60), like: range(101, 110) });

      renderSaved('/saved?page=3');
      await waitFor(() => expect(screen.getByText('Saved 49')).toBeInTheDocument());

      await userEvent.click(screen.getByRole('button', { name: /Liked/ }));

      await waitFor(() => expect(screen.getByText('Saved 101')).toBeInTheDocument());
      expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/saved\?signal=like$/);
      expect(savedRequests().slice(-1)[0]).toBe('/feedback/events?signal=like&limit=24&offset=0&locale=en');
    });

    it('omits the default tab from the URL', async () => {
      mockSavedServer({ bookmark: range(1, 5), like: range(101, 105) });

      renderSaved('/saved?signal=like');
      await waitFor(() => expect(screen.getByText('Saved 101')).toBeInTheDocument());

      await userEvent.click(screen.getByRole('button', { name: /Bookmarked/ }));

      await waitFor(() => expect(screen.getByText('Saved 1')).toBeInTheDocument());
      expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/saved$/);
    });

    it('treats an unknown signal as the default tab', async () => {
      mockSavedServer({ bookmark: range(1, 5) });

      renderSaved('/saved?signal=nope');

      await waitFor(() => expect(screen.getByText('Saved 1')).toBeInTheDocument());
      expect(savedRequests()).toEqual(['/feedback/events?signal=bookmark&limit=24&offset=0&locale=en']);
    });
  });

  describe('unsaving', () => {
    it('unsaving a card mid-page pulls the next page\'s first event up into the gap', async () => {
      mockSavedServer({ bookmark: range(1, 60) });

      renderSaved('/saved?page=2');
      await waitFor(() => expect(screen.getByText('Saved 48')).toBeInTheDocument());
      expect(screen.queryByText('Saved 49')).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Unsave Saved 30' }));

      await waitFor(() => expect(screen.getByText('Saved 49')).toBeInTheDocument());
      expect(screen.queryByText('Saved 30')).not.toBeInTheDocument();
      expect(screen.getAllByTestId('event-card')).toHaveLength(24);
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/saved?page=2');
    });

    it('unsaving the last card on the last page lands on the new last page', async () => {
      mockSavedServer({ bookmark: range(1, 25) });

      renderSaved('/saved?page=2');
      await waitFor(() => expect(screen.getByText('Saved 25')).toBeInTheDocument());

      await userEvent.click(screen.getByRole('button', { name: 'Unsave Saved 25' }));

      await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/saved$/));
      await waitFor(() => expect(screen.getByText('Saved 1')).toBeInTheDocument());
      expect(screen.getByText('Saved 24')).toBeInTheDocument();
    });
  });
});
