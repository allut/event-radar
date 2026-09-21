import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ClaimPending from './ClaimPending';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn(), post: vi.fn() },
}));

vi.mock('../../hooks/useOrganizerLogout', () => ({
  useOrganizerLogout: () => vi.fn(),
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPost = vi.mocked(organizerApi.post);

function renderPending() {
  return renderWithProviders(<ClaimPending />, {
    route: '/organizer/claims/7/pending',
    pathPattern: '/organizer/claims/:id/pending',
  });
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

describe('ClaimPending (#415)', () => {
  it('shows the Fienta-token instructions and lets the organizer copy the code', async () => {
    mockGet.mockResolvedValueOnce({
      id: 7,
      status: 'pending',
      verification_mechanism: 'fienta_token',
      dns_record_name: null,
      dns_record_value: 'er-verify-abc123',
      can_recheck: true,
    });
    renderPending();

    await waitFor(() => expect(screen.getByText('Add your code to Fienta')).toBeInTheDocument());
    expect(screen.getByText('er-verify-abc123')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check now' })).toBeInTheDocument();
  });

  it('shows the DNS-TXT record instructions with record name and value', async () => {
    mockGet.mockResolvedValueOnce({
      id: 8,
      status: 'pending',
      verification_mechanism: 'dns_txt',
      dns_record_name: '_eventradar-verify.kumu.ekm.ee',
      dns_record_value: 'er-verify-xyz789',
      can_recheck: true,
    });
    renderPending();

    await waitFor(() => expect(screen.getByText('Add a DNS record')).toBeInTheDocument());
    expect(screen.getByText('_eventradar-verify.kumu.ekm.ee')).toBeInTheDocument();
    expect(screen.getByText('er-verify-xyz789')).toBeInTheDocument();
  });

  it('tracks copied state per field, not globally (#415 review fix)', async () => {
    mockGet.mockResolvedValueOnce({
      id: 8,
      status: 'pending',
      verification_mechanism: 'dns_txt',
      dns_record_name: '_eventradar-verify.kumu.ekm.ee',
      dns_record_value: 'er-verify-xyz789',
      can_recheck: true,
    });
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    renderPending();

    await waitFor(() => expect(screen.getByText('Add a DNS record')).toBeInTheDocument());
    const copyButtons = screen.getAllByRole('button', { name: 'Copy' });
    expect(copyButtons).toHaveLength(2);

    await userEvent.click(copyButtons[0]);

    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
  });

  it('shows the plain admin-review notice with no Check now button', async () => {
    mockGet.mockResolvedValueOnce({
      id: 9,
      status: 'pending',
      verification_mechanism: 'admin_review',
      dns_record_name: null,
      dns_record_value: 'er-verify-000',
      can_recheck: false,
    });
    renderPending();

    await waitFor(() => expect(screen.getByText('Your claim is being reviewed')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Check now' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel this claim' })).toBeInTheDocument();
  });

  it('shows the approved state with a link to the claim-editing surface', async () => {
    mockGet.mockResolvedValueOnce({
      id: 10,
      status: 'approved',
      verification_mechanism: 'fienta_token',
      dns_record_name: null,
      dns_record_value: 'er-verify-000',
      can_recheck: false,
    });
    renderPending();

    await waitFor(() => expect(screen.getByText("You're verified")).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Edit event' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel this claim' })).not.toBeInTheDocument();
  });

  it('check now re-runs verification and reflects a granted outcome', async () => {
    mockGet.mockResolvedValueOnce({
      id: 7,
      status: 'pending',
      verification_mechanism: 'fienta_token',
      dns_record_name: null,
      dns_record_value: 'er-verify-abc123',
      can_recheck: true,
    });
    mockPost.mockResolvedValueOnce({
      id: 7,
      status: 'approved',
      verification_mechanism: 'fienta_token',
      dns_record_name: null,
      dns_record_value: 'er-verify-abc123',
      can_recheck: false,
    });
    renderPending();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Check now' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Check now' }));

    expect(mockPost).toHaveBeenCalledWith('/organizer/claims/7/recheck');
    await waitFor(() => expect(screen.getByText("You're verified")).toBeInTheDocument());
  });

  it('self-cancel confirms then cancels the pending claim', async () => {
    mockGet.mockResolvedValueOnce({
      id: 7,
      status: 'pending',
      verification_mechanism: 'admin_review',
      dns_record_name: null,
      dns_record_value: 'er-verify-abc123',
      can_recheck: false,
    });
    mockPost.mockResolvedValueOnce({
      id: 7,
      status: 'cancelled',
      verification_mechanism: 'admin_review',
      dns_record_name: null,
      dns_record_value: 'er-verify-abc123',
      can_recheck: false,
    });
    renderPending();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Cancel this claim' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Cancel this claim' }));

    expect(mockPost).toHaveBeenCalledWith('/organizer/claims/7/cancel');
    await waitFor(() => expect(screen.getByText('Claim cancelled')).toBeInTheDocument());
  });
});
