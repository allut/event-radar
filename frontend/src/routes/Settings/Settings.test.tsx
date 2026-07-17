import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Settings from './Settings';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
  clearToken: vi.fn(),
  beginLogout: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  // Real ApiError (shared class, no network dependency); only api.* stubbed.
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from '../../api/client';
const mockGet = vi.mocked(api.get);
const mockPatch = vi.mocked(api.patch);
const mockPost = vi.mocked(api.post);

const settingsData = {
  id: 1,
  email: 'user@example.com',
  locale: 'en',
  home_city: 'Tallinn',
  email_digest_opt_in: true,
  created_at: '2024-01-01T00:00:00Z',
  personas: [
    { slug: 'culture_buff', display_name_en: 'Culture Buff', weight: 1.0 },
    { slug: 'weekend_hobbyist', display_name_en: 'Weekend Hobbyist', weight: 0.4 },
  ],
};

describe('Settings', () => {
  it('shows loading state initially', () => {
    mockGet.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<Settings />);
    expect(screen.getByLabelText(/loading/i)).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    mockGet.mockRejectedValueOnce(new Error('network'));
    renderWithProviders(<Settings />);
    await waitFor(() => expect(screen.getByText(/Failed to load settings/i)).toBeInTheDocument());
  });

  it('shows email on success', async () => {
    mockGet.mockResolvedValueOnce(settingsData);
    renderWithProviders(<Settings />);
    await waitFor(() => expect(screen.getByText('user@example.com')).toBeInTheDocument());
  });

  it('shows primary persona', async () => {
    mockGet.mockResolvedValueOnce(settingsData);
    renderWithProviders(<Settings />);
    await waitFor(() => expect(screen.getByText('Culture Buff')).toBeInTheDocument());
  });

  it('shows secondary persona', async () => {
    mockGet.mockResolvedValueOnce(settingsData);
    renderWithProviders(<Settings />);
    await waitFor(() => expect(screen.getByText('Weekend Hobbyist')).toBeInTheDocument());
  });

  it('digest toggle patch on click', async () => {
    mockGet.mockResolvedValueOnce(settingsData);
    mockPatch.mockResolvedValueOnce({ ...settingsData, email_digest_opt_in: false });
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /digest/i }));
    await userEvent.click(screen.getByRole('button', { name: /digest/i }));
    expect(mockPatch).toHaveBeenCalledWith('/users/me', { email_digest_opt_in: false });
  });

  it('shows saved toast on successful patch', async () => {
    mockGet.mockResolvedValueOnce(settingsData);
    mockPatch.mockResolvedValueOnce({ ...settingsData, email_digest_opt_in: false });
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /digest/i }));
    await userEvent.click(screen.getByRole('button', { name: /digest/i }));
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
  });

  it('toast auto-clears after delay', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    mockGet.mockResolvedValueOnce(settingsData);
    mockPatch.mockResolvedValueOnce({ ...settingsData, email_digest_opt_in: false });
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /digest/i }));
    await user.click(screen.getByRole('button', { name: /digest/i }));
    await waitFor(() => screen.getByRole('status'));
    vi.runAllTimers();
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
    vi.useRealTimers();
  });

  it('logout-all calls api.post /auth/logout-all', async () => {
    mockGet.mockResolvedValueOnce(settingsData);
    mockPost.mockResolvedValueOnce({ detail: 'Logged out' });
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /log out everywhere/i }));
    await userEvent.click(screen.getByRole('button', { name: /log out everywhere/i }));
    expect(mockPost).toHaveBeenCalledWith('/auth/logout-all');
  });

  it('logout-all shows success message then clears token after delay', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    mockGet.mockResolvedValueOnce(settingsData);
    mockPost.mockResolvedValueOnce({ detail: 'Logged out' });
    const { clearToken } = await import('../../lib/auth');
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /log out everywhere/i }));
    await user.click(screen.getByRole('button', { name: /log out everywhere/i }));
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
    vi.runAllTimers();
    await waitFor(() => expect(clearToken).toHaveBeenCalled());
    vi.useRealTimers();
  });
});
