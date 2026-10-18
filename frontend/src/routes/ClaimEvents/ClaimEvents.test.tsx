import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ClaimEvents from './ClaimEvents';
import { LocationProbe, renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn() },
}));

vi.mock('../../hooks/useOrganizerLogout', () => ({
  useOrganizerLogout: () => vi.fn(),
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);

function page(overrides: Record<string, unknown> = {}) {
  return {
    total: 2,
    limit: 20,
    offset: 0,
    has_more: false,
    events: [
      { id: 1, title: 'Jazzkaar Late Night', starts_at: '2026-10-03T20:00:00+03:00', status: 'published' },
      { id: 2, title: 'Winter Chamber Series', starts_at: '2026-10-24T19:30:00+03:00', status: 'classified' },
    ],
    ...overrides,
  };
}

function renderList(search = '') {
  return renderWithProviders(
    <>
      <ClaimEvents />
      <LocationProbe />
    </>,
    {
      route: `/en/organizer/claims/7/events${search}`,
      pathPattern: '/:locale/organizer/claims/:id/events',
    },
  );
}

/** Serves `total` covered events (ids 1..total), sliced by the request's
 * limit/offset the way GET /organizer/claims/{id}/events pages them.
 * `hold(offset)` may return a promise that delays that page's response. */
function mockPagedEvents(total: number, hold?: (offset: number) => Promise<void> | undefined) {
  mockGet.mockImplementation(async (path: string) => {
    const params = new URL(path, 'http://x').searchParams;
    const limit = Number(params.get('limit'));
    const offset = Number(params.get('offset'));
    await hold?.(offset);
    const events = [];
    for (let id = offset + 1; id <= Math.min(offset + limit, total); id++) {
      events.push({ id, title: `Event ${id}`, starts_at: '2026-10-03T20:00:00+03:00', status: 'published' });
    }
    return { total, limit, offset, has_more: offset + events.length < total, events };
  });
}

const requests = () => mockGet.mock.calls.map(([url]) => url);

beforeEach(() => {
  mockGet.mockReset();
});

describe('ClaimEvents (#436)', () => {
  it('renders every event the claim covers with its status', async () => {
    mockGet.mockResolvedValueOnce(page());
    renderList();

    await waitFor(() => expect(screen.getByText('Jazzkaar Late Night')).toBeInTheDocument());
    expect(screen.getByText('Winter Chamber Series')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/organizer/claims/7/events'));
  });

  it('sends locale= on the request so a language switch refetches (#454)', async () => {
    mockGet.mockResolvedValueOnce(page());
    renderList();

    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(mockGet).toHaveBeenCalledWith(expect.stringMatching(/[?&]locale=/));
  });

  it('links each row to the editor with its own event_id (#437)', async () => {
    mockGet.mockResolvedValueOnce(page());
    renderList();

    await waitFor(() => expect(screen.getByText('Jazzkaar Late Night')).toBeInTheDocument());
    const rowLink = screen.getByText('Jazzkaar Late Night').closest('a');
    expect(rowLink).toHaveAttribute('href', '/organizer/claims/7/edit?event_id=1');
    const otherRowLink = screen.getByText('Winter Chamber Series').closest('a');
    expect(otherRowLink).toHaveAttribute('href', '/organizer/claims/7/edit?event_id=2');
  });

  it('shows the empty state when the claim covers no events', async () => {
    mockGet.mockResolvedValueOnce(page({ total: 0, events: [] }));
    renderList();

    await waitFor(() => expect(screen.getByText('No events yet')).toBeInTheDocument());
  });

  describe('paging (#558)', () => {
    it('pages at 20, mapping ?page to the request offset', async () => {
      mockPagedEvents(45);
      renderList('?page=2');

      await waitFor(() => expect(screen.getByText('Event 21')).toBeInTheDocument());
      expect(screen.getByText('Event 40')).toBeInTheDocument();
      expect(screen.queryByText('Event 41')).not.toBeInTheDocument();
      expect(requests()).toEqual(['/organizer/claims/7/events?limit=20&offset=20&locale=en']);
    });

    it('shows the pager under the list with the range label instead of Load more', async () => {
      mockPagedEvents(45);
      const { container } = renderList();
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());

      const list = screen.getByRole('list', { name: 'Events this claim covers' });
      const nav = screen.getByRole('navigation', { name: 'Pages' });
      expect(list.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(within(nav).getByRole('link', { name: 'Page 3' })).toHaveAttribute(
        'href',
        '/en/organizer/claims/7/events?page=3',
      );
      expect(container.textContent).toContain('1–20 of 45');
      expect(screen.queryByText('Load more')).not.toBeInTheDocument();
    });

    it('after a page change focuses the heading and instant-scrolls to it', async () => {
      mockPagedEvents(45);
      renderList();
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());

      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

      await waitFor(() => expect(screen.getByText('Event 21')).toBeInTheDocument());
      await waitFor(() =>
        expect(document.activeElement).toBe(screen.getByRole('heading', { level: 1, name: 'Events this claim covers' })),
      );
      expect(window.scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'instant' }));
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/organizer/claims/7/events?page=2');
    });

    it('marks the list aria-busy while the previous page shows as placeholder data', async () => {
      let release: () => void = () => {};
      const page2 = new Promise<void>((resolve) => {
        release = resolve;
      });
      mockPagedEvents(45, (offset) => (offset === 20 ? page2 : undefined));
      renderList();
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());
      const list = screen.getByRole('list', { name: 'Events this claim covers' });
      expect(list).toHaveAttribute('aria-busy', 'false');

      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

      await waitFor(() => expect(list).toHaveAttribute('aria-busy', 'true'));
      expect(screen.getByText('Event 1')).toBeInTheDocument();
      release();
      await waitFor(() => expect(screen.getByText('Event 21')).toBeInTheDocument());
      expect(screen.getByRole('list', { name: 'Events this claim covers' })).toHaveAttribute('aria-busy', 'false');
    });

    it('hides the page links but keeps the range label when everything fits on one page', async () => {
      mockGet.mockResolvedValueOnce(page());
      const { container } = renderList();

      await waitFor(() => expect(screen.getByText('Jazzkaar Late Night')).toBeInTheDocument());
      expect(container.textContent).toContain('1–2 of 2');
      expect(screen.queryByRole('link', { name: 'Page 1' })).not.toBeInTheDocument();
    });
  });
});

describe('ClaimEvents Promotions row action (#614)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  const promoPage = () =>
    page({
      events: [
        { id: 1, title: 'Jazzkaar Late Night', starts_at: '2026-10-03T20:00:00+03:00', status: 'published', promotion: { promotable: true, badge: null } },
        { id: 2, title: 'Winter Chamber Series', starts_at: '2026-10-24T19:30:00+03:00', status: 'published', promotion: { promotable: false, badge: 'live' } },
      ],
    });

  it('shows Promote on a promotable row and the status badge on a promoted one, keeping the row link', async () => {
    mockGet.mockResolvedValueOnce(promoPage());
    renderList();

    expect(await screen.findByRole('link', { name: 'Promote Jazzkaar Late Night' })).toHaveAttribute(
      'href',
      '/en/organizer/promotions/new?event_id=1',
    );
    expect(screen.getByRole('link', { name: 'Live: Winter Chamber Series. Open Promotions.' })).toHaveAttribute(
      'href',
      '/en/organizer/promotions?event=2',
    );
    expect(screen.getByText('Jazzkaar Late Night').closest('a')).toHaveAttribute('href', '/organizer/claims/7/edit?event_id=1');
  });

  it('renders no Promotions action when rows carry no promotion key', async () => {
    mockGet.mockResolvedValueOnce(page());
    renderList();

    await screen.findByText('Jazzkaar Late Night');
    expect(screen.queryByRole('link', { name: /^Promote / })).not.toBeInTheDocument();
  });
});
