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
    delete: vi.fn(),
  },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPatch = vi.mocked(organizerApi.patch);
const mockPost = vi.mocked(organizerApi.post);
const mockDelete = vi.mocked(organizerApi.delete);

const sampleProfile = {
  id: 5, email: 'organizer@example.com', locale: 'en', verified: true, name: null, google_linked: false,
};

beforeEach(() => {
  mockGet.mockReset();
  mockPatch.mockReset();
  mockPost.mockReset().mockResolvedValue({});
  mockDelete.mockReset();
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
    // mockResolvedValue (not Once) — the save now triggers an invalidate +
    // refetch of the profile query rather than writing the PATCH response
    // straight into the cache, so GET fires a second time after the PATCH.
    mockGet.mockResolvedValue(sampleProfile);
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

  it('shows not-linked state and no unlink button when Google is not linked', async () => {
    mockGet.mockResolvedValueOnce(sampleProfile);
    renderWithProviders(<OrganizerSettings />);
    await waitFor(() => expect(screen.getByText('Google account not linked')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /unlink google/i })).not.toBeInTheDocument();
  });

  it('shows linked state and an unlink button when Google is linked', async () => {
    mockGet.mockResolvedValueOnce({ ...sampleProfile, google_linked: true });
    renderWithProviders(<OrganizerSettings />);
    await waitFor(() => expect(screen.getByText('Google account linked')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /unlink google/i })).toBeInTheDocument();
  });

  it('unlink calls DELETE /organizer/profile/identities/google and flips to not-linked', async () => {
    // First GET (initial load) returns linked; the invalidate-triggered
    // refetch after unlink hits this queued not-linked response.
    mockGet.mockResolvedValueOnce({ ...sampleProfile, google_linked: true });
    mockGet.mockResolvedValueOnce({ ...sampleProfile, google_linked: false });
    mockDelete.mockResolvedValueOnce({ detail: 'Identity unlinked.' });
    renderWithProviders(<OrganizerSettings />);
    await waitFor(() => screen.getByRole('button', { name: /unlink google/i }));

    await userEvent.click(screen.getByRole('button', { name: /unlink google/i }));

    expect(mockDelete).toHaveBeenCalledWith('/organizer/profile/identities/google');
    await waitFor(() => expect(screen.getAllByText('Google account not linked').length).toBeGreaterThan(0));
  });
});
