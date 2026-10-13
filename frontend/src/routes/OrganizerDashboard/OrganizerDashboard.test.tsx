import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrganizerDashboard from './OrganizerDashboard';
import { LocationProbe, renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn(), delete: vi.fn() },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockDelete = vi.mocked(organizerApi.delete);

const sampleEvents = {
  events: [
    { id: 1, slug: 'jazz-night', title: 'Jazz Night', starts_at: '2026-08-01T18:00:00Z', status: 'published', needs_review: true },
    { id: 2, slug: 'art-show', title: 'Art Show', starts_at: '2026-08-05T10:00:00Z', status: 'classified', needs_review: true },
  ],
  total: 2,
  limit: 24,
  offset: 0,
  has_more: false,
};

/** GET /organizer/claims?limit=1 as the dashboard's summary line reads it:
 * only `total` and `pending_count` matter. */
function claimsSummary(total: number, pending: number) {
  return { claims: [], total, pending_count: pending, limit: 1, offset: 0, has_more: total > 1 };
}

// OrganizerDashboard renders OrganizerProfileNudge, which fires its own
// organizerApi.get('/organizer/profile') call — route by path instead of
// queueing positional mockResolvedValueOnce values, since the two calls can
// resolve in either order. Defaults to a name set, so the nudge banner
// (covered by OrganizerProfileNudge.test.tsx) doesn't interfere with these
// event-list assertions unless a test overrides it.
// ClaimEventPicker (#414) also fires its own organizerApi.get calls
// (suggestions on mount) — defaults to an empty list so it doesn't leak
// duplicate event titles into these event-list assertions unless a test
// overrides it.
function mockOrganizerGet(
  eventsResponse: unknown,
  profileResponse: unknown = { name: 'Test Organizer' },
  claimSuggestionsResponse: unknown = { events: [] },
  ownClaimsResponse: unknown = claimsSummary(0, 0),
) {
  mockGet.mockImplementation((path: string) => {
    if (path.includes('/organizer/profile')) return Promise.resolve(profileResponse);
    if (path.includes('/organizer/claims/suggestions')) return Promise.resolve(claimSuggestionsResponse);
    if (path.startsWith('/organizer/claims?')) return Promise.resolve(ownClaimsResponse);
    return Promise.resolve(eventsResponse);
  });
}

/** Serves `total` own events (ids 1..total), sliced by the request's
 * limit/offset, the way GET /organizer/events pages them. */
function ownEventsPage(url: string, total: number) {
  const params = new URL(url, 'http://x').searchParams;
  const limit = Number(params.get('limit'));
  const offset = Number(params.get('offset'));
  const events = [];
  for (let id = offset + 1; id <= Math.min(offset + limit, total); id++) {
    events.push({
      id,
      slug: `event-${id}`,
      title: `Event ${id}`,
      starts_at: '2026-08-01T18:00:00Z',
      status: 'published',
      needs_review: false,
    });
  }
  return { events, total, limit, offset, has_more: offset + events.length < total };
}

/** Like mockOrganizerGet, but Your events is a paged list of `total` rows.
 * `hold(offset)` may return a promise that delays that page's response. */
function mockPagedEvents(total: number, hold?: (offset: number) => Promise<void> | undefined) {
  mockGet.mockImplementation(async (path: string) => {
    if (path.includes('/organizer/profile')) return { name: 'Test Organizer' };
    if (path.includes('/organizer/claims/suggestions')) return { events: [] };
    if (path.startsWith('/organizer/claims?')) return claimsSummary(0, 0);
    const offset = Number(new URL(path, 'http://x').searchParams.get('offset'));
    await hold?.(offset);
    return ownEventsPage(path, total);
  });
}

const eventRequests = () =>
  mockGet.mock.calls.map(([url]) => url).filter((url) => url.startsWith('/organizer/events?'));

beforeEach(() => {
  mockGet.mockReset();
  mockDelete.mockReset();
});

describe('OrganizerDashboard', () => {
  it('lists the organizer\'s own events with status and review badges', async () => {
    mockOrganizerGet(sampleEvents);
    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    expect(screen.getByText('Art Show')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/organizer/events?limit='));
  });

  it('sends locale= on the events request (#454)', async () => {
    mockOrganizerGet(sampleEvents);
    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());

    expect(mockGet).toHaveBeenCalledWith(expect.stringMatching(/\/organizer\/events\?.*[?&]locale=en/));
  });

  it('shows an empty state when there are no events', async () => {
    mockOrganizerGet({ events: [], total: 0, limit: 24, offset: 0, has_more: false });
    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText(/no events yet/i)).toBeInTheDocument());
  });

  it('deletes an event after confirmation', async () => {
    mockOrganizerGet(sampleEvents);
    mockDelete.mockResolvedValueOnce({ id: 1, status: 'cancelled' });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());

    const deleteButtons = screen.getAllByRole('button', { name: /delete/i });
    await userEvent.click(deleteButtons[0]);

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('/organizer/events/1'));
    confirmSpy.mockRestore();
  });

  it('does not delete when the confirmation is declined', async () => {
    mockOrganizerGet(sampleEvents);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());

    const deleteButtons = screen.getAllByRole('button', { name: /delete/i });
    await userEvent.click(deleteButtons[0]);

    expect(mockDelete).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('summarises the organizer\'s claims with a link to Your claims', async () => {
    mockOrganizerGet(sampleEvents, undefined, undefined, claimsSummary(37, 3));
    renderWithProviders(<OrganizerDashboard />);

    const summary = await screen.findByRole('region', { name: 'Your claims' });
    expect(summary).toHaveTextContent('You have 37 claims (3 pending)');
    expect(within(summary).getByRole('link', { name: /View/ })).toHaveAttribute('href', '/organizer/claims');
    // Only the counts are needed: one row, and no claim rows on the dashboard.
    expect(mockGet).toHaveBeenCalledWith('/organizer/claims?limit=1');
    expect(screen.queryByRole('list', { name: 'Your claims' })).not.toBeInTheDocument();
  });

  it('leaves the pending part out when no claim is pending, and uses the singular for one', async () => {
    mockOrganizerGet(sampleEvents, undefined, undefined, claimsSummary(1, 0));
    renderWithProviders(<OrganizerDashboard />);

    const summary = await screen.findByRole('region', { name: 'Your claims' });
    expect(summary).toHaveTextContent('You have 1 claim');
    expect(summary).not.toHaveTextContent('pending');
  });

  it('hides the claims summary when the organizer has no claims', async () => {
    mockOrganizerGet(sampleEvents, undefined, undefined, claimsSummary(0, 0));
    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    expect(screen.queryByRole('region', { name: 'Your claims' })).not.toBeInTheDocument();
    expect(screen.queryByText(/You have/)).not.toBeInTheDocument();
  });

  describe('Your events paging', () => {
    it('pages Your events at 24, mapping ?page to the request offset', async () => {
      mockPagedEvents(58);
      renderWithProviders(<OrganizerDashboard />, { route: '/organizer/dashboard?page=2' });

      await waitFor(() => expect(screen.getByText('Event 25')).toBeInTheDocument());
      expect(screen.getByText('Event 48')).toBeInTheDocument();
      expect(screen.queryByText('Event 49')).not.toBeInTheDocument();
      expect(eventRequests()).toEqual(['/organizer/events?limit=24&offset=24&locale=en']);
    });

    it('shows the pager under the list with the range label', async () => {
      mockPagedEvents(58);
      const { container } = renderWithProviders(<OrganizerDashboard />, {
        route: '/organizer/dashboard',
      });
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());

      const list = screen.getByRole('list', { name: 'Your events' });
      const nav = screen.getByRole('navigation', { name: 'Pages' });
      expect(list.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(within(nav).getByRole('link', { name: 'Page 3' })).toHaveAttribute(
        'href',
        '/organizer/dashboard?page=3',
      );
      expect(container.textContent).toContain('1–24 of 58');
    });

    it('after a page change focuses the Your events heading and instant-scrolls to it', async () => {
      mockPagedEvents(58);
      renderWithProviders(
        <>
          <OrganizerDashboard />
          <LocationProbe />
        </>,
        { route: '/organizer/dashboard' },
      );
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());

      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

      await waitFor(() => expect(screen.getByText('Event 25')).toBeInTheDocument());
      await waitFor(() =>
        expect(document.activeElement).toBe(screen.getByRole('heading', { level: 1, name: 'Your events' })),
      );
      expect(window.scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'instant' }));
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/organizer/dashboard?page=2');
    });

    it('marks the list aria-busy while the previous page shows as placeholder data', async () => {
      let release: () => void = () => {};
      const page2 = new Promise<void>((resolve) => {
        release = resolve;
      });
      mockPagedEvents(58, (offset) => (offset === 24 ? page2 : undefined));
      renderWithProviders(<OrganizerDashboard />, { route: '/organizer/dashboard' });
      await waitFor(() => expect(screen.getByText('Event 1')).toBeInTheDocument());
      const list = screen.getByRole('list', { name: 'Your events' });
      expect(list).toHaveAttribute('aria-busy', 'false');

      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

      await waitFor(() => expect(list).toHaveAttribute('aria-busy', 'true'));
      expect(screen.getByText('Event 1')).toBeInTheDocument();
      release();
      await waitFor(() => expect(screen.getByText('Event 25')).toBeInTheDocument());
      expect(screen.getByRole('list', { name: 'Your events' })).toHaveAttribute('aria-busy', 'false');
    });

    it('keeps the current page after deleting an event (cancelled rows stay listed)', async () => {
      mockPagedEvents(58);
      mockDelete.mockResolvedValueOnce({ id: 30, status: 'cancelled' });
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
      renderWithProviders(<OrganizerDashboard />, { route: '/organizer/dashboard?page=2' });
      await waitFor(() => expect(screen.getByText('Event 25')).toBeInTheDocument());

      await userEvent.click(screen.getAllByRole('button', { name: /delete/i })[0]);

      await waitFor(() => expect(eventRequests()).toHaveLength(2));
      expect(eventRequests()[1]).toBe('/organizer/events?limit=24&offset=24&locale=en');
      confirmSpy.mockRestore();
    });
  });
});
