import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ClaimEventPicker from './ClaimEventPicker';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn(), post: vi.fn() },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPost = vi.mocked(organizerApi.post);

const candidate = { id: 42, title: 'Jazz Night', venue_name: 'Rock Hall', starts_at: '2026-08-01T18:00:00Z', image_url: null };

function mockClaimGet(suggestions: unknown = { events: [] }, search: unknown = { events: [] }) {
  mockGet.mockImplementation((path: string) =>
    Promise.resolve(path.includes('/search') ? search : suggestions),
  );
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('ClaimEventPicker', () => {
  it('shows the suggestions list when the account has matches', async () => {
    mockClaimGet({ events: [candidate] });
    renderWithProviders(<ClaimEventPicker locale="en" onClaimed={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    expect(screen.getByText('Suggested for you')).toBeInTheDocument();
  });

  it('hides the suggestions section when there are none', async () => {
    mockClaimGet({ events: [] });
    renderWithProviders(<ClaimEventPicker locale="en" onClaimed={vi.fn()} />);
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(screen.queryByText('Suggested for you')).not.toBeInTheDocument();
  });

  it('searches on typing and claims a result', async () => {
    mockClaimGet({ events: [] }, { events: [candidate] });
    mockPost.mockResolvedValueOnce({ status: 'pending' });
    const onClaimed = vi.fn();
    renderWithProviders(<ClaimEventPicker locale="en" onClaimed={onClaimed} />);

    await userEvent.type(screen.getByRole('combobox'), 'jazz');
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument(), { timeout: 2000 });

    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));

    expect(mockPost).toHaveBeenCalledWith('/organizer/claims', { event_id: 42 });
    await waitFor(() => expect(onClaimed).toHaveBeenCalledWith('pending'));
  });

  it('shows an inline error when claiming fails', async () => {
    mockClaimGet({ events: [candidate] });
    mockPost.mockRejectedValueOnce(new Error('network'));
    renderWithProviders(<ClaimEventPicker locale="en" onClaimed={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});
