import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrganizerProfileNudge from './OrganizerProfileNudge';
import { renderWithProviders } from '../../test/utils';
import { ORGANIZER_PROFILE_NUDGE_DISMISSED_KEY } from '../../constants';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn() },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);

beforeEach(() => {
  mockGet.mockReset();
  localStorage.clear();
});

describe('OrganizerProfileNudge', () => {
  it('shows the nudge when the organizer has no display name set', async () => {
    mockGet.mockResolvedValueOnce({ name: null });
    renderWithProviders(<OrganizerProfileNudge locale="en" />);
    await waitFor(() => expect(screen.getByText(/set a display name/i)).toBeInTheDocument());
    expect(screen.getByRole('link', { name: /add your name/i })).toBeInTheDocument();
  });

  it('renders nothing when the organizer already has a display name', async () => {
    mockGet.mockResolvedValueOnce({ name: 'Tallinn Live' });
    renderWithProviders(<OrganizerProfileNudge locale="en" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(screen.queryByText(/set a display name/i)).not.toBeInTheDocument();
  });

  it('hides after dismiss and persists the dismissal', async () => {
    mockGet.mockResolvedValueOnce({ name: null });
    renderWithProviders(<OrganizerProfileNudge locale="en" />);
    await waitFor(() => expect(screen.getByText(/set a display name/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }));

    expect(screen.queryByText(/set a display name/i)).not.toBeInTheDocument();
    expect(localStorage.getItem(ORGANIZER_PROFILE_NUDGE_DISMISSED_KEY)).not.toBeNull();
  });

  it('stays hidden on a later mount once dismissal is persisted', async () => {
    localStorage.setItem(ORGANIZER_PROFILE_NUDGE_DISMISSED_KEY, '1');
    mockGet.mockResolvedValueOnce({ name: null });
    renderWithProviders(<OrganizerProfileNudge locale="en" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(screen.queryByText(/set a display name/i)).not.toBeInTheDocument();
  });
});
