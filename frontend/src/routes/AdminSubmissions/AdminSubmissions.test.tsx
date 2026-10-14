import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import { focusManager, QueryClient } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import AdminSubmissions from './AdminSubmissions';
import { LocationProbe, renderWithProviders } from '../../test/utils';
import { QUERY_KEYS } from '../../constants/api';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { adminApi, ApiError } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);

const sampleSubmissions = {
  total: 2,
  events: [
    {
      id: 1,
      title: 'Tallinn Jazz Night',
      description: 'Live jazz trio in the museum courtyard.',
      venue_name: 'Fotografiska Tallinn',
      url: 'https://fotografiska.ee/events/jazz-night',
      categories: ['music'],
      status: 'published',
      submitted_by_organizer_id: 14,
      created_at: '2026-08-25T05:00:00Z',
    },
    {
      id: 2,
      title: 'Kalamaja Street Food Market',
      description: null,
      venue_name: 'Kalamaja',
      url: null,
      categories: [],
      status: 'published',
      submitted_by_organizer_id: 22,
      created_at: '2026-08-25T02:00:00Z',
    },
  ],
};

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

function submission(id: number) {
  return { ...sampleSubmissions.events[1], id, title: `Submission ${id}` };
}

/** A fake server queue: GETs slice the live rows by the request offset, and
 * an approve/retract takes its row out, so a refetch pulls the next row up. */
function serveQueue(ids: number[]) {
  const live = [...ids];
  mockGet.mockImplementation(async (url: string) => {
    const params = new URL(url, 'http://x').searchParams;
    const limit = Number(params.get('limit'));
    const offset = Number(params.get('offset'));
    return {
      total: live.length,
      limit,
      offset,
      has_more: offset + limit < live.length,
      events: live.slice(offset, offset + limit).map(submission),
    } as never;
  });
  mockPost.mockImplementation(async (path: string) => {
    const id = Number(/submissions\/(\d+)\//.exec(path)?.[1]);
    live.splice(live.indexOf(id), 1);
    return { id, needs_review: false, note: 'ok' } as never;
  });
  return live;
}

const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, k) => from + k);

function rowButton(title: string): HTMLElement {
  return screen.getByRole('button', { name: new RegExp(`^${title}\\b`) });
}

function listRowTitles(): string[] {
  return screen
    .getAllByRole('button')
    .map((b) => /^Submission \d+/.exec(b.textContent ?? '')?.[0])
    .filter((t): t is string => t !== undefined);
}

async function approve(note = 'Looks good.') {
  await userEvent.type(screen.getByLabelText(/note/i), note);
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
}

function listGets(): number {
  return mockGet.mock.calls.filter(([url]) => String(url).startsWith('/admin/submissions?')).length;
}

describe('AdminSubmissions', () => {
  it('lists pending submissions and shows the first item\'s full context in the detail panel', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    expect(screen.getByText('Kalamaja Street Food Market')).toBeInTheDocument();
    expect(screen.getByText('Organizer #14', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Live jazz trio in the museum courtyard.')).toBeInTheDocument();
  });

  it('links the detail panel to the full event inspector', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    expect(screen.getByRole('link', { name: /Open full details/ })).toHaveAttribute('href', '/admin/events/1');
  });

  it('renders the description snippet as plain text, never as HTML markup (out of scope for #271)', async () => {
    mockGet.mockResolvedValueOnce({
      total: 1,
      events: [
        {
          ...sampleSubmissions.events[0],
          description: 'Doors at 8pm. <strong>Bring ID</strong> — 18+ only.',
        },
      ],
    });
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    const preview = screen.getByText(/Doors at 8pm\. <strong>Bring ID<\/strong> — 18\+ only\./);
    expect(preview.querySelector('strong')).not.toBeInTheDocument();
  });

  it('shows an empty state when there are no pending submissions', async () => {
    mockGet.mockResolvedValueOnce({ total: 0, events: [] });
    renderWithProviders(<AdminSubmissions />);
    await waitFor(() => expect(screen.getByText('No pending submissions.')).toBeInTheDocument());
  });

  it('switches the detail panel when a different row is selected', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    renderWithProviders(<AdminSubmissions />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /Kalamaja Street Food Market/ }));
    expect(screen.getByRole('heading', { name: 'Kalamaja Street Food Market' })).toBeInTheDocument();
    expect(screen.getByText('No description.')).toBeInTheDocument();
  });

  it('requires a note before approve/retract are enabled', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    renderWithProviders(<AdminSubmissions />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Retract' })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/note/i), 'Looks good.');
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
  });

  it('approves a submission with the typed note, then keeps it in the list greyed out and tagged', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    mockGet.mockResolvedValueOnce({ ...sampleSubmissions, total: 1, events: [sampleSubmissions.events[1]] });
    mockPost.mockResolvedValueOnce({ id: 1, needs_review: false, note: 'Looks good.' });
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/note/i), 'Looks good.');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/submissions/1/approve',
      { resolution_note: 'Looks good.' },
    ));
    expect(await screen.findByText(/Submission approved\./)).toBeInTheDocument();

    const list = screen.getAllByRole('button').filter((b) => within(b).queryByText('Tallinn Jazz Night'));
    expect(list[0]).toHaveTextContent('Approved');
  });

  it('retracts a submission with the typed note', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    mockGet.mockResolvedValueOnce({ ...sampleSubmissions, total: 1, events: [sampleSubmissions.events[1]] });
    mockPost.mockResolvedValueOnce({ id: 1, status: 'cancelled', note: 'Duplicate listing.' });
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/note/i), 'Duplicate listing.');
    await userEvent.click(screen.getByRole('button', { name: 'Retract' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/submissions/1/retract',
      { resolution_note: 'Duplicate listing.' },
    ));
    expect(await screen.findByText(/Submission retracted\./)).toBeInTheDocument();

    const list = screen.getAllByRole('button').filter((b) => within(b).queryByText('Tallinn Jazz Night'));
    expect(list[0]).toHaveTextContent('Retracted');
  });

  it('shows an error toast and leaves the submission actionable when approve fails', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    mockPost.mockRejectedValueOnce(new ApiError(429, 'Too many requests.'));
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/note/i), 'Looks good.');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));

    expect(await screen.findByText('Too many requests.')).toBeInTheDocument();
    expect(screen.queryByText(/Submission approved\./)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
  });
  it('requests 50 per page from ?page and shows the range label in place of Load more', async () => {
    serveQueue(range(1, 120));
    renderWithProviders(<AdminSubmissions />, { route: '/admin/submissions?page=2' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Submission 51' })).toBeInTheDocument());
    expect(mockGet).toHaveBeenCalledWith('/admin/submissions?limit=50&offset=50');
    expect(screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === '51–100 of 120')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Page 2' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('refetches the page and the counts when another admin already removed the submission', async () => {
    const live = serveQueue([1, 2, 3]);
    mockPost.mockImplementation(async () => {
      live.splice(live.indexOf(1), 1);
      throw new ApiError(404, 'Submission not found.');
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    queryClient.setQueryData([QUERY_KEYS.adminCounts], { submissions: 3 });
    renderWithProviders(<AdminSubmissions />, { queryClient });
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Submission 1' })).toBeInTheDocument());

    await approve();

    expect(await screen.findByText('Submission not found.')).toBeInTheDocument();
    await waitFor(() => expect(listRowTitles()).toEqual(['Submission 2', 'Submission 3']));
    expect(queryClient.getQueryState([QUERY_KEYS.adminCounts])?.isInvalidated).toBe(true);
  });

  it('marks the selected row aria-current="true"', async () => {
    serveQueue([1, 2]);
    renderWithProviders(<AdminSubmissions />);
    await waitFor(() => expect(rowButton('Submission 1')).toHaveAttribute('aria-current', 'true'));
    expect(rowButton('Submission 2')).not.toHaveAttribute('aria-current');

    await userEvent.click(rowButton('Submission 2'));
    expect(rowButton('Submission 2')).toHaveAttribute('aria-current', 'true');
    expect(rowButton('Submission 1')).not.toHaveAttribute('aria-current');
  });

  it('refetches the page once per action: tagged rows stay in place, pulled-up rows go at the bottom', async () => {
    serveQueue(range(1, 60));
    renderWithProviders(<AdminSubmissions />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Submission 1' })).toBeInTheDocument());
    expect(listGets()).toBe(1);

    await userEvent.click(rowButton('Submission 3'));
    await approve();

    await waitFor(() => expect(listRowTitles()).toHaveLength(51));
    expect(listGets()).toBe(2);
    expect(mockGet).toHaveBeenLastCalledWith('/admin/submissions?limit=50&offset=0');
    const titles = listRowTitles();
    expect(titles.slice(0, 4)).toEqual(['Submission 1', 'Submission 2', 'Submission 3', 'Submission 4']);
    expect(titles[50]).toBe('Submission 51');
    expect(rowButton('Submission 3')).toHaveTextContent('Approved');
    expect(rowButton('Submission 51')).not.toHaveTextContent('Approved');
    // Live rows only: 59 left, and the page shows the first 50 of them.
    expect(screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === '1–50 of 59')).toBeInTheDocument();
  });

  it('holds an emptied last page while its rows are tagged, with the no-items label and a working pager', async () => {
    serveQueue(range(1, 51));
    renderWithProviders(
      <>
        <AdminSubmissions />
        <LocationProbe />
      </>,
      { route: '/admin/submissions?page=2' },
    );
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Submission 51' })).toBeInTheDocument());

    await approve();

    expect(await screen.findByText('No items on this page · 50 total')).toBeInTheDocument();
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/admin/submissions?page=2');
    expect(rowButton('Submission 51')).toHaveTextContent('Approved');
    expect(screen.getByRole('link', { name: 'Page 1' })).toHaveAttribute('href', '/admin/submissions');
  });

  it('clamps to the new last page when the page empties for any other reason', async () => {
    const live = serveQueue(range(1, 51));
    renderWithProviders(
      <>
        <AdminSubmissions />
        <LocationProbe />
      </>,
      { route: '/admin/submissions?page=2' },
    );
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Submission 51' })).toBeInTheDocument());

    // Another tab resolved the row; a refetch on window focus finds the page empty.
    live.splice(live.indexOf(51), 1);
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });

    await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/admin\/submissions$/));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Submission 1' })).toBeInTheDocument());
    act(() => focusManager.setFocused(undefined));
  });

  it('on a page change selects and focuses the first row, clears the tags and scrolls the list top into view on mobile', async () => {
    vi.mocked(window.matchMedia).mockImplementation(
      (query: string) => ({ matches: query.includes('max-width'), media: query }) as MediaQueryList,
    );
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    serveQueue(range(1, 120));
    renderWithProviders(<AdminSubmissions />, { route: '/admin/submissions' });
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Submission 1' })).toBeInTheDocument());
    await userEvent.click(rowButton('Submission 2'));
    await userEvent.click(screen.getByRole('button', { name: /Back to list/ }));
    await approve();
    await waitFor(() => expect(listGets()).toBe(2));

    await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

    // 119 live rows after the approve: page 2 starts at Submission 52.
    await waitFor(() => expect(rowButton('Submission 52')).toHaveFocus());
    expect(rowButton('Submission 52')).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('heading', { name: 'Submission 52' })).toBeInTheDocument();
    expect(screen.queryByText('Approved')).not.toBeInTheDocument();
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start', behavior: 'auto' });
  });
});
