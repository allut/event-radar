import { describe, it, expect, vi } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import OrganizerVerify from './OrganizerVerify';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
}));

vi.mock('../../lib/organizerAuth', () => ({
  setOrganizerToken: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: {
    get: vi.fn(),
  },
}));

import { organizerApi } from '../../api/client';
import { setOrganizerToken } from '../../lib/organizerAuth';
const mockGet = vi.mocked(organizerApi.get);
const mockSetOrganizerToken = vi.mocked(setOrganizerToken);

describe('OrganizerVerify', () => {
  it('shows error when no token in URL', () => {
    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify' });
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows verifying state initially when token present', () => {
    mockGet.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify?token=abc' });
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('on success: calls setOrganizerToken (not the consumer setToken) with the organizer flag', async () => {
    mockGet.mockResolvedValueOnce({ session_token: 'org-tok' });

    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify?token=valid' });

    await waitFor(() => expect(mockSetOrganizerToken).toHaveBeenCalledWith('org-tok'));
    expect(mockGet).toHaveBeenCalledWith('/organizer/auth/verify?token=valid');
  });

  it('on verify failure: shows error state', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockGet.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Link expired'));

    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify?token=expired' });

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Link expired')).toBeInTheDocument();
  });
});
