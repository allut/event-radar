import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import { focusManager, QueryClient } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { useNavigate } from 'react-router-dom';
import AdminReports from './AdminReports';
import { LocationProbe, renderWithProviders } from '../../test/utils';
import { QUERY_KEYS } from '../../constants/api';
import splitViewStyles from '../../components/AdminQueueSplitView/AdminQueueSplitView.module.css';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { adminApi, ApiError } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);

const sampleReports = {
  total: 2,
  limit: 50,
  offset: 0,
  has_more: false,
  report_not_found: false,
  events: [
    {
      event_id: 1,
      title: 'MEEDIUM',
      status: 'published',
      venue: 'Von Krahli teater',
      submitted_by_organizer_id: null,
      report_count: 1,
      reasons: ['hateful_or_violent'],
      has_illegal_allegation: true,
      reports: [
        {
          reason: 'hateful_or_violent',
          detail: 'Contains language that may violate local law.',
          is_illegal_allegation: true,
          created_at: '2026-08-25T07:00:00Z',
        },
      ],
      oldest_open_report_at: '2026-08-25T07:00:00Z',
    },
    {
      event_id: 2,
      title: 'Öömaaeg',
      status: 'published',
      venue: 'Von Krahli teater',
      submitted_by_organizer_id: null,
      report_count: 2,
      reasons: ['spam_or_scam', 'misleading_info'],
      has_illegal_allegation: false,
      reports: [
        { reason: 'spam_or_scam', detail: null, is_illegal_allegation: false, created_at: '2026-08-24T10:00:00Z' },
        { reason: 'misleading_info', detail: 'Price mismatch.', is_illegal_allegation: false, created_at: '2026-08-23T10:00:00Z' },
      ],
      oldest_open_report_at: '2026-08-23T10:00:00Z',
    },
  ],
};

const afterResolvingFirst = { ...sampleReports, total: 1, events: [sampleReports.events[1]] };

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('AdminReports', () => {
  it('lists open reports and shows the first item\'s full context in the detail panel', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    expect(screen.getByText('Öömaaeg')).toBeInTheDocument();
    expect(screen.getByText('Illegal content alleged')).toBeInTheDocument();
    expect(screen.getByText('Contains language that may violate local law.')).toBeInTheDocument();
  });

  it('links the detail panel to the full event inspector', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    expect(screen.getByRole('link', { name: /Open full details/ })).toHaveAttribute('href', '/admin/events/1');
  });

  it('shows an empty state when there are no open reports', async () => {
    mockGet.mockResolvedValueOnce({ ...sampleReports, total: 0, events: [] });
    renderWithProviders(<AdminReports />);
    await waitFor(() => expect(screen.getByText('No open reports.')).toBeInTheDocument());
  });

  it('switches the detail panel when a different row is selected', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    renderWithProviders(<AdminReports />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    expect(screen.queryByText('Price mismatch.')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Öömaaeg/ }));
    expect(screen.getByRole('heading', { name: 'Öömaaeg' })).toBeInTheDocument();
    expect(screen.getByText('Price mismatch.')).toBeInTheDocument();
  });

  it('auto-opens the detail panel matching a ?report= deep link', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    renderWithProviders(<AdminReports />, { route: '/admin/reports?report=2' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Öömaaeg' })).toBeInTheDocument());
    expect(screen.getByText('Price mismatch.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Öömaaeg' }).closest(`.${splitViewStyles.detail}`))
      .toHaveClass(splitViewStyles.detailShownMobile);
  });

  it('falls back to the first item when the ?report= id has no matching open report', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    renderWithProviders(<AdminReports />, { route: '/admin/reports?report=999' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
  });

  it('does not mis-treat a missing ?report= param as event id 0', async () => {
    mockGet.mockResolvedValueOnce({
      ...sampleReports,
      total: 1,
      events: [{ ...sampleReports.events[0], event_id: 0 }],
    });
    renderWithProviders(<AdminReports />, { route: '/admin/reports' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    expect(screen.getByRole('heading', { name: 'MEEDIUM' }).closest(`.${splitViewStyles.detail}`))
      .not.toHaveClass(splitViewStyles.detailShownMobile);
  });

  it('requires a note before resolve/takedown are enabled', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    renderWithProviders(<AdminReports />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Resolve' })).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Take down event' })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Reviewed, all clear.');
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeEnabled();
  });

  it('resolves a report with the typed note, then keeps it in the list greyed out and tagged', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    mockGet.mockResolvedValueOnce(afterResolvingFirst);
    mockPost.mockResolvedValueOnce({ event_id: 1, resolved_count: 1 });
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Confirmed, edited the listing.');
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/reports/1/resolve',
      { resolution_note: 'Confirmed, edited the listing.' },
    ));
    expect(await screen.findByText(/Resolved\. Reporters notified\./)).toBeInTheDocument();

    const list = screen.getAllByRole('button').filter((b) => within(b).queryByText('MEEDIUM'));
    expect(list[0]).toHaveTextContent('Resolved');
  });

  it('takes an event down with the typed note', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    mockGet.mockResolvedValueOnce(afterResolvingFirst);
    mockPost.mockResolvedValueOnce({ event_id: 1, status: 'cancelled', resolved_count: 1 });
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Illegal content confirmed, taken down.');
    await userEvent.click(screen.getByRole('button', { name: 'Take down event' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/reports/1/takedown',
      { resolution_note: 'Illegal content confirmed, taken down.' },
    ));
    expect(await screen.findByText(/Event taken down\. Reporters notified\./)).toBeInTheDocument();
  });

  it('replaces the stale pre-takedown status once the event is actually taken down', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    mockGet.mockResolvedValueOnce(afterResolvingFirst);
    mockPost.mockResolvedValueOnce({ event_id: 1, status: 'cancelled', resolved_count: 1 });
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    expect(screen.getByText(/status: published/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Illegal content confirmed, taken down.');
    await userEvent.click(screen.getByRole('button', { name: 'Take down event' }));

    await screen.findByText(/Event taken down\. Reporters notified\./);
    expect(screen.getByText(/status: cancelled/)).toBeInTheDocument();
    expect(screen.queryByText(/status: published/)).not.toBeInTheDocument();
  });

  it('shows an error toast and leaves the report actionable when resolve fails', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    mockPost.mockRejectedValueOnce(new ApiError(429, 'Too many requests.'));
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Confirmed, edited the listing.');
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));

    expect(await screen.findByText('Too many requests.')).toBeInTheDocument();
    expect(screen.queryByText(/Resolved\. Reporters notified\./)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeEnabled();
  });

  describe('numbered pager', () => {
    function report(id: number) {
      return { ...sampleReports.events[1], event_id: id, title: `R#${id}#` };
    }

    /** A fake server: GETs slice the open reports by offset; `report=<id>`
     * with the row open returns the page holding it, without it page 1 and
     * report_not_found. Resolving a row takes it out. */
    function serveQueue(ids: number[]) {
      const open = [...ids];
      mockGet.mockImplementation(async (url: string) => {
        const params = new URL(url, 'http://x').searchParams;
        const limit = Number(params.get('limit'));
        let offset = Number(params.get('offset'));
        let notFound = false;
        if (params.has('report')) {
          const at = open.indexOf(Number(params.get('report')));
          notFound = at === -1;
          offset = notFound ? 0 : Math.floor(at / limit) * limit;
        }
        return {
          total: open.length,
          limit,
          offset,
          has_more: offset + limit < open.length,
          report_not_found: notFound,
          events: open.slice(offset, offset + limit).map(report),
        } as never;
      });
      mockPost.mockImplementation(async (path: string) => {
        const id = Number(/reports\/(\d+)\//.exec(path)?.[1]);
        open.splice(open.indexOf(id), 1);
        return { event_id: id, resolved_count: 1 } as never;
      });
      return open;
    }

    const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, k) => from + k);
    const rowButton = (title: string) => screen.getByRole('button', { name: new RegExp(`^${title}`) });
    const listRowTitles = () =>
      screen
        .getAllByRole('button')
        .map((b) => /^R#\d+#/.exec(b.textContent ?? '')?.[0])
        .filter((t): t is string => t !== undefined);
    const listGets = () => mockGet.mock.calls.filter(([url]) => String(url).startsWith('/admin/reports?')).length;

    async function resolve(note = 'All clear.') {
      await userEvent.type(screen.getByLabelText(/resolution note/i), note);
      await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    }

    it('requests 50 per page from ?page and shows the range label in place of Load more', async () => {
      serveQueue(range(1, 120));
      renderWithProviders(<AdminReports />, { route: '/admin/reports?page=2' });

      await waitFor(() => expect(screen.getByRole('heading', { name: 'R#51#' })).toBeInTheDocument());
      expect(mockGet).toHaveBeenCalledWith('/admin/reports?limit=50&offset=50');
      expect(screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === '51–100 of 120')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Page 2' })).toHaveAttribute('aria-current', 'page');
      expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
    });

    it('sends report to the server only when the URL has report and no page', async () => {
      serveQueue(range(1, 120));
      renderWithProviders(<AdminReports />, { route: '/admin/reports?page=2&report=60' });

      await waitFor(() => expect(screen.getByRole('heading', { name: 'R#60#' })).toBeInTheDocument());
      expect(mockGet).toHaveBeenCalledTimes(1);
      expect(mockGet).toHaveBeenCalledWith('/admin/reports?limit=50&offset=50');
    });

    it('lands a deep link on the page holding the report, selected, with a silent URL sync', async () => {
      serveQueue(range(1, 120));
      renderWithProviders(
        <>
          <AdminReports />
          <LocationProbe />
        </>,
        { route: '/admin/reports?report=110' },
      );

      await waitFor(() => expect(screen.getByRole('heading', { name: 'R#110#' })).toBeInTheDocument());
      expect(mockGet).toHaveBeenCalledWith('/admin/reports?limit=50&offset=0&report=110');
      await waitFor(() =>
        expect(screen.getByTestId('location-probe')).toHaveTextContent('/admin/reports?report=110&page=3'),
      );
      expect(rowButton('R#110#')).toHaveAttribute('aria-current', 'true');
      expect(screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === '101–120 of 120')).toBeInTheDocument();
      // The sync is a silent replace: no live-region announcement, no focus move.
      expect(screen.getByRole('status')).toBeEmptyDOMElement();
      expect(rowButton('R#110#')).not.toHaveFocus();
    });

    it('keeps ?report=<id> on page 1 for a row located there, and the page links drop it', async () => {
      serveQueue(range(1, 120));
      renderWithProviders(
        <>
          <AdminReports />
          <LocationProbe />
        </>,
        { route: '/admin/reports?report=7' },
      );

      await waitFor(() => expect(rowButton('R#7#')).toHaveAttribute('aria-current', 'true'));
      expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/admin\/reports\?report=7$/);
      expect(screen.getByRole('link', { name: 'Page 2' })).toHaveAttribute('href', '/admin/reports?page=2');
    });

    it('locates a page-1 deep link once: a later refetch stays on page 1 even if the report moved down', async () => {
      const open = serveQueue(range(1, 120));
      renderWithProviders(
        <>
          <AdminReports />
          <LocationProbe />
        </>,
        { route: '/admin/reports?report=7' },
      );
      await waitFor(() => expect(rowButton('R#7#')).toHaveAttribute('aria-current', 'true'));
      // 50 newer, higher-ranked reports push #7 onto page 2 server-side.
      open.unshift(...range(1001, 1050));

      await userEvent.click(rowButton('R#1#'));
      await resolve();

      await waitFor(() => expect(listGets()).toBe(2));
      expect(mockGet).toHaveBeenLastCalledWith('/admin/reports?limit=50&offset=0');
      await waitFor(() => expect(rowButton('R#1#')).toHaveTextContent('Resolved'));
      expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/admin\/reports\?report=7$/);
    });

    it.each([
      ['fresh', 30_000],
      ['stale', 0],
    ])('does not re-locate a page-1 deep link after a remount with a %s cache', async (_label, staleTime) => {
      const open = serveQueue(range(1, 120));
      function Detail() {
        const navigate = useNavigate();
        return <button type="button" onClick={() => navigate(-1)}>Go back</button>;
      }
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, staleTime }, mutations: { retry: false } },
      });
      renderWithProviders(null, {
        route: '/admin/reports?report=7',
        queryClient,
        routes: [
          { path: '/admin/reports', element: <><AdminReports /><LocationProbe /></> },
          { path: '/admin/events/:id', element: <><Detail /><LocationProbe /></> },
        ],
      });
      await waitFor(() => expect(rowButton('R#7#')).toHaveAttribute('aria-current', 'true'));
      await userEvent.click(screen.getByRole('link', { name: /Open full details/ }));
      await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent('/admin/events/7'));
      await userEvent.click(screen.getByRole('button', { name: 'Go back' }));
      await waitFor(() => expect(rowButton('R#7#')).toBeInTheDocument());
      // 50 newer, higher-ranked reports push #7 onto page 2 server-side.
      open.unshift(...range(1001, 1050));

      await userEvent.click(rowButton('R#1#'));
      await resolve();

      await waitFor(() => expect(rowButton('R#1#')).toHaveTextContent('Resolved'));
      expect(mockGet.mock.calls.slice(1).map(([url]) => url)).not.toContainEqual(expect.stringContaining('report='));
      expect(screen.getByTestId('location-probe')).not.toHaveTextContent('page=2');
    });

    it('does not re-locate a page-1 deep link on Back after its locate cache was collected while mounted', async () => {
      const open = serveQueue(range(1, 120));
      function BackButton() {
        const navigate = useNavigate();
        return <button type="button" onClick={() => navigate(-1)}>Go back</button>;
      }
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, staleTime: 30_000, gcTime: 50 }, mutations: { retry: false } },
      });
      renderWithProviders(null, {
        route: '/admin/reports?report=7',
        queryClient,
        routes: [{ path: '/admin/reports', element: <><AdminReports /><LocationProbe /><BackButton /></> }],
      });
      await waitFor(() => expect(rowButton('R#7#')).toHaveAttribute('aria-current', 'true'));
      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));
      await waitFor(() => expect(rowButton('R#51#')).toBeInTheDocument());
      await waitFor(() =>
        expect(queryClient.getQueryData([QUERY_KEYS.adminReports, 'locate', 7, 1])).toBeUndefined(),
      );
      // 50 newer, higher-ranked reports push #7 onto page 2 server-side.
      open.unshift(...range(1001, 1050));

      await userEvent.click(screen.getByRole('button', { name: 'Go back' }));

      await waitFor(() => expect(rowButton('R#1001#')).toBeInTheDocument());
      expect(mockGet.mock.calls.slice(1).map(([url]) => url)).not.toContainEqual(expect.stringContaining('report='));
      expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/admin\/reports\?report=7$/);
    });

    it('opens the mobile detail panel for the located row', async () => {
      serveQueue(range(1, 120));
      renderWithProviders(<AdminReports />, { route: '/admin/reports?report=110' });

      const title = await screen.findByRole('heading', { name: 'R#110#' });
      expect(title.closest(`.${splitViewStyles.detail}`)).toHaveClass(splitViewStyles.detailShownMobile);
    });

    it('shows the already-resolved notice on page 1 when the report is no longer open', async () => {
      serveQueue(range(1, 120));
      renderWithProviders(<AdminReports />, { route: '/admin/reports?report=999' });

      const notice = (await screen.findByText(/was already resolved/)).closest('p') as HTMLElement;
      expect(notice).toHaveTextContent('Report #999 was already resolved. Showing the start of the queue.');
      expect(within(notice).getByRole('link', { name: 'Open event #999' })).toHaveAttribute('href', '/admin/events/999');
      expect(screen.getByRole('heading', { name: 'R#1#' })).toBeInTheDocument();
      expect(rowButton('R#1#')).toHaveAttribute('aria-current', 'true');
    });

    it('does not show the notice when the report is open', async () => {
      serveQueue(range(1, 20));
      renderWithProviders(<AdminReports />, { route: '/admin/reports?report=5' });

      await waitFor(() => expect(rowButton('R#5#')).toHaveAttribute('aria-current', 'true'));
      expect(screen.queryByText(/was already resolved/)).not.toBeInTheDocument();
    });

    it('does not claim the report was already resolved after this screen resolved it', async () => {
      serveQueue(range(1, 20));
      renderWithProviders(<AdminReports />, { route: '/admin/reports?report=5' });
      await waitFor(() => expect(rowButton('R#5#')).toHaveAttribute('aria-current', 'true'));

      await resolve();

      await waitFor(() => expect(listGets()).toBe(2));
      expect(rowButton('R#5#')).toHaveTextContent('Resolved');
      expect(screen.queryByText(/was already resolved/)).not.toBeInTheDocument();
    });

    it('refetches the page and marks the counts and plain pages stale when the event is gone (404)', async () => {
      const open = serveQueue([1, 2, 3]);
      mockPost.mockImplementation(async () => {
        open.splice(open.indexOf(1), 1);
        throw new ApiError(404, 'Event not found.');
      });
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
      queryClient.setQueryData([QUERY_KEYS.adminCounts], { reports: 3 });
      queryClient.setQueryData([QUERY_KEYS.adminReports, 2], { total: 3, offset: 50, events: [] });
      // A deep link: the page is served from the locate key.
      renderWithProviders(<AdminReports />, { route: '/admin/reports?report=2', queryClient });
      await waitFor(() => expect(rowButton('R#2#')).toHaveAttribute('aria-current', 'true'));

      await userEvent.click(rowButton('R#1#'));
      await resolve();

      expect(await screen.findByText('Event not found.')).toBeInTheDocument();
      await waitFor(() => expect(listRowTitles()).toEqual(['R#2#', 'R#3#']));
      expect(queryClient.getQueryState([QUERY_KEYS.adminCounts])?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState([QUERY_KEYS.adminReports, 2])?.isInvalidated).toBe(true);
    });

    it('refetches the page once per action: tagged rows stay in place, pulled-up rows go at the bottom', async () => {
      serveQueue(range(1, 60));
      renderWithProviders(<AdminReports />);
      await waitFor(() => expect(screen.getByRole('heading', { name: 'R#1#' })).toBeInTheDocument());
      expect(listGets()).toBe(1);

      await userEvent.click(rowButton('R#3#'));
      await resolve();

      await waitFor(() => expect(listRowTitles()).toHaveLength(51));
      expect(listGets()).toBe(2);
      const titles = listRowTitles();
      expect(titles.slice(0, 4)).toEqual(['R#1#', 'R#2#', 'R#3#', 'R#4#']);
      expect(titles[50]).toBe('R#51#');
      expect(rowButton('R#3#')).toHaveTextContent('Resolved');
      expect(screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === '1–50 of 59')).toBeInTheDocument();
    });

    it('holds an emptied last page while its rows are tagged', async () => {
      serveQueue(range(1, 51));
      renderWithProviders(
        <>
          <AdminReports />
          <LocationProbe />
        </>,
        { route: '/admin/reports?page=2' },
      );
      await waitFor(() => expect(screen.getByRole('heading', { name: 'R#51#' })).toBeInTheDocument());

      await resolve();

      expect(await screen.findByText('No items on this page · 50 total')).toBeInTheDocument();
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/admin/reports?page=2');
      expect(rowButton('R#51#')).toHaveTextContent('Resolved');
    });

    it('clamps to the new last page when the page empties for any other reason', async () => {
      const open = serveQueue(range(1, 51));
      renderWithProviders(
        <>
          <AdminReports />
          <LocationProbe />
        </>,
        { route: '/admin/reports?page=2' },
      );
      await waitFor(() => expect(screen.getByRole('heading', { name: 'R#51#' })).toBeInTheDocument());

      open.splice(open.indexOf(51), 1);
      act(() => {
        focusManager.setFocused(false);
        focusManager.setFocused(true);
      });

      await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/admin\/reports$/));
      await waitFor(() => expect(screen.getByRole('heading', { name: 'R#1#' })).toBeInTheDocument());
      act(() => focusManager.setFocused(undefined));
    });

    it('on a page change selects and focuses the first row, drops report from the URL and clears the tags', async () => {
      serveQueue(range(1, 120));
      renderWithProviders(
        <>
          <AdminReports />
          <LocationProbe />
        </>,
        { route: '/admin/reports?report=7' },
      );
      await waitFor(() => expect(rowButton('R#7#')).toHaveAttribute('aria-current', 'true'));
      await resolve();
      await waitFor(() => expect(listGets()).toBe(2));

      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

      // 119 open after the resolve: page 2 starts at Report 52.
      await waitFor(() => expect(rowButton('R#52#')).toHaveFocus());
      expect(rowButton('R#52#')).toHaveAttribute('aria-current', 'true');
      expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/admin\/reports\?page=2$/);
      expect(screen.queryByText('Resolved')).not.toBeInTheDocument();
    });
  });
});
