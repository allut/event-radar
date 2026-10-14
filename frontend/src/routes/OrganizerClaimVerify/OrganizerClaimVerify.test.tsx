import { t } from '../../i18n';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import OrganizerClaimVerify from './OrganizerClaimVerify';
import { QueryClient } from '@tanstack/react-query';
import { renderWithProviders } from '../../test/utils';
import { QUERY_KEYS, QUERY_STALE_TIME } from '../../constants/api';

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

/** A query client holding a cached organizer-claims list page, to observe
 * whether a claim mutation marks the list (and dashboard summary) stale. */
function clientWithCachedClaimsList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: QUERY_STALE_TIME }, mutations: { retry: false } },
  });
  queryClient.setQueryData(CACHED_CLAIMS_KEY, { claims: [], total: 0, offset: 0 });
  return queryClient;
}
const CACHED_CLAIMS_KEY = [QUERY_KEYS.organizerClaims, 'en', 1];

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

  it('marks the Your claims list and dashboard summary stale once the claim link creates the claim', async () => {
    mockPost.mockResolvedValueOnce({ claim: { id: 42 } });
    const queryClient = clientWithCachedClaimsList();

    renderWithProviders(<OrganizerClaimVerify />, { route: '/organizer/claims/verify?token=valid', queryClient });

    await waitFor(() => expect(mockSetOrganizerSignedInHint).toHaveBeenCalled());
    expect(queryClient.getQueryState(CACHED_CLAIMS_KEY)?.isInvalidated).toBe(true);
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
