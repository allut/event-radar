import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminDedup from './AdminDedup';
import { LocationProbe, renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { adminApi } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);

function page(groups: unknown[], offset: number, hasMore: boolean, total: number) {
  return {
    group_count: groups.length,
    event_count: groups.reduce((n: number, g) => n + (g as { events: unknown[] }).events.length, 0),
    total,
    limit: 50,
    offset,
    has_more: hasMore,
    groups,
  };
}

const groupA = {
  dedup_group_id: 482,
  events: [
    { id: 1, title: 'Jazzkaar Opening Night', starts_at: '2026-09-04T19:00:00+03:00', venue: 'Kultuurikatel', status: 'published', url: 'https://x.ee/1', is_explicit: false },
    { id: 2, title: 'Jazzkaar Opening Night — Piletilevi', starts_at: '2026-09-04T19:00:00+03:00', venue: 'Kultuurikatel', status: 'classified', url: null, is_explicit: false },
  ],
};

const groupB = {
  dedup_group_id: 490,
  events: [
    { id: 3, title: 'Late Night Cabaret', starts_at: '2026-09-06T22:00:00+03:00', venue: 'Von Krahl', status: 'published', url: null, is_explicit: true },
  ],
};

beforeEach(() => {
  mockGet.mockReset();
});

describe('AdminDedup', () => {
  it('lists dedup groups with their member events', async () => {
    mockGet.mockResolvedValueOnce(page([groupA, groupB], 0, false, 2));
    renderWithProviders(<AdminDedup />);

    await waitFor(() => expect(screen.getByText('Group #482')).toBeInTheDocument());
    expect(screen.getByText('Group #490')).toBeInTheDocument();
    expect(screen.getByText('Jazzkaar Opening Night')).toBeInTheDocument();
    expect(screen.getByText('Jazzkaar Opening Night — Piletilevi')).toBeInTheDocument();
    expect(screen.getByText('explicit')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith('/admin/dedup/groups?limit=50&offset=0');
  });

  it('shows an empty state when there are no dedup groups', async () => {
    mockGet.mockResolvedValueOnce(page([], 0, false, 0));
    renderWithProviders(<AdminDedup />);
    await waitFor(() => expect(screen.getByText('No dedup groups')).toBeInTheDocument());
  });

  it('maps ?page to the request offset at 50 groups per page', async () => {
    mockGet.mockResolvedValueOnce(page([groupB], 100, false, 101));
    renderWithProviders(<AdminDedup />, { route: '/admin/dedup?page=3' });

    await waitFor(() => expect(screen.getByText('Group #490')).toBeInTheDocument());
    expect(mockGet).toHaveBeenCalledWith('/admin/dedup/groups?limit=50&offset=100');
    expect(screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === '101–101 of 101')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Page 3' })).toHaveAttribute('aria-current', 'page');
  });

  it('pages with the numbered pager, resetting scroll and focusing the first group', async () => {
    mockGet.mockResolvedValueOnce(page([groupA], 0, true, 51));
    renderWithProviders(
      <>
        <AdminDedup />
        <LocationProbe />
      </>,
      { route: '/admin/dedup' },
    );
    await waitFor(() => expect(screen.getByText('Group #482')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();

    mockGet.mockResolvedValueOnce(page([groupB], 50, false, 51));
    await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

    await waitFor(() => expect(screen.getByTestId('dedup-group-490')).toHaveFocus());
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/admin/dedup?page=2');
    expect(mockGet).toHaveBeenLastCalledWith('/admin/dedup/groups?limit=50&offset=50');
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'auto' });
    expect(screen.getByRole('status')).toHaveTextContent('Page 2 of 2. Items 51 to 51 of 51.');
  });

  it('renders the desktop-only gate message alongside the real content', async () => {
    mockGet.mockResolvedValueOnce(page([groupA], 0, false, 1));
    renderWithProviders(<AdminDedup />);
    await waitFor(() => expect(screen.getByText('Group #482')).toBeInTheDocument());
    expect(
      screen.getByText('Come back at a desk — the dedup console needs more room than this screen.'),
    ).toBeInTheDocument();
  });
});
