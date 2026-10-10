import { t } from '../../i18n';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import OrganizerClaimVerify from './OrganizerClaimVerify';
import { renderWithProviders } from '../../test/utils';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

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

describe('OrganizerClaimVerify (#415)', () => {
  afterEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('shows error when no token in URL', () => {
    renderWithProviders(<OrganizerClaimVerify />, { route: '/organizer/claims/verify' });
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('verifies the claim-link token, signs the organizer in, and lands pre-selected on the pending screen', async () => {
    mockPost.mockResolvedValueOnce({ claim: { id: 42 } });

    renderWithProviders(<OrganizerClaimVerify />, { route: '/organizer/claims/verify?token=valid' });

    await waitFor(() => expect(mockSetOrganizerSignedInHint).toHaveBeenCalled());
    expect(mockPost).toHaveBeenCalledWith('/organizer/claims/verify-link', { token: 'valid' });
    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/organizer/claims/42/pending', { replace: true }),
    );
  });

  it('on verify failure: shows error state', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Link expired'));

    renderWithProviders(<OrganizerClaimVerify />, { route: '/organizer/claims/verify?token=expired' });

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Link expired')).toBeInTheDocument();
  });
});

describe('OrganizerClaimVerify locale', () => {
  // The page speaks the URL's language (like the Footer under it, #497) —
  // never the saved preference, mocked to 'en' above.
  it('renders in the URL prefix\'s language', () => {
    renderWithProviders(<OrganizerClaimVerify />, { route: '/ru/organizer/claims/verify' });
    expect(screen.getAllByText(t('no_token', 'ru')).length).toBeGreaterThan(0);
  });

  it('renders Estonian on a bare path', () => {
    renderWithProviders(<OrganizerClaimVerify />, { route: '/organizer/claims/verify' });
    expect(screen.getAllByText(t('no_token', 'et')).length).toBeGreaterThan(0);
  });
});
