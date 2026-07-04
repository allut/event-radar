import { describe, it, expect, vi } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import AuthVerify from './AuthVerify';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setToken: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: {
    get: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
      this.name = 'ApiError';
    }
  },
}));

import { api } from '../../api/client';
import { setToken } from '../../lib/auth';
const mockGet = vi.mocked(api.get);
const mockSetToken = vi.mocked(setToken);

describe('AuthVerify', () => {
  it('shows error when no token in URL', () => {
    renderWithProviders(<AuthVerify />, { route: '/auth/verify' });
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows verifying state initially when token present', () => {
    mockGet.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=abc' });
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('on success: calls setToken and shows success state', async () => {
    mockGet
      .mockResolvedValueOnce({ session_token: 'tok123' })
      .mockResolvedValueOnce({ has_personas: true });

    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=valid' });

    await waitFor(() => expect(mockSetToken).toHaveBeenCalledWith('tok123'));
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
  });

  it('strips the token from the address bar before verifying', () => {
    const replaceStateSpy = vi.spyOn(window.history, 'replaceState');
    mockGet.mockReturnValue(new Promise(() => undefined));

    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=valid' });

    expect(replaceStateSpy).toHaveBeenCalledWith({}, '', '/auth/verify');
    replaceStateSpy.mockRestore();
  });

  it('on verify failure: shows error state', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockGet.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.UNAUTHORIZED, 'Link expired'));

    renderWithProviders(<AuthVerify />, { route: '/auth/verify?token=expired' });

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Link expired')).toBeInTheDocument();
  });
});
