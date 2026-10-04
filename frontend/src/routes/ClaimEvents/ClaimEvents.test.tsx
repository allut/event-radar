import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import ClaimEvents from './ClaimEvents';
import { renderWithProviders } from '../../test/utils';

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

function renderList() {
  return renderWithProviders(<ClaimEvents />, {
    route: '/en/organizer/claims/7/events',
    pathPattern: '/:locale/organizer/claims/:id/events',
  });
}

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

  it('shows a load-more control when the server reports more pages', async () => {
    mockGet.mockResolvedValueOnce(page({ has_more: true, total: 3 }));
    renderList();

    await waitFor(() => expect(screen.getByText('Load more')).toBeInTheDocument());
  });
});
