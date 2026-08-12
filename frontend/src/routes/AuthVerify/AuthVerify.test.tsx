import { describe, it, expect, vi } from 'vitest';
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
  },
}));

import { api } from '../../api/client';
import { setSignedInHint } from '../../lib/auth';
const mockGet = vi.mocked(api.get);
const mockPost = vi.mocked(api.post);
const mockSetSignedInHint = vi.mocked(setSignedInHint);

describe('AuthVerify', () => {
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
    mockGet.mockResolvedValueOnce({ has_personas: true });

    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=valid' });

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/auth/verify', { token: 'valid' }));
    await waitFor(() => expect(mockSetSignedInHint).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
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
