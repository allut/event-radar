import { describe, it, expect, vi, afterEach } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import AuthVerify from './AuthVerify';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setSignedInHint: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  // Real ApiError (shared class, no network dependency); only api.* stubbed.
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

import { api } from '../../api/client';
import { setSignedInHint } from '../../lib/auth';
import { getThemePreference } from '../../lib/theme';
const mockGet = vi.mocked(api.get);
const mockPost = vi.mocked(api.post);
const mockPatch = vi.mocked(api.patch);
const mockSetSignedInHint = vi.mocked(setSignedInHint);

describe('AuthVerify', () => {
  afterEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('shows error when no token in URL', () => {
    renderWithProviders(<AuthVerify />, { route: '/auth/verify' });
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows verifying state initially when token present', () => {
    mockPost.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=abc' });
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('on success: POSTs the token in the body, calls setSignedInHint, and shows success state', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    mockGet.mockResolvedValueOnce({ has_personas: true, theme_preference: null });

    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=valid' });

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/auth/verify', { token: 'valid' }));
    await waitFor(() => expect(mockSetSignedInHint).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
  });

  it('seeds the account theme when local has an explicit override and the account has none', async () => {
    localStorage.setItem('theme_preference', 'dark');
    mockPost.mockResolvedValueOnce(undefined);
    mockGet.mockResolvedValueOnce({ has_personas: true, theme_preference: null });
    mockPatch.mockResolvedValueOnce(undefined);

    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=valid' });

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/users/me', { theme_preference: 'dark' }));
    // Local value is untouched — it's the source being seeded, not overwritten.
    expect(getThemePreference()).toBe('dark');
  });

  it('does not seed the account theme when local has no explicit override', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    mockGet.mockResolvedValueOnce({ has_personas: true, theme_preference: null });

    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=valid' });

    await waitFor(() => expect(mockSetSignedInHint).toHaveBeenCalled());
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('applies an existing non-null account theme locally instead of overwriting it', async () => {
    localStorage.setItem('theme_preference', 'dark');
    mockPost.mockResolvedValueOnce(undefined);
    mockGet.mockResolvedValueOnce({ has_personas: true, theme_preference: 'light' });

    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=valid' });

    await waitFor(() => expect(mockSetSignedInHint).toHaveBeenCalled());
    // Account value wins visually and is mirrored locally; no PATCH is sent
    // since the account already holds this preference.
    expect(getThemePreference()).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('strips the token from the address bar before verifying', () => {
    const replaceStateSpy = vi.spyOn(window.history, 'replaceState');
    mockPost.mockReturnValue(new Promise(() => undefined));

    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=valid' });

    expect(replaceStateSpy).toHaveBeenCalledWith({}, '', '/auth/verify');
    replaceStateSpy.mockRestore();
  });

  it('on verify failure: shows error state', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.UNAUTHORIZED, 'Link expired'));

    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=expired' });

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Link expired')).toBeInTheDocument();
  });
});
