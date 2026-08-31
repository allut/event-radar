import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrganizerSettings from './OrganizerSettings';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: {
    get: vi.fn(),
    patch: vi.fn(),
    // Default-resolved so useOrganizerLogout's fire-and-forget
    // POST /organizer/auth/logout call (fired alongside every logout-all's
    // follow-up handleLogout) never hits an unmocked call with no return value.
    post: vi.fn().mockResolvedValue({}),
  },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPatch = vi.mocked(organizerApi.patch);
const mockPost = vi.mocked(organizerApi.post);

const sampleProfile = { id: 5, email: 'organizer@example.com', locale: 'en', verified: true, name: null };

beforeEach(() => {
  mockGet.mockReset();
  mockPatch.mockReset();
  mockPost.mockReset().mockResolvedValue({});
});

describe('OrganizerSettings', () => {
  it('shows the account email', async () => {
    mockGet.mockResolvedValueOnce(sampleProfile);
    renderWithProviders(<OrganizerSettings />);
    await waitFor(() => expect(screen.getByText('organizer@example.com')).toBeInTheDocument());
  });

  it('renders the display-name field, empty when unset', async () => {
    mockGet.mockResolvedValueOnce(sampleProfile);
    renderWithProviders(<OrganizerSettings />);
    await waitFor(() => expect(screen.getByLabelText(/display name/i)).toBeInTheDocument());
    expect(screen.getByLabelText(/display name/i)).toHaveValue('');
  });

  it('prefills the existing display name', async () => {
    mockGet.mockResolvedValueOnce({ ...sampleProfile, name: 'Tallinn Live' });
    renderWithProviders(<OrganizerSettings />);
    await waitFor(() => expect(screen.getByLabelText(/display name/i)).toHaveValue('Tallinn Live'));
  });

  it('saves the entered name and shows a success toast', async () => {
    mockGet.mockResolvedValueOnce(sampleProfile);
    mockPatch.mockResolvedValueOnce({ ...sampleProfile, name: 'Tallinn Live' });
    renderWithProviders(<OrganizerSettings />);
    await waitFor(() => expect(screen.getByLabelText(/display name/i)).toBeInTheDocument());

    await userEvent.type(screen.getByLabelText(/display name/i), 'Tallinn Live');
    await userEvent.click(screen.getByRole('button', { name: /save name/i }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/organizer/profile', { name: 'Tallinn Live' }));
    expect(await screen.findByText(/name saved/i)).toBeInTheDocument();
  });

  it('shows an error toast when saving fails', async () => {
    mockGet.mockResolvedValueOnce(sampleProfile);
    mockPatch.mockRejectedValueOnce(new Error('boom'));
    renderWithProviders(<OrganizerSettings />);
    await waitFor(() => expect(screen.getByLabelText(/display name/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /save name/i }));

    expect(await screen.findByText(/something went wrong|generic_error|error/i)).toBeInTheDocument();
  });

  it('logout-all calls organizerApi.post /organizer/auth/logout-all', async () => {
    mockGet.mockResolvedValueOnce(sampleProfile);
    mockPost.mockResolvedValueOnce({ detail: 'Logged out' });
    renderWithProviders(<OrganizerSettings />);
    await waitFor(() => screen.getByRole('button', { name: /log out everywhere/i }));
    await userEvent.click(screen.getByRole('button', { name: /log out everywhere/i }));
    expect(mockPost).toHaveBeenCalledWith('/organizer/auth/logout-all');
  });

  it('logout-all shows a success message after clicking', async () => {
    mockGet.mockResolvedValueOnce(sampleProfile);
    mockPost.mockResolvedValueOnce({ detail: 'Logged out' });
    renderWithProviders(<OrganizerSettings />);
    await waitFor(() => screen.getByRole('button', { name: /log out everywhere/i }));
    await userEvent.click(screen.getByRole('button', { name: /log out everywhere/i }));
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
  });
});
