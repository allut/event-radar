import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrganizerClaims from './OrganizerClaims';
import { LocationProbe, renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn() },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);

function ownClaim(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    kind: 'publisher',
    status: 'pending',
    verification_mechanism: 'fienta_token',
    dormant: false,
    publisher_name: null,
    event_id: id,
    event_title: `Claim ${id}`,
    created_at: '2026-08-01T00:00:00Z',
    resolved_at: null,
    ...overrides,
  };
}

/** Serves `total` own claims (ids 1..total), sliced by the request's
 * limit/offset, the way GET /organizer/claims pages them. `hold(offset)` may
 * return a promise that delays that page's response. */
function mockPagedClaims(total: number, hold?: (offset: number) => Promise<void> | undefined) {
  mockGet.mockImplementation(async (path: string) => {
    if (path.includes('/organizer/profile')) return { name: 'Test Organizer' };
    const params = new URL(path, 'http://x').searchParams;
    const limit = Number(params.get('limit'));
    const offset = Number(params.get('offset'));
    await hold?.(offset);
    const claims = [];
    for (let id = offset + 1; id <= Math.min(offset + limit, total); id++) claims.push(ownClaim(id));
    return { claims, total, pending_count: total, limit, offset, has_more: offset + claims.length < total };
  });
}

const claimRequests = () =>
  mockGet.mock.calls.map(([url]) => url).filter((url) => url.startsWith('/organizer/claims?'));

beforeEach(() => {
  mockGet.mockReset();
});

describe('OrganizerClaims', () => {
  it('pages Your claims at 20, mapping ?page to the request offset', async () => {
    mockPagedClaims(47);
    renderWithProviders(<OrganizerClaims />, { route: '/organizer/claims?page=2' });

    await waitFor(() => expect(screen.getByText('Claim 21')).toBeInTheDocument());
    expect(screen.getByText('Claim 40')).toBeInTheDocument();
    expect(screen.queryByText('Claim 41')).not.toBeInTheDocument();
    expect(claimRequests()).toEqual(['/organizer/claims?limit=20&offset=20&locale=en']);
  });

  it('shows each claim with its status and shortcuts', async () => {
    mockGet.mockImplementation(async (path: string) => {
      if (path.includes('/organizer/profile')) return { name: 'Test Organizer' };
      return {
        claims: [
          ownClaim(1, {
            status: 'approved',
            publisher_name: 'Jazzkaar',
            event_title: 'Jazzkaar Festival Night',
            resolved_at: '2026-08-02T00:00:00Z',
          }),
          ownClaim(2, { kind: 'series', status: 'declined', event_id: null, event_title: null }),
        ],
        total: 2,
        pending_count: 0,
        limit: 20,
        offset: 0,
        has_more: false,
      };
    });
    renderWithProviders(<OrganizerClaims />, { route: '/organizer/claims' });

    await waitFor(() => expect(screen.getByText('Jazzkaar Festival Night')).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Your claims' })).toBeInTheDocument();
    expect(screen.getByText('Granted')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Edit event' })).toHaveAttribute('href', '/organizer/claims/1/edit');
    expect(screen.getByRole('link', { name: 'View all events' })).toHaveAttribute('href', '/organizer/claims/1/events');
    expect(screen.getByText('Declined')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View status' })).toHaveAttribute('href', '/organizer/claims/2/pending');
  });

  it('shows the pager under the list with the range label', async () => {
    mockPagedClaims(47);
    const { container } = renderWithProviders(<OrganizerClaims />, { route: '/organizer/claims' });
    await waitFor(() => expect(screen.getByText('Claim 1')).toBeInTheDocument());

    const list = screen.getByRole('list', { name: 'Your claims' });
    const nav = screen.getByRole('navigation', { name: 'Pages' });
    expect(list.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(nav).getByRole('link', { name: 'Page 3' })).toHaveAttribute('href', '/organizer/claims?page=3');
    expect(container.textContent).toContain('1–20 of 47');
  });

  it('after a page change focuses the Your claims heading and instant-scrolls to it', async () => {
    mockPagedClaims(47);
    renderWithProviders(
      <>
        <OrganizerClaims />
        <LocationProbe />
      </>,
      { route: '/organizer/claims' },
    );
    await waitFor(() => expect(screen.getByText('Claim 1')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

    await waitFor(() => expect(screen.getByText('Claim 21')).toBeInTheDocument());
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole('heading', { level: 1, name: 'Your claims' })),
    );
    expect(window.scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'instant' }));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/organizer/claims?page=2');
  });

  it('marks the list aria-busy while the previous page shows as placeholder data', async () => {
    let release: () => void = () => {};
    const page2 = new Promise<void>((resolve) => {
      release = resolve;
    });
    mockPagedClaims(47, (offset) => (offset === 20 ? page2 : undefined));
    renderWithProviders(<OrganizerClaims />, { route: '/organizer/claims' });
    await waitFor(() => expect(screen.getByText('Claim 1')).toBeInTheDocument());
    const list = screen.getByRole('list', { name: 'Your claims' });
    expect(list).toHaveAttribute('aria-busy', 'false');

    await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

    await waitFor(() => expect(list).toHaveAttribute('aria-busy', 'true'));
    expect(screen.getByText('Claim 1')).toBeInTheDocument();
    release();
    await waitFor(() => expect(screen.getByText('Claim 21')).toBeInTheDocument());
    expect(screen.getByRole('list', { name: 'Your claims' })).toHaveAttribute('aria-busy', 'false');
  });

  it('shows an empty state and no pager when the organizer has no claims', async () => {
    mockPagedClaims(0);
    renderWithProviders(<OrganizerClaims />, { route: '/organizer/claims' });

    await waitFor(() => expect(screen.getByText('No claims yet')).toBeInTheDocument());
    expect(screen.queryByRole('navigation', { name: 'Pages' })).not.toBeInTheDocument();
  });
});
