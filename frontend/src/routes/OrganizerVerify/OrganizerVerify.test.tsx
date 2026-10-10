import { t } from '../../i18n';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import OrganizerVerify from './OrganizerVerify';
import { renderWithProviders } from '../../test/utils';

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
  },
}));

import { organizerApi } from '../../api/client';
import { setOrganizerSignedInHint } from '../../lib/organizerAuth';
const mockPost = vi.mocked(organizerApi.post);
const mockSetOrganizerSignedInHint = vi.mocked(setOrganizerSignedInHint);

describe('OrganizerVerify', () => {
  afterEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
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

  it('on verify failure: shows error state', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Link expired'));

    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify?token=expired' });

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Link expired')).toBeInTheDocument();
  });
});

describe('OrganizerVerify locale', () => {
  // The page speaks the URL's language (like the Footer under it, #497) —
  // never the saved preference, mocked to 'en' above.
  it('renders in the URL prefix\'s language', () => {
    renderWithProviders(<OrganizerVerify />, { route: '/ru/organizer/verify' });
    expect(screen.getAllByText(t('no_token', 'ru')).length).toBeGreaterThan(0);
  });

  it('renders Estonian on a bare path', () => {
    renderWithProviders(<OrganizerVerify />, { route: '/organizer/verify' });
    expect(screen.getAllByText(t('no_token', 'et')).length).toBeGreaterThan(0);
  });
});
