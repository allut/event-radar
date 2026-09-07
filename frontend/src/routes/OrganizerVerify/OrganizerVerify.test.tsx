import { describe, it, expect, vi, afterEach } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import OrganizerVerify from './OrganizerVerify';
import { renderWithProviders } from '../../test/utils';
import { getThemePreference } from '../../lib/theme';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
}));

vi.mock('../../lib/organizerAuth', () => ({
  setOrganizerSignedInHint: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: {
    post: vi.fn(),
    get: vi.fn(() => Promise.resolve({ theme_preference: null })),
    patch: vi.fn(() => Promise.resolve()),
  },
}));

import { organizerApi } from '../../api/client';
import { setOrganizerSignedInHint } from '../../lib/organizerAuth';
const mockPost = vi.mocked(organizerApi.post);
const mockGet = vi.mocked(organizerApi.get);
const mockPatch = vi.mocked(organizerApi.patch);
const mockSetOrganizerSignedInHint = vi.mocked(setOrganizerSignedInHint);

describe('OrganizerVerify', () => {
  afterEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ theme_preference: null });
  });

  it('shows error when no token in URL', () => {
    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify' });
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows verifying state initially when token present', () => {
    mockPost.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify?token=abc' });
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('on success: calls setOrganizerSignedInHint (not the consumer hint) with the organizer flag', async () => {
    mockPost.mockResolvedValueOnce(undefined);

    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify?token=valid' });

    await waitFor(() => expect(mockSetOrganizerSignedInHint).toHaveBeenCalled());
    expect(mockPost).toHaveBeenCalledWith('/organizer/auth/verify', { token: 'valid' });
  });

  it('seeds the organizer account theme when local has an explicit override and the account has none', async () => {
    localStorage.setItem('theme_preference', 'dark');
    mockPost.mockResolvedValueOnce(undefined);
    mockGet.mockResolvedValueOnce({ theme_preference: null });

    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify?token=valid' });

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/organizer/profile', { theme_preference: 'dark' }));
    // Local value is untouched — it's the source being seeded, not overwritten.
    expect(getThemePreference()).toBe('dark');
  });

  it('does not seed the organizer account theme when local has no explicit override', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    mockGet.mockResolvedValueOnce({ theme_preference: null });

    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify?token=valid' });

    await waitFor(() => expect(mockSetOrganizerSignedInHint).toHaveBeenCalled());
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('applies an existing non-null organizer account theme locally instead of overwriting it', async () => {
    localStorage.setItem('theme_preference', 'dark');
    mockPost.mockResolvedValueOnce(undefined);
    mockGet.mockResolvedValueOnce({ theme_preference: 'light' });

    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify?token=valid' });

    await waitFor(() => expect(mockSetOrganizerSignedInHint).toHaveBeenCalled());
    // Account value wins visually and is mirrored locally; no PATCH is sent
    // since the account already holds this preference.
    expect(getThemePreference()).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('on verify failure: shows error state', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Link expired'));

    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify?token=expired' });

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Link expired')).toBeInTheDocument();
  });
});
