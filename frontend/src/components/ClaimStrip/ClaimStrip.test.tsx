import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ClaimPanel, ClaimPill } from './ClaimStrip';
import { CACHED_CLAIMS_KEY, clientWithCachedClaimsList, renderWithProviders } from '../../test/utils';
import { ORGANIZER_SIGNED_IN_HINT_KEY } from '../../constants/auth';
import { CLAIM_JUSTIFICATION_REQUIRED_ERROR } from '../../constants/claims';

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>();
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
    organizerApi: { get: vi.fn(), post: vi.fn() },
  };
});

import { ApiError, organizerApi } from '../../api/client';
const mockOrganizerPost = vi.mocked(organizerApi.post);


describe('ClaimPill', () => {
  it('renders the pending label', () => {
    renderWithProviders(<ClaimPill status="pending" locale="en" />);
    expect(screen.getByText('Claim pending review')).toBeInTheDocument();
  });

  it('renders the claimed label', () => {
    renderWithProviders(<ClaimPill status="claimed" locale="en" />);
    expect(screen.getByText('Organizer-verified')).toBeInTheDocument();
  });
});

describe('ClaimPanel', () => {
  afterEach(() => {
    localStorage.removeItem(ORGANIZER_SIGNED_IN_HINT_KEY);
    mockOrganizerPost.mockReset();
  });

  it('shows an inline error and lets the organizer retry after a failed claim', async () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    mockOrganizerPost.mockRejectedValueOnce(new Error('network'));
    renderWithProviders(<ClaimPanel eventId={7} locale="en" />);

    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Claim this event' })).not.toBeDisabled();
  });

  it('lands an already-authenticated organizer on the pending screen for the created claim (#415)', async () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    mockOrganizerPost.mockResolvedValueOnce({ id: 42, status: 'pending' });
    renderWithProviders(null, {
      routes: [
        { path: '/', element: <ClaimPanel eventId={7} locale="en" /> },
        { path: '/organizer/claims/:id/pending', element: <div>pending-screen-42</div> },
      ],
    });

    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));

    await waitFor(() => expect(screen.getByText('pending-screen-42')).toBeInTheDocument());
  });

  it('marks the Your claims list and dashboard summary stale once the claim is created', async () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    mockOrganizerPost.mockResolvedValueOnce({ id: 42, status: 'pending' });
    const queryClient = clientWithCachedClaimsList();
    renderWithProviders(null, {
      routes: [
        { path: '/', element: <ClaimPanel eventId={7} locale="en" /> },
        { path: '/organizer/claims/:id/pending', element: <div>pending-screen-42</div> },
      ],
      queryClient,
    });

    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));

    await waitFor(() => expect(screen.getByText('pending-screen-42')).toBeInTheDocument());
    expect(queryClient.getQueryState(CACHED_CLAIMS_KEY)?.isInvalidated).toBe(true);
  });

  it('reveals a justification field when the claim resolves to a series claim (#428), then resubmits with it', async () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    mockOrganizerPost
      .mockRejectedValueOnce(new ApiError(422, CLAIM_JUSTIFICATION_REQUIRED_ERROR))
      .mockResolvedValueOnce({ id: 42, status: 'pending' });
    renderWithProviders(null, {
      routes: [
        { path: '/', element: <ClaimPanel eventId={7} locale="en" /> },
        { path: '/organizer/claims/:id/pending', element: <div>pending-screen-42</div> },
      ],
    });

    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));

    const textarea = await screen.findByPlaceholderText(/organize this recurring night/);
    const submitBtn = screen.getByRole('button', { name: 'Submit for review' });
    expect(submitBtn).toBeDisabled();

    await userEvent.type(textarea, 'I run this recurring night.');
    await userEvent.click(submitBtn);

    expect(mockOrganizerPost).toHaveBeenLastCalledWith('/organizer/claims', {
      event_id: 7,
      justification: 'I run this recurring night.',
    });
    await waitFor(() => expect(screen.getByText('pending-screen-42')).toBeInTheDocument());
  });
});
