import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminClaims from './AdminClaims';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { adminApi, ApiError } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);

const pendingClaims = {
  total: 2,
  claims: [
    {
      id: 1,
      kind: 'publisher',
      status: 'pending',
      organizer: { id: 9, email: 'jazz@example.com', name: 'Kesklinna Jazz Klubi' },
      publisher: { id: 5, name: 'KUMU' },
      event_series_key: null,
      verification_mechanism: 'dns_txt',
      verification_domain: 'kesklinnajazz.ee',
      dns_record_name: '_eventradar-verify.kesklinnajazz.ee',
      proof_token: 'er-verify-abc123',
      event_id: 42,
      event_title: 'Jazz Night',
      counts_toward_trust: true,
      created_at: '2026-09-19T07:00:00Z',
      resolved_at: null,
    },
    {
      id: 2,
      kind: 'series',
      status: 'pending',
      organizer: { id: 10, email: 'vinyl@example.com', name: null },
      publisher: null,
      event_series_key: 'Vinyl Nights\x1fKultuurikatel',
      verification_mechanism: 'admin_review',
      verification_domain: null,
      dns_record_name: null,
      proof_token: 'er-verify-def456',
      event_id: null,
      event_title: null,
      counts_toward_trust: true,
      created_at: '2026-09-18T07:00:00Z',
      resolved_at: null,
    },
  ],
};

const approvedClaims = {
  total: 1,
  claims: [
    {
      id: 3,
      kind: 'publisher',
      status: 'approved',
      organizer: { id: 11, email: 'oolaev@example.com', name: 'Öölaev Events' },
      publisher: { id: 6, name: 'Fienta: Öölaev' },
      event_series_key: null,
      verification_mechanism: 'fienta_token',
      verification_domain: null,
      dns_record_name: null,
      proof_token: 'er-verify-ghi789',
      event_id: 55,
      event_title: 'Boat Party',
      counts_toward_trust: false,
      created_at: '2026-09-01T07:00:00Z',
      resolved_at: '2026-09-01T08:00:00Z',
    },
  ],
};

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('AdminClaims', () => {
  it('lists pending claims with per-mechanism evidence', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    renderWithProviders(<AdminClaims />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kesklinna Jazz Klubi' })).toBeInTheDocument());
    expect(screen.getByText('DNS-TXT check')).toBeInTheDocument();
    expect(screen.getByText('_eventradar-verify.kesklinnajazz.ee')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('status=pending'));
  });

  it('shows claimant-identity-only evidence for a series claim with no automated check', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    renderWithProviders(<AdminClaims />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kesklinna Jazz Klubi' })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /vinyl@example.com/ }));
    expect(screen.getByText('Claimant identity')).toBeInTheDocument();
  });

  it('links the detail panel to the full event inspector only when an event is resolved', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    renderWithProviders(<AdminClaims />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kesklinna Jazz Klubi' })).toBeInTheDocument());
    expect(screen.getByRole('link', { name: /Open full details/ })).toHaveAttribute('href', '/admin/events/42');

    await userEvent.click(screen.getByRole('button', { name: /vinyl@example.com/ }));
    expect(screen.queryByRole('link', { name: /Open full details/ })).not.toBeInTheDocument();
  });

  it('requires a note before grant/decline are enabled', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    renderWithProviders(<AdminClaims />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Grant claim' })).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Decline claim' })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/resolution note/i), 'DNS record confirmed manually.');
    expect(screen.getByRole('button', { name: 'Grant claim' })).toBeEnabled();
  });

  it('grants a claim with the typed note and tags it in the list', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    mockPost.mockResolvedValueOnce({ id: 1, status: 'approved', note: 'DNS record confirmed manually.' });
    renderWithProviders(<AdminClaims />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kesklinna Jazz Klubi' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/resolution note/i), 'DNS record confirmed manually.');
    await userEvent.click(screen.getByRole('button', { name: 'Grant claim' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/claims/1/grant',
      { resolution_note: 'DNS record confirmed manually.' },
    ));
    expect(await screen.findByText(/Granted\./)).toBeInTheDocument();
  });

  it('declines a claim with the typed note', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    mockPost.mockResolvedValueOnce({ id: 1, status: 'revoked', note: "Domain didn't match." });
    renderWithProviders(<AdminClaims />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kesklinna Jazz Klubi' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/resolution note/i), "Domain didn't match.");
    await userEvent.click(screen.getByRole('button', { name: 'Decline claim' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/claims/1/decline',
      { resolution_note: "Domain didn't match." },
    ));
    expect(await screen.findByText(/Declined\./)).toBeInTheDocument();
  });

  it('shows an error toast and leaves the claim actionable when grant fails', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    mockPost.mockRejectedValueOnce(new ApiError(429, 'Too many requests.'));
    renderWithProviders(<AdminClaims />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kesklinna Jazz Klubi' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/resolution note/i), 'note');
    await userEvent.click(screen.getByRole('button', { name: 'Grant claim' }));

    expect(await screen.findByText('Too many requests.')).toBeInTheDocument();
    expect(screen.queryByText(/Granted\./)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Grant claim' })).toBeEnabled();
  });

  it('shows an empty state when there are no pending claims', async () => {
    mockGet.mockResolvedValueOnce({ total: 0, claims: [] });
    renderWithProviders(<AdminClaims />);
    await waitFor(() => expect(screen.getByText('No claims pending review.')).toBeInTheDocument());
  });

  it('switches to the Granted tab, warns about trust/pin impact, and revokes with a note', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    mockGet.mockResolvedValueOnce(approvedClaims);
    mockPost.mockResolvedValueOnce({ id: 3, event_id: 55, note: 'Escalated from a content report.' });
    renderWithProviders(<AdminClaims />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kesklinna Jazz Klubi' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('tab', { name: 'Granted' }));

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Öölaev Events' })).toBeInTheDocument());
    expect(mockGet).toHaveBeenLastCalledWith(expect.stringContaining('status=approved'));
    expect(screen.queryByText('Grant claim', { exact: false })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Revoke claim' })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Escalated from a content report.');
    await userEvent.click(screen.getByRole('button', { name: 'Revoke claim' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/claims/3/revoke',
      { resolution_note: 'Escalated from a content report.' },
    ));
    expect(await screen.findByText(/Revoked\./)).toBeInTheDocument();
  });

  it('does not show the trust-strip warning for a Fienta-sourced approved claim', async () => {
    mockGet.mockResolvedValueOnce({ total: 0, claims: [] });
    mockGet.mockResolvedValueOnce(approvedClaims);
    renderWithProviders(<AdminClaims />);

    await waitFor(() => expect(screen.getByText('No claims pending review.')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('tab', { name: 'Granted' }));

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Öölaev Events' })).toBeInTheDocument());
    expect(screen.queryByText(/Trusted-claimant status/)).not.toBeInTheDocument();
  });
});
