import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrganizerDashboard from './OrganizerDashboard';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
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
  limit: 24,
  offset: 0,
};

beforeEach(() => {
  mockGet.mockReset();
  mockDelete.mockReset();
});

describe('OrganizerDashboard', () => {
  it('lists the organizer\'s own events with status and review badges', async () => {
    mockGet.mockResolvedValueOnce(sampleEvents);
    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    expect(screen.getByText('Art Show')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/organizer/events?limit='));
  });

  it('shows an empty state when there are no events', async () => {
    mockGet.mockResolvedValueOnce({ events: [], limit: 24, offset: 0 });
    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText(/no events yet/i)).toBeInTheDocument());
  });

  it('deletes an event after confirmation', async () => {
    mockGet.mockResolvedValue(sampleEvents);
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
    mockGet.mockResolvedValue(sampleEvents);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());

    const deleteButtons = screen.getAllByRole('button', { name: /delete/i });
    await userEvent.click(deleteButtons[0]);

    expect(mockDelete).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
