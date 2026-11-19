import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import { focusManager } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import AdminClaims from './AdminClaims';
import { LocationProbe, makeTestQueryClient, renderWithProviders } from '../../test/utils';
import { QUERY_KEYS, QUERY_STALE_TIME } from '../../constants/api';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { adminApi, ApiError } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);

const pendingClaims = {
  total: 3,
  offset: 0,
  claims: [
    {
      id: 1,
      kind: 'publisher',
      status: 'pending',
      organizer: { id: 9, email: 'jazz@example.com', name: 'Kesklinna Jazz Klubi' },
      publisher: { id: 5, name: 'KUMU' },
      event_series_key: null,
      verification_mechanism: 'dns_txt',
      verification_domain: 'jazz-venue.example',
      verification_contact: null,
      dns_record_name: '_eventradar-verify.jazz-venue.example',
      proof_token: 'er-verify-abc123',
      justification: null,
      event_id: 42,
      event_title: 'Jazz Night',
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
      verification_contact: null,
      dns_record_name: null,
      proof_token: 'er-verify-def456',
      justification: "We've run this monthly night at Kultuurikatel since 2023.",
      event_id: null,
      event_title: null,
      created_at: '2026-09-18T07:00:00Z',
      resolved_at: null,
    },
    {
      id: 4,
      kind: 'publisher',
      status: 'pending',
      organizer: { id: 12, email: 'promoter@example.com', name: null },
      publisher: { id: 7, name: 'Example Circus' },
      event_series_key: null,
      verification_mechanism: 'piletilevi_mailbox',
      verification_domain: null,
      verification_contact: 'bookings@examplecircus.example',
      dns_record_name: null,
      proof_token: 'er-verify-jkl012',
      justification: null,
      event_id: null,
      event_title: null,
      created_at: '2026-09-17T07:00:00Z',
      resolved_at: null,
    },
  ],
};

const approvedClaims = {
  total: 1,
  offset: 0,
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
      verification_contact: null,
      dns_record_name: null,
      proof_token: 'er-verify-ghi789',
      justification: null,
      event_id: 55,
      event_title: 'Boat Party',
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
    expect(screen.getByText('_eventradar-verify.jazz-venue.example')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith('/admin/claims?status=pending&limit=50&offset=0');
  });

  it('shows claimant identity plus the justification for a series claim', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    renderWithProviders(<AdminClaims />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kesklinna Jazz Klubi' })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /vinyl@example.com/ }));
    expect(screen.getByText('Claimant identity')).toBeInTheDocument();
    expect(screen.getByText(/We've run this monthly night at Kultuurikatel since 2023\./)).toBeInTheDocument();
  });

  it('shows the claimant email vs. resolved contact for a piletilevi_mailbox mismatch', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    renderWithProviders(<AdminClaims />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kesklinna Jazz Klubi' })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /promoter@example.com/ }));
    expect(screen.getByText('Contact-mailbox check')).toBeInTheDocument();
    expect(screen.getAllByText('promoter@example.com').length).toBeGreaterThan(0);
    expect(screen.getByText('bookings@examplecircus.example')).toBeInTheDocument();
    expect(screen.getByText('No match')).toBeInTheDocument();
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
    mockGet.mockResolvedValue(pendingClaims);
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
    mockGet.mockResolvedValue(pendingClaims);
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
    mockGet.mockResolvedValueOnce({ total: 0, offset: 0, claims: [] });
    renderWithProviders(<AdminClaims />);
    await waitFor(() => expect(screen.getByText('No claims pending review.')).toBeInTheDocument());
  });

  it('switches to the Granted tab, warns about trust/pin impact, and revokes with a note', async () => {
    mockGet.mockResolvedValueOnce(pendingClaims);
    mockGet.mockResolvedValue(approvedClaims);
    mockPost.mockResolvedValueOnce({ id: 3, event_id: 55, note: 'Escalated from a content report.' });
    renderWithProviders(<AdminClaims />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kesklinna Jazz Klubi' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('tab', { name: 'Granted' }));

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Öölaev Events' })).toBeInTheDocument());
    expect(mockGet).toHaveBeenCalledWith('/admin/claims?status=approved&limit=50&offset=0');
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

  it('warns about revoking an approved claim without mentioning Trusted-claimant status', async () => {
    mockGet.mockResolvedValueOnce({ total: 0, offset: 0, claims: [] });
    mockGet.mockResolvedValueOnce(approvedClaims);
    renderWithProviders(<AdminClaims />);

    await waitFor(() => expect(screen.getByText('No claims pending review.')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('tab', { name: 'Granted' }));

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Öölaev Events' })).toBeInTheDocument());
    expect(screen.getByText(/reverts the event's pinned fields to source/)).toBeInTheDocument();
    expect(screen.queryByText(/Trusted-claimant status/)).not.toBeInTheDocument();
  });

  describe('numbered pager and URL state (spec #551)', () => {
    function claim(id: number, status = 'pending') {
      return {
        ...pendingClaims.claims[1],
        id,
        status,
        organizer: { id, email: `claimant${id}@example.com`, name: `Claimant ${id}` },
      };
    }

    /** A fake server: GETs slice the live rows of the requested tab by
     * offset, and a grant/decline/revoke takes its row out of its list. */
    function serveClaims(pending: number[], approved: number[] = []) {
      const lists: Record<string, number[]> = { pending: [...pending], approved: [...approved] };
      mockGet.mockImplementation(async (url: string) => {
        const params = new URL(url, 'http://x').searchParams;
        const tab = params.get('status') ?? 'pending';
        const live = lists[tab];
        const limit = Number(params.get('limit'));
        const offset = Number(params.get('offset'));
        return {
          total: live.length,
          limit,
          offset,
          has_more: offset + limit < live.length,
          claims: live.slice(offset, offset + limit).map((id) => claim(id, tab)),
        } as never;
      });
      mockPost.mockImplementation(async (path: string) => {
        const id = Number(/claims\/(\d+)\//.exec(path)?.[1]);
        for (const live of Object.values(lists)) {
          if (live.includes(id)) live.splice(live.indexOf(id), 1);
        }
        return { id, note: 'ok' } as never;
      });
      return lists;
    }

    const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, k) => from + k);
    const rowButton = (id: number) => screen.getByRole('button', { name: new RegExp(`^Claimant ${id}\\b`) });
    const listRowCount = () => screen.getAllByRole('button', { name: /^Claimant \d+\b/ }).length;
    const claimsGets = () => mockGet.mock.calls.filter(([url]) => String(url).startsWith('/admin/claims?')).length;
    const renderQueue = (route: string) =>
      renderWithProviders(
        <>
          <AdminClaims />
          <LocationProbe />
        </>,
        { route },
      );
    const grantWithNote = async () => {
      await userEvent.type(screen.getByLabelText(/resolution note/i), 'ok');
      await userEvent.click(screen.getByRole('button', { name: 'Grant claim' }));
    };

    it('requests 50 per page from ?page and shows the range label in place of Load more', async () => {
      serveClaims(range(1, 120));
      renderQueue('/admin/claims?page=2');

      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 51' })).toBeInTheDocument());
      expect(mockGet).toHaveBeenCalledWith('/admin/claims?status=pending&limit=50&offset=50');
      expect(screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === '51–100 of 120')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Page 2' })).toHaveAttribute('aria-current', 'page');
      expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
    });

    it('reads the tab from the URL and keeps it in the pager links', async () => {
      serveClaims([], range(1, 120));
      renderQueue('/admin/claims?status=approved&page=2');

      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 51' })).toBeInTheDocument());
      expect(mockGet).toHaveBeenCalledWith('/admin/claims?status=approved&limit=50&offset=50');
      expect(screen.getByRole('tab', { name: 'Granted' })).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByRole('link', { name: 'Page 3' })).toHaveAttribute('href', '/admin/claims?status=approved&page=3');
    });

    it('switching tabs is one push to page 1 that omits the default tab', async () => {
      serveClaims(range(1, 120), [200]);
      renderQueue('/admin/claims?page=3');
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 101' })).toBeInTheDocument());

      await userEvent.click(screen.getByRole('tab', { name: 'Granted' }));
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 200' })).toBeInTheDocument());
      expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/admin\/claims\?status=approved$/);

      await userEvent.click(screen.getByRole('tab', { name: 'Pending review' }));
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());
      expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/admin\/claims$/);
    });

    it('treats an unknown ?status as the pending tab', async () => {
      serveClaims([1]);
      renderQueue('/admin/claims?status=bogus');
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());
      expect(mockGet).toHaveBeenCalledWith('/admin/claims?status=pending&limit=50&offset=0');
    });

    it('marks the selected row aria-current="true"', async () => {
      serveClaims([1, 2]);
      renderQueue('/admin/claims');
      await waitFor(() => expect(rowButton(1)).toHaveAttribute('aria-current', 'true'));
      await userEvent.click(rowButton(2));
      expect(rowButton(2)).toHaveAttribute('aria-current', 'true');
      expect(rowButton(1)).not.toHaveAttribute('aria-current');
    });

    it('refetches once per grant: the tagged row stays, the pulled-up row goes at the bottom', async () => {
      serveClaims(range(1, 60));
      renderQueue('/admin/claims');
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());
      expect(claimsGets()).toBe(1);

      await userEvent.click(rowButton(3));
      await grantWithNote();

      await waitFor(() => expect(listRowCount()).toBe(51));
      expect(claimsGets()).toBe(2);
      expect(rowButton(3)).toHaveTextContent('Granted');
      expect(rowButton(51)).not.toHaveTextContent('Granted');
      expect(screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === '1–50 of 59')).toBeInTheDocument();
    });

    it('refetches after a revoke on the Granted tab too', async () => {
      serveClaims([], range(1, 60));
      renderQueue('/admin/claims?status=approved');
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());

      await userEvent.type(screen.getByLabelText(/resolution note/i), 'ok');
      await userEvent.click(screen.getByRole('button', { name: 'Revoke claim' }));

      await waitFor(() => expect(listRowCount()).toBe(51));
      expect(mockGet).toHaveBeenLastCalledWith('/admin/claims?status=approved&limit=50&offset=0');
      expect(rowButton(1)).toHaveTextContent('Revoked');
    });

    it('holds an emptied last page while its rows are tagged, with the no-items label', async () => {
      serveClaims(range(1, 51));
      renderQueue('/admin/claims?page=2');
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 51' })).toBeInTheDocument());

      await userEvent.type(screen.getByLabelText(/resolution note/i), 'ok');
      await userEvent.click(screen.getByRole('button', { name: 'Decline claim' }));

      expect(await screen.findByText('No items on this page · 50 total')).toBeInTheDocument();
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/admin/claims?page=2');
      expect(rowButton(51)).toHaveTextContent('Declined');
    });

    it('clamps to the new last page when the page empties for any other reason', async () => {
      const lists = serveClaims(range(1, 51));
      renderQueue('/admin/claims?page=2');
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 51' })).toBeInTheDocument());

      lists.pending.splice(lists.pending.indexOf(51), 1);
      act(() => {
        focusManager.setFocused(false);
        focusManager.setFocused(true);
      });

      await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/admin\/claims$/));
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());
      act(() => focusManager.setFocused(undefined));
    });

    it('on a page change selects and focuses the first row and clears the tags', async () => {
      serveClaims(range(1, 120));
      renderQueue('/admin/claims');
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());
      await grantWithNote();
      await waitFor(() => expect(claimsGets()).toBe(2));

      await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

      // 119 live rows after the grant: page 2 starts at Claimant 52.
      await waitFor(() => expect(rowButton(52)).toHaveFocus());
      expect(rowButton(52)).toHaveAttribute('aria-current', 'true');
      expect(screen.queryByText(/Granted\./)).not.toBeInTheDocument();
      expect(screen.getAllByRole('button').some((b) => /Claimant 1\b.*Granted/.test(b.textContent ?? ''))).toBe(false);
    });

    it('a grant marks the other tab stale, so switching to it refetches within the stale time', async () => {
      const lists = serveClaims(range(1, 3), [10]);
      // Granting moves the claim to the Granted list on the server.
      const post = mockPost.getMockImplementation()!;
      mockPost.mockImplementation(async (path: string, body?: unknown) => {
        const result = await post(path, body);
        const id = Number(/claims\/(\d+)\//.exec(path)?.[1]);
        if (path.includes('grant')) lists.approved.unshift(id);
        return result;
      });
      const queryClient = makeTestQueryClient({ staleTime: QUERY_STALE_TIME });
      renderWithProviders(<AdminClaims />, { route: '/admin/claims?status=approved', queryClient });
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 10' })).toBeInTheDocument());
      await userEvent.click(screen.getByRole('tab', { name: 'Pending review' }));
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());
      await grantWithNote();
      await waitFor(() => expect(rowButton(1)).toHaveTextContent('Granted'));

      await userEvent.click(screen.getByRole('tab', { name: 'Granted' }));

      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());
      expect(rowButton(10)).toBeInTheDocument();
    });

    it('still shows the error toast when the admin switched tab before the action failed', async () => {
      serveClaims(range(1, 3), [10]);
      let reject!: (e: unknown) => void;
      mockPost.mockImplementation(() => new Promise((_res, rej) => { reject = rej; }) as never);
      renderQueue('/admin/claims');
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());
      await grantWithNote();
      await userEvent.click(screen.getByRole('tab', { name: 'Granted' }));
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 10' })).toBeInTheDocument());

      await act(async () => { reject(new ApiError(409, 'This claim was already resolved.')); });

      expect(await screen.findByText('This claim was already resolved.')).toBeInTheDocument();
    });

    it('refetches the newly shown tab once when an action started on the other tab succeeds', async () => {
      const lists = serveClaims(range(1, 3), [10]);
      let resolve!: () => void;
      mockPost.mockImplementation((path: string) => new Promise((res) => {
        resolve = () => {
          const id = Number(/claims\/(\d+)\//.exec(path)?.[1]);
          lists.pending.splice(lists.pending.indexOf(id), 1);
          lists.approved.unshift(id);
          res({ id, note: 'ok' });
        };
      }) as never);
      renderQueue('/admin/claims');
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());
      await grantWithNote();
      await userEvent.click(screen.getByRole('tab', { name: 'Granted' }));
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 10' })).toBeInTheDocument());
      const before = claimsGets();

      await act(async () => { resolve(); });

      await waitFor(() => expect(rowButton(1)).toBeInTheDocument());
      await new Promise((r) => setTimeout(r, 50));
      expect(claimsGets() - before).toBe(1);
    });

    it('refetches the page and the counts when another admin already resolved the claim', async () => {
      const lists = serveClaims(range(1, 3));
      mockPost.mockImplementation(async () => {
        lists.pending.splice(lists.pending.indexOf(1), 1);
        throw new ApiError(409, 'This claim was already resolved.');
      });
      const queryClient = makeTestQueryClient();
      queryClient.setQueryData([QUERY_KEYS.adminCounts], { claims: 3 });
      renderWithProviders(<AdminClaims />, { route: '/admin/claims', queryClient });
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());

      await grantWithNote();

      expect(await screen.findByText('This claim was already resolved.')).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByRole('button', { name: /^Claimant 1\b/ })).not.toBeInTheDocument());
      expect(queryClient.getQueryState([QUERY_KEYS.adminCounts])?.isInvalidated).toBe(true);
    });

    it('does not carry a tagged row over to the other tab', async () => {
      serveClaims(range(1, 3), [10]);
      renderQueue('/admin/claims');
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 1' })).toBeInTheDocument());
      await userEvent.type(screen.getByLabelText(/resolution note/i), 'ok');
      await userEvent.click(screen.getByRole('button', { name: 'Decline claim' }));
      await waitFor(() => expect(rowButton(1)).toHaveTextContent('Declined'));

      await userEvent.click(screen.getByRole('tab', { name: 'Granted' }));
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Claimant 10' })).toBeInTheDocument());
      expect(screen.queryByText('Declined')).not.toBeInTheDocument();
    });
  });
});
